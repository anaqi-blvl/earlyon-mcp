"""Fetch -> validate -> expand -> store."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from . import db, fetch
from .config import Config
from .expand import expand_all
from .normalize import CLOSURE_TYPE, build_venue_resolver, clean_title, html_to_text, program_type

log = logging.getLogger("earlyon.refresh")

# Refuse a snapshot that has lost more than this fraction of the previously stored occurrence total.
MAX_SHRINK = 0.30


def _fnum(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _first_image(raw: Any) -> str | None:
    if not raw:
        return None
    try:
        items = json.loads(raw) if isinstance(raw, str) else raw
        return items[0] if items else None
    except (ValueError, TypeError, IndexError):
        return raw if isinstance(raw, str) and raw.startswith("http") else None


def build_rows(cal: dict[str, Any], tz: str) -> list[db.Row]:
    """Expand a calendar payload into storable rows (deduplicated by occurrence id)."""
    events = cal["events"]
    resolve = build_venue_resolver(events)
    rows: dict[str, db.Row] = {}
    for ev, occ in expand_all(events, tz):
        html = ev.get("desc") or ""
        text, links = html_to_text(html)
        ptype = program_type(ev)
        name, addr = resolve(ev, text)
        v = ev.get("venue") or {}
        start_ts = occ.start.strftime("%Y-%m-%dT%H:%M")
        end_dt = occ.end
        if not occ.all_day and end_dt > occ.start and end_dt.hour == 0 and end_dt.minute == 0:
            end_date = end_dt.date() - timedelta(days=1)  # ends exactly at midnight
        else:
            end_date = end_dt.date()
        oid = f"{ev['id']}:{start_ts}"
        rows.setdefault(
            oid,
            db.Row(
                id=oid, series_id=int(ev["id"]), title=clean_title(ev.get("title", "")), program_type=ptype,
                is_closure=ptype == CLOSURE_TYPE, all_day=occ.all_day, start_ts=start_ts,
                end_ts=end_dt.strftime("%Y-%m-%dT%H:%M"), start_date=occ.start_date.isoformat(),
                end_date=end_date.isoformat(), venue_name=name, venue_address=addr,
                lat=_fnum(v.get("lat")), lng=_fnum(v.get("lng") or v.get("long")),
                description_text=text, description_html=html, links=links, image_url=_first_image(ev.get("image")),
            ),
        )
    return list(rows.values())


def payload_hash(cal: dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(cal.get("events"), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def refresh_once(cfg: Config, now: datetime | None = None, *, get_token: Callable | None = None,
                 get_calendar: Callable | None = None, get_page: Callable | None = None) -> dict[str, Any]:
    """Run one refresh. Never raises: failures are recorded and the previous data is kept."""
    tz = ZoneInfo(cfg.timezone)
    now = now or datetime.now(tz)
    get_token = get_token or (lambda: fetch.fetch_instance_token(cfg))
    get_calendar = get_calendar or (lambda tok: fetch.fetch_calendar(cfg, tok))
    get_page = get_page or (lambda: fetch.fetch_calendar_page(cfg))
    started = now.isoformat(timespec="seconds")

    def record_failure(status: str, err: str) -> dict[str, Any]:
        log.error("refresh %s: %s", status, err)
        with db.connect(cfg.db_path) as conn:
            conn.execute("INSERT INTO scrapes(started_at, finished_at, status, error) VALUES (?,?,?,?)",
                         (started, datetime.now(tz).isoformat(timespec="seconds"), status, err[:500]))
        return {"ok": False, "status": status, "error": err}

    try:
        cal = get_calendar(get_token())
    except Exception as e:  # noqa: BLE001 - recorded, previous data stays
        return record_failure("error", str(e))

    name = (cal.get("name") or "")
    if not name.startswith(cfg.expected_name_prefix):
        return record_failure("rejected", f"unexpected calendar name {name!r} (wrong comp_id or site changed)")
    if not cal["events"]:
        return record_failure("rejected", "calendar has zero events")
    try:
        rows = build_rows(cal, cfg.timezone)
    except Exception as e:  # noqa: BLE001
        return record_failure("error", f"expansion failed: {e}")
    if not rows:
        return record_failure("rejected", "expansion produced zero occurrences")

    with db.connect(cfg.db_path) as conn:
        prev = conn.execute("SELECT occurrences_in FROM scrapes WHERE status='ok' ORDER BY id DESC LIMIT 1").fetchone()
    if prev and prev["occurrences_in"] and prev["occurrences_in"] >= 20 and len(rows) < prev["occurrences_in"] * (1 - MAX_SHRINK):
        return record_failure("rejected", f"snapshot shrank from {prev['occurrences_in']} to {len(rows)} occurrences")

    regs: list[dict[str, Any]] | None = None
    try:
        regs = fetch.parse_registrations(get_page(), cfg.site_url, now.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%S"))
    except Exception as e:  # noqa: BLE001 - registrations are a bonus, never fatal
        log.warning("registrations fetch failed: %s", e)

    horizon = max(r.end_date for r in rows)
    with db.connect(cfg.db_path) as conn:
        cur = conn.execute("INSERT INTO scrapes(started_at, status, events_in, occurrences_in, horizon, payload_hash) VALUES (?,?,?,?,?,?)",
                           (started, "running", len(cal["events"]), len(rows), horizon, payload_hash(cal)))
        sid = cur.lastrowid
        stats = db.apply_snapshot(conn, rows, now.date(), now, sid)
        if regs is not None:
            db.replace_registrations(conn, regs, now)
        conn.execute("UPDATE scrapes SET status='ok', finished_at=?, added=?, removed=?, modified=?, initial=? WHERE id=?",
                     (datetime.now(tz).isoformat(timespec="seconds"), stats["added"], stats["removed"], stats["modified"], stats["initial"], sid))
    log.info("refresh ok: %d events -> %d occurrences, %s", len(cal["events"]), len(rows), stats)
    return {"ok": True, "status": "ok", "events": len(cal["events"]), "occurrences": len(rows), "horizon": horizon,
            "registrations": None if regs is None else len(regs), **stats}
