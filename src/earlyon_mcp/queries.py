"""Read-side queries and response shaping."""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from .normalize import type_matches


def fmt_time(ts: str) -> str:
    dt = datetime.strptime(ts[:16], "%Y-%m-%dT%H:%M")
    return dt.strftime("%I:%M %p").lstrip("0")


def fmt_date(d: date) -> str:
    return f"{d.strftime('%A, %B')} {d.day}, {d.year}"


def event_dict(r: sqlite3.Row, description: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": r["id"],
        "date": r["start_date"],
        "weekday": date.fromisoformat(r["start_date"]).strftime("%A"),
        "all_day": bool(r["all_day"]),
        "start": None if r["all_day"] else fmt_time(r["start_ts"]),
        "end": None if r["all_day"] else fmt_time(r["end_ts"]),
        "type": r["program_type"],
        "title": r["title"],
        "venue": r["venue_name"],
        "address": r["venue_address"],
    }
    if r["end_date"] != r["start_date"]:
        out["end_date"] = r["end_date"]
    if description:
        out["description"] = r["description_text"]
        links = json.loads(r["links_json"] or "[]")
        if links:
            out["links"] = links
    return out


def coverage(conn: sqlite3.Connection) -> dict[str, Any]:
    r = conn.execute("SELECT MIN(start_date) a, MAX(end_date) b, COUNT(*) n FROM occurrences").fetchone()
    last = conn.execute("SELECT finished_at, horizon FROM scrapes WHERE status='ok' ORDER BY id DESC LIMIT 1").fetchone()
    return {"earliest": r["a"], "latest": r["b"], "total_occurrences": r["n"],
            "last_refresh": last["finished_at"] if last else None}


def notes_for(conn: sqlite3.Connection, start: date, end: date, stale_hours: float, now: datetime) -> list[str]:
    cov = coverage(conn)
    notes: list[str] = []
    if not cov["total_occurrences"]:
        return ["No calendar data has been loaded yet; the first refresh may still be running or failing (see get_status)."]
    if cov["latest"] and end.isoformat() > cov["latest"]:
        notes.append(f"The published calendar only runs through {cov['latest']}; dates after that are not yet scheduled "
                     "(unknown, not necessarily empty).")
    if cov["earliest"] and start.isoformat() < cov["earliest"]:
        notes.append(f"History starts {cov['earliest']}; earlier dates are not available.")
    if cov["last_refresh"]:
        age = now.replace(tzinfo=None) - datetime.fromisoformat(cov["last_refresh"]).replace(tzinfo=None)
        if age > timedelta(hours=stale_hours * 2):
            notes.append(f"Data may be stale: last successful refresh was {cov['last_refresh']}.")
    else:
        notes.append("No successful refresh recorded yet; data may be stale or missing.")
    return notes


def between(conn: sqlite3.Connection, start: date, end: date, program_type: str | None = None,
            description: bool = False, limit: int = 300) -> dict[str, Any]:
    """Occurrences overlapping [start, end], split into events and closures."""
    rows = conn.execute(
        "SELECT * FROM occurrences WHERE start_date <= ? AND end_date >= ? ORDER BY start_ts, title",
        (end.isoformat(), start.isoformat()),
    ).fetchall()
    closures = [event_dict(r, description) for r in rows if r["is_closure"]]
    evs = [r for r in rows if not r["is_closure"] and type_matches(program_type, r["program_type"])]
    truncated = len(evs) > limit
    return {"events": [event_dict(r, description) for r in evs[:limit]], "closures": closures,
            "count": len(evs), "truncated": truncated}


def search(conn: sqlite3.Connection, query: str, since: date, until: date | None, program_type: str | None,
           newest_first: bool, limit: int) -> list[sqlite3.Row]:
    tokens = [t for t in query.lower().split() if t]
    where, args = ["start_date >= ?"], [since.isoformat()]
    if until:
        where.append("start_date <= ?")
        args.append(until.isoformat())
    for t in tokens:
        where.append("lower(title || ' ' || program_type || ' ' || coalesce(venue_name,'') || ' ' || "
                     "coalesce(venue_address,'') || ' ' || description_text) LIKE ?")
        args.append(f"%{t}%")
    order = "DESC" if newest_first else "ASC"
    rows = conn.execute(f"SELECT * FROM occurrences WHERE {' AND '.join(where)} ORDER BY start_ts {order} LIMIT ?",
                        (*args, limit * 3 if program_type else limit)).fetchall()
    rows = [r for r in rows if type_matches(program_type, r["program_type"])]
    return rows[:limit]


def program_types(conn: sqlite3.Connection, today: date) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT program_type, COUNT(*) total, SUM(CASE WHEN end_date >= ? THEN 1 ELSE 0 END) upcoming, "
        "MIN(title) sample FROM occurrences GROUP BY program_type ORDER BY total DESC", (today.isoformat(),)).fetchall()
    return [{"type": r["program_type"], "upcoming_occurrences": r["upcoming"], "total_occurrences": r["total"]} for r in rows]


def status(conn: sqlite3.Connection) -> dict[str, Any]:
    cov = coverage(conn)
    scrapes = conn.execute("SELECT started_at, finished_at, status, error, events_in, occurrences_in, added, removed, modified "
                           "FROM scrapes ORDER BY id DESC LIMIT 5").fetchall()
    ok = conn.execute("SELECT finished_at FROM scrapes WHERE status='ok' ORDER BY id DESC LIMIT 1").fetchone()
    return {"coverage": cov, "last_ok": ok["finished_at"] if ok else None, "recent_scrapes": [dict(s) for s in scrapes]}


def recent_changes(conn: sqlite3.Connection, since_iso: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM changes WHERE at >= ? ORDER BY at DESC, id DESC LIMIT ?", (since_iso, limit)).fetchall()
    return [{"change": r["kind"], "detected_at": r["at"], "title": r["title"], "type": r["program_type"],
             "date": r["start_ts"][:10], "start": fmt_time(r["start_ts"])} for r in rows]


def registrations(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [json.loads(r["data_json"]) for r in conn.execute("SELECT data_json FROM registrations ORDER BY event_id")]
