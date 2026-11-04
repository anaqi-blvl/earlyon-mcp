import copy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from conftest import make_event
from earlyon_mcp import db, queries
from earlyon_mcp.config import Config
from earlyon_mcp.refresh import build_rows, refresh_once

TZ = ZoneInfo("America/Toronto")


def calendar(events, name="EarlyON Program Calendar2026"):
    return {"name": name, "events": events, "categories": []}


def run(cfg, cal, now, page=""):
    return refresh_once(cfg, now=now, get_token=lambda: "tok", get_calendar=lambda t: cal, get_page=lambda: page)


@pytest.fixture
def cfg(tmp_path):
    return Config(db_path=str(tmp_path / "t.db"))


WEEKLY = make_event(id=10, title="Baby Club.", start="2026-11-02T09:30", end="2026-11-02T11:30",
                    repeat={"type": "Week", "end": "2026-11-30"})


def test_initial_load_then_cancellation_logged_and_past_frozen(cfg):
    d1 = datetime(2026, 11, 3, 8, 0, tzinfo=TZ)
    r = run(cfg, calendar([WEEKLY]), d1)
    assert r["ok"] and r["initial"] == 1 and r["occurrences"] == 4
    with db.connect(cfg.db_path) as conn:
        assert [x["title"] for x in conn.execute("SELECT title FROM occurrences")] == ["Baby Club"] * 4
        assert conn.execute("SELECT COUNT(*) FROM changes").fetchone()[0] == 0  # initial import is not a change

    # Day later: Nov 9 cancelled (excluded), Nov 2 already past. Site edits must not rewrite the past.
    cancelled = copy.deepcopy(WEEKLY)
    cancelled["repeat"]["exclude"] = ["2026-11-02", "2026-11-09"]
    d2 = datetime(2026, 11, 4, 8, 0, tzinfo=TZ)
    r = run(cfg, calendar([cancelled]), d2)
    assert r["ok"] and r["removed"] == 1
    with db.connect(cfg.db_path) as conn:
        dates = [x["start_date"] for x in conn.execute("SELECT start_date FROM occurrences ORDER BY start_date")]
        assert dates == ["2026-11-02", "2026-11-16", "2026-11-23"]  # past Nov 2 survived; Nov 9 gone
        ch = queries.recent_changes(conn, "2026-11-01")
        assert [(c["change"], c["date"]) for c in ch] == [("removed", "2026-11-09")]


def test_modification_detected(cfg):
    run(cfg, calendar([WEEKLY]), datetime(2026, 11, 3, 8, tzinfo=TZ))
    edited = copy.deepcopy(WEEKLY)
    edited["venue"]["name"] = "New Hall"
    edited["venue"]["address"] = "2 Other Rd, Belleville"
    r = run(cfg, calendar([edited]), datetime(2026, 11, 3, 12, tzinfo=TZ))
    assert r["modified"] == 3 and r["added"] == 0  # Nov 2 is past -> frozen, not rewritten


def test_rejects_wrong_calendar_name_and_keeps_data(cfg):
    run(cfg, calendar([WEEKLY]), datetime(2026, 11, 3, 8, tzinfo=TZ))
    r = run(cfg, calendar([WEEKLY], name="Something Else"), datetime(2026, 11, 3, 12, tzinfo=TZ))
    assert not r["ok"] and r["status"] == "rejected"
    with db.connect(cfg.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM occurrences").fetchone()[0] == 4
        assert conn.execute("SELECT status FROM scrapes ORDER BY id DESC LIMIT 1").fetchone()[0] == "rejected"


def test_rejects_empty_and_shrunken_snapshots(cfg):
    big = [make_event(id=i, title=f"P{i}", repeat={"type": "Week", "end": "2027-01-01"}) for i in range(1, 6)]
    r = run(cfg, calendar(big), datetime(2026, 11, 3, 8, tzinfo=TZ))
    assert r["ok"]
    assert run(cfg, calendar([]), datetime(2026, 11, 3, 9, tzinfo=TZ))["status"] == "rejected"
    r = run(cfg, calendar(big[:1]), datetime(2026, 11, 3, 10, tzinfo=TZ))
    assert r["status"] == "rejected" and "shrank" in r["error"]


def test_fetch_error_recorded_not_raised(cfg):
    def boom(_):
        raise RuntimeError("network down")
    r = refresh_once(cfg, now=datetime(2026, 11, 3, 8, tzinfo=TZ), get_token=lambda: "t", get_calendar=boom, get_page=lambda: "")
    assert not r["ok"] and r["status"] == "error"


def test_build_rows_dedupes_and_flags_closures():
    closure = make_event(id=20, title="STAT HOLIDAY", all_day=1, start="2026-12-25", end="2026-12-25",
                         categories=[{"id": 9, "name": "CLOSURES"}], venue={"name": "", "address": "All EarlyON Programs Closed"},
                         repeat={"additionalDates": [{"start": "2026-12-25", "end": "2026-12-25", "allDay": True}]})
    rows = build_rows(calendar([closure]), "America/Toronto")
    assert len(rows) == 1 and rows[0].is_closure and rows[0].all_day and rows[0].venue_address is None
