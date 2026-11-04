"""SQLite storage. Past occurrences are frozen; today-onward occurrences mirror the latest snapshot."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS occurrences (
  id TEXT PRIMARY KEY,
  series_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  program_type TEXT NOT NULL,
  is_closure INTEGER NOT NULL,
  all_day INTEGER NOT NULL,
  start_ts TEXT NOT NULL,
  end_ts TEXT NOT NULL,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  venue_name TEXT,
  venue_address TEXT,
  lat REAL,
  lng REAL,
  description_text TEXT NOT NULL DEFAULT '',
  description_html TEXT NOT NULL DEFAULT '',
  links_json TEXT NOT NULL DEFAULT '[]',
  image_url TEXT,
  content_hash TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_occ_start ON occurrences(start_date);
CREATE INDEX IF NOT EXISTS idx_occ_end ON occurrences(end_date);
CREATE TABLE IF NOT EXISTS scrapes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL,
  error TEXT,
  payload_hash TEXT,
  events_in INTEGER,
  occurrences_in INTEGER,
  horizon TEXT,
  added INTEGER NOT NULL DEFAULT 0,
  removed INTEGER NOT NULL DEFAULT 0,
  modified INTEGER NOT NULL DEFAULT 0,
  initial INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scrape_id INTEGER NOT NULL,
  at TEXT NOT NULL,
  kind TEXT NOT NULL,
  occurrence_id TEXT NOT NULL,
  title TEXT NOT NULL,
  program_type TEXT NOT NULL,
  start_ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_changes_at ON changes(at);
CREATE TABLE IF NOT EXISTS registrations (
  event_id TEXT PRIMARY KEY,
  data_json TEXT NOT NULL,
  fetched_at TEXT NOT NULL
);
"""


@dataclass
class Row:
    """An occurrence ready to store."""

    id: str
    series_id: int
    title: str
    program_type: str
    is_closure: bool
    all_day: bool
    start_ts: str
    end_ts: str
    start_date: str
    end_date: str
    venue_name: str | None
    venue_address: str | None
    lat: float | None
    lng: float | None
    description_text: str
    description_html: str
    links: list[dict[str, str]]
    image_url: str | None

    def content_hash(self) -> str:
        payload = json.dumps(
            [self.title, self.program_type, self.start_ts, self.end_ts, self.venue_name, self.venue_address,
             self.description_text, self.links],
            sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha1(payload.encode()).hexdigest()


@contextmanager
def connect(path: str) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def apply_snapshot(conn: sqlite3.Connection, rows: list[Row], today: date, now: datetime, scrape_id: int) -> dict[str, int]:
    """Merge a fresh expansion into the DB.

    * Occurrences that ended before ``today`` are frozen: inserted if missing, never modified or deleted.
    * Everything else is replaced to mirror the snapshot (cancellations disappear), and the delta is logged.
    """
    ts = now.isoformat(timespec="seconds")
    today_s = today.isoformat()
    initial = conn.execute("SELECT COUNT(*) FROM occurrences").fetchone()[0] == 0
    existing = {r["id"]: r for r in conn.execute("SELECT id, content_hash, title, program_type, start_ts FROM occurrences WHERE end_date >= ?", (today_s,))}
    added = removed = modified = 0
    seen: set[str] = set()

    def log_change(kind: str, oid: str, title: str, ptype: str, start_ts: str) -> None:
        if not initial:
            conn.execute(
                "INSERT INTO changes(scrape_id, at, kind, occurrence_id, title, program_type, start_ts) VALUES (?,?,?,?,?,?,?)",
                (scrape_id, ts, kind, oid, title, ptype, start_ts),
            )

    for r in rows:
        h = r.content_hash()
        vals = (r.series_id, r.title, r.program_type, int(r.is_closure), int(r.all_day), r.start_ts, r.end_ts,
                r.start_date, r.end_date, r.venue_name, r.venue_address, r.lat, r.lng, r.description_text,
                r.description_html, json.dumps(r.links, ensure_ascii=False), r.image_url)
        if r.end_date < today_s:  # frozen past
            conn.execute(
                "INSERT OR IGNORE INTO occurrences(id, series_id, title, program_type, is_closure, all_day, start_ts, end_ts, "
                "start_date, end_date, venue_name, venue_address, lat, lng, description_text, description_html, links_json, "
                "image_url, content_hash, first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r.id, *vals, h, ts, ts),
            )
            continue
        seen.add(r.id)
        old = existing.get(r.id)
        if old is None:
            conn.execute(
                "INSERT OR REPLACE INTO occurrences(id, series_id, title, program_type, is_closure, all_day, start_ts, end_ts, "
                "start_date, end_date, venue_name, venue_address, lat, lng, description_text, description_html, links_json, "
                "image_url, content_hash, first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r.id, *vals, h, ts, ts),
            )
            added += 1
            log_change("added", r.id, r.title, r.program_type, r.start_ts)
        else:
            if old["content_hash"] != h:
                modified += 1
                log_change("modified", r.id, r.title, r.program_type, r.start_ts)
            conn.execute(
                "UPDATE occurrences SET series_id=?, title=?, program_type=?, is_closure=?, all_day=?, start_ts=?, end_ts=?, "
                "start_date=?, end_date=?, venue_name=?, venue_address=?, lat=?, lng=?, description_text=?, description_html=?, "
                "links_json=?, image_url=?, content_hash=?, last_seen=? WHERE id=?",
                (*vals, h, ts, r.id),
            )
    for oid, old in existing.items():
        if oid not in seen:
            conn.execute("DELETE FROM occurrences WHERE id=?", (oid,))
            removed += 1
            log_change("removed", oid, old["title"], old["program_type"], old["start_ts"])
    return {"added": added, "removed": removed, "modified": modified, "initial": int(initial)}


def replace_registrations(conn: sqlite3.Connection, regs: list[dict[str, Any]], now: datetime) -> None:
    conn.execute("DELETE FROM registrations")
    for r in regs:
        conn.execute("INSERT INTO registrations(event_id, data_json, fetched_at) VALUES (?,?,?)",
                     (str(r["event_id"]), json.dumps(r, ensure_ascii=False), now.isoformat(timespec="seconds")))
