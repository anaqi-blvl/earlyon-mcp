"""MCP server (stdio). Wrap with mcp-proxy for streamable HTTP."""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from datetime import date, datetime, timedelta
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from . import __version__, db, queries
from .config import Config
from .dates import parse_date, today_in, week_bounds
from .refresh import refresh_once

log = logging.getLogger("earlyon.server")
cfg = Config.from_env()

INSTRUCTIONS = (
    "Family Space Quinte EarlyON program calendar (free playgroups, baby clubs, Wildwood outdoor programs, evening "
    "programs, special events) for Belleville / Quinte West / Tweed / Madoc / Marmora, Ontario. Times are Eastern. "
    "Use get_events for a single day, get_week for a week, get_events_range for arbitrary spans, search_events to "
    "find a program by name/place/topic (also works for past dates), get_event_details for the full description. "
    "Closures (stat holidays, weather, office closures) are returned in a separate 'closures' list - always mention "
    "them. Heed each response's 'notes' (data horizon, staleness)."
)

mcp = FastMCP("earlyon", instructions=INSTRUCTIONS)

_first_attempt_done = threading.Event()
_refresh_lock = threading.Lock()


def _conn():
    parent = os.path.dirname(os.path.abspath(cfg.db_path))
    os.makedirs(parent, exist_ok=True)
    return db.connect(cfg.db_path)


def _now() -> datetime:
    return datetime.now(ZoneInfo(cfg.timezone))


def _today() -> date:
    return today_in(cfg.timezone)


def _run_refresh() -> dict[str, Any]:
    with _refresh_lock:
        return refresh_once(cfg)


def _due() -> bool:
    with _conn() as conn:
        ok = conn.execute("SELECT finished_at FROM scrapes WHERE status='ok' ORDER BY id DESC LIMIT 1").fetchone()
        last = conn.execute("SELECT started_at, status FROM scrapes ORDER BY id DESC LIMIT 1").fetchone()
    now = _now().replace(tzinfo=None)
    ok_stale = ok is None or now - datetime.fromisoformat(ok["finished_at"]).replace(tzinfo=None) >= timedelta(hours=cfg.refresh_hours)
    if not ok_stale:
        return False
    if last and last["status"] != "ok":  # back off after a failure
        return now - datetime.fromisoformat(last["started_at"]).replace(tzinfo=None) >= timedelta(minutes=15)
    return True


def _background_loop() -> None:
    while True:
        try:
            if _due():
                _run_refresh()
        except Exception:  # noqa: BLE001
            log.exception("background refresh crashed")
        _first_attempt_done.set()
        time.sleep(60)


def _ensure_ready() -> None:
    """On a cold start the first tool call waits (briefly) for the initial load instead of returning nothing."""
    with _conn() as conn:
        has = conn.execute("SELECT 1 FROM occurrences LIMIT 1").fetchone()
    if not has:
        _first_attempt_done.wait(timeout=45)


def _meta(start: date, end: date) -> list[str]:
    with _conn() as conn:
        return queries.notes_for(conn, start, end, cfg.refresh_hours, _now())


def _date(arg: str | None, default: str = "today") -> date:
    return parse_date(arg or default, _today())


DateArg = Annotated[str, Field(description="'today', 'tomorrow', 'friday', 'next monday', 'in 3 days', '2026-11-12', or 'Nov 12'")]
TypeArg = Annotated[str | None, Field(description="Optional program-type filter, case-insensitive substring, e.g. 'morning', 'evening', 'wildwood', 'outdoor', 'afternoon'. Use list_program_types for the full list.")]


@mcp.tool()
def get_events(date: DateArg = "today", program_type: TypeArg = None, include_description: bool = False) -> dict[str, Any]:
    """Programs happening on one day (time, type, venue) plus any closures that day."""
    _ensure_ready()
    d = _date(date)
    with _conn() as conn:
        res = queries.between(conn, d, d, program_type, include_description)
    closed = [c["title"] for c in res["closures"]]
    summary = f"{res['count']} program(s) on {queries.fmt_date(d)}"
    if closed:
        summary += f" - CLOSURE NOTICE: {'; '.join(closed)}"
    return {"date": d.isoformat(), "weekday": d.strftime("%A"), "summary": summary, **res, "notes": _meta(d, d)}


@mcp.tool()
def get_week(week_of: Annotated[str, Field(description="'this', 'next', 'last', or any date inside the wanted Monday-Sunday week")] = "this",
             program_type: TypeArg = None, include_description: bool = False) -> dict[str, Any]:
    """A Monday-Sunday week of programs, grouped by day."""
    _ensure_ready()
    today = _today()
    anchor = {"this": today, "next": today + timedelta(days=7), "last": today - timedelta(days=7)}.get(week_of.strip().lower()) or _date(week_of)
    start, end = week_bounds(anchor)
    with _conn() as conn:
        res = queries.between(conn, start, end, program_type, include_description, limit=500)
    days = []
    for i in range(7):
        d = start + timedelta(days=i)
        iso = d.isoformat()
        days.append({"date": iso, "weekday": d.strftime("%A"),
                     "events": [e for e in res["events"] if e["date"] == iso],
                     "closures": [c["title"] for c in res["closures"] if c["date"] <= iso <= c.get("end_date", c["date"])]})
    return {"week_start": start.isoformat(), "week_end": end.isoformat(), "count": res["count"], "days": days, "notes": _meta(start, end)}


@mcp.tool()
def get_events_range(start: DateArg, end: DateArg, program_type: TypeArg = None, include_description: bool = False,
                     limit: Annotated[int, Field(ge=1, le=500)] = 200) -> dict[str, Any]:
    """Programs between two dates inclusive (past or future), sorted by time."""
    _ensure_ready()
    s, e = _date(start), _date(end)
    if e < s:
        raise ValueError("end date is before start date")
    with _conn() as conn:
        res = queries.between(conn, s, e, program_type, include_description, limit)
    return {"start": s.isoformat(), "end": e.isoformat(), **res, "notes": _meta(s, e)}


@mcp.tool()
def search_events(query: Annotated[str, Field(description="Words to find in title, type, venue, address or description, e.g. 'baby club', 'Tweed', 'storywalk'")],
                  since: Annotated[str | None, Field(description="Earliest date (default today). Use a past date to search history.")] = None,
                  until: Annotated[str | None, Field(description="Latest date (default: no limit)")] = None,
                  program_type: TypeArg = None,
                  newest_first: Annotated[bool, Field(description="True to list latest first, e.g. 'when was the last ...'")] = False,
                  limit: Annotated[int, Field(ge=1, le=100)] = 25, include_description: bool = False) -> dict[str, Any]:
    """Find occurrences of programs by name, place or topic."""
    _ensure_ready()
    s = _date(since)
    u = _date(until) if until else None
    with _conn() as conn:
        rows = queries.search(conn, query, s, u, program_type, newest_first, limit)
    return {"query": query, "since": s.isoformat(), "count": len(rows),
            "events": [queries.event_dict(r, include_description) for r in rows], "notes": _meta(s, u or s)}


@mcp.tool()
def get_event_details(event_id: Annotated[str, Field(description="An 'id' from another tool, e.g. '3526559:2026-11-04T09:30'. A bare series id (digits) returns that program's next occurrence.")]) -> dict[str, Any]:
    """Full details for one occurrence: description text, links, venue, and the program's other upcoming dates."""
    _ensure_ready()
    today = _today()
    with _conn() as conn:
        row = conn.execute("SELECT * FROM occurrences WHERE id=?", (event_id,)).fetchone()
        if row is None and event_id.strip().isdigit():
            row = conn.execute("SELECT * FROM occurrences WHERE series_id=? AND end_date>=? ORDER BY start_ts LIMIT 1",
                               (int(event_id), today.isoformat())).fetchone()
        if row is None:
            raise ValueError(f"No event with id {event_id!r}. Use search_events or get_events to find ids.")
        upcoming = conn.execute("SELECT start_ts FROM occurrences WHERE series_id=? AND end_date>=? AND id<>? ORDER BY start_ts LIMIT 8",
                                (row["series_id"], today.isoformat(), row["id"])).fetchall()
    out = queries.event_dict(row, description=True)
    out["other_upcoming_dates"] = [f"{u['start_ts'][:10]} {queries.fmt_time(u['start_ts'])}" for u in upcoming]
    return out


@mcp.tool()
def list_program_types() -> dict[str, Any]:
    """The program categories (Morning Indoor, Wildwood Outdoor, Afternoon Indoor, Evening, ...) with counts."""
    _ensure_ready()
    with _conn() as conn:
        return {"types": queries.program_types(conn, _today())}


@mcp.tool()
def get_closures(start: DateArg = "today", end: Annotated[str | None, Field(description="Default: 90 days after start")] = None) -> dict[str, Any]:
    """Closure notices (stat holidays, office/program closures) in a date range."""
    _ensure_ready()
    s = _date(start)
    e = _date(end) if end else s + timedelta(days=90)
    with _conn() as conn:
        res = queries.between(conn, s, e)
    return {"start": s.isoformat(), "end": e.isoformat(), "closures": res["closures"], "notes": _meta(s, e)}


@mcp.tool()
def get_registrations() -> dict[str, Any]:
    """Special programs that require pre-registration (e.g. Infant Massage, ASQ Connection) with open/closed state."""
    _ensure_ready()
    with _conn() as conn:
        regs = queries.registrations(conn)
    return {"count": len(regs), "registrations": regs,
            "notes": ["Registration state is derived from the registration window; confirm on the website before relying on it."]}


@mcp.tool()
def get_recent_changes(days: Annotated[int, Field(ge=1, le=60)] = 7) -> dict[str, Any]:
    """Upcoming programs that were added, removed (cancelled) or edited recently."""
    _ensure_ready()
    since = (_now() - timedelta(days=days)).replace(tzinfo=None).isoformat(timespec="seconds")
    with _conn() as conn:
        ch = queries.recent_changes(conn, since)
    return {"days": days, "count": len(ch), "changes": ch,
            "notes": ["The site removes cancelled programs from the calendar, so 'removed' usually means cancelled or rescheduled."]}


@mcp.tool()
def get_status() -> dict[str, Any]:
    """Data freshness and coverage (last refresh, earliest/latest dates, recent refresh outcomes)."""
    _ensure_ready()
    with _conn() as conn:
        st = queries.status(conn)
    return {"version": __version__, "timezone": cfg.timezone, "refresh_every_hours": cfg.refresh_hours, **st}


@mcp.tool()
def refresh_now() -> dict[str, Any]:
    """Force a refresh from the website (rate limited; normally refreshes automatically every few hours)."""
    with _conn() as conn:
        last = conn.execute("SELECT started_at FROM scrapes ORDER BY id DESC LIMIT 1").fetchone()
    if last:
        age = _now().replace(tzinfo=None) - datetime.fromisoformat(last["started_at"]).replace(tzinfo=None)
        if age < timedelta(minutes=cfg.min_manual_refresh_minutes):
            return {"skipped": True, "reason": f"last refresh attempt was {int(age.total_seconds() // 60)} min ago"}
    return _run_refresh()


def run() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    threading.Thread(target=_background_loop, name="earlyon-refresh", daemon=True).start()
    mcp.run()
