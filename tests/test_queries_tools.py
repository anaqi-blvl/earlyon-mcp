import copy
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from conftest import make_event
from earlyon_mcp import db, queries, server
from earlyon_mcp.config import Config
from earlyon_mcp.refresh import refresh_once

TZ = ZoneInfo("America/Toronto")
NOW = datetime(2026, 11, 4, 9, 0, tzinfo=TZ)


def build_calendar():
    evs = [
        make_event(id=1, title="Park Dale EarlyON", start="2026-11-04T09:30", end="2026-11-04T13:00",
                   desc="<p>Fun for all</p><p>\U0001F4CD 73 Poplar St</p>", repeat={"type": "Week", "end": "2026-12-01"}),
        make_event(id=2, title="Evening Fun.", start="2026-11-05T16:30", end="2026-11-05T19:00",
                   categories=[{"id": 2, "name": "Evening Program"}], repeat={"type": "Week", "end": "2026-12-01"}),
        make_event(id=3, title="STAT HOLIDAY", all_day=1, start="2026-11-10", end="2026-11-10",
                   categories=[{"id": 3, "name": "CLOSURES"}], venue={"name": "", "address": ""}),
        make_event(id=4, title="Christmas Closure", start="2026-11-24T08:30", end="2026-11-26T16:00",
                   categories=[{"id": 3, "name": "CLOSURES"}], venue={"name": "", "address": ""}),
    ]
    return {"name": "EarlyON Program Calendar2026", "events": evs}


@pytest.fixture
def loaded(tmp_path, monkeypatch):
    cfg = Config(db_path=str(tmp_path / "t.db"))
    cal = build_calendar()
    page = ('<html>x "events":{"events":[{"id":"abc","title":"ASQ Connection","slug":"asq-1","description":"Free session",'
            '"scheduling":{"formatted":"November 30, 2026, 1:15 p.m.","config":{"scheduleTbd":false,"startDate":"2026-11-30T18:15:00.000Z",'
            '"endDate":"2026-11-30T19:15:00.000Z","timeZoneId":"America/Toronto"}},'
            '"registration":{"rsvpCollection":{"config":{"startDate":"2026-10-26T13:00:00.000Z","endDate":"2026-11-23T14:00:00.000Z","limit":2}}},'
            '"location":{"name":"A School","address":"1 St"}}],"x":1}</html>')
    r = refresh_once(cfg, now=NOW, get_token=lambda: "t", get_calendar=lambda t: cal, get_page=lambda: page)
    assert r["ok"] and r["registrations"] == 1
    monkeypatch.setattr(server, "cfg", cfg)
    monkeypatch.setattr(server, "_today", lambda: date(2026, 11, 4))
    monkeypatch.setattr(server, "_now", lambda: NOW)
    return cfg


def test_get_events_today_and_closure_summary(loaded):
    res = server.get_events("today")
    assert res["count"] == 1 and res["events"][0]["title"] == "Park Dale EarlyON"
    assert res["events"][0]["start"] == "9:30 AM" and res["events"][0]["end"] == "1:00 PM"
    res = server.get_events("2026-11-10")
    assert res["count"] == 0 and "CLOSURE NOTICE" in res["summary"] and res["closures"][0]["all_day"]


def test_multi_day_closure_overlaps_every_day(loaded):
    for d in ("2026-11-24", "2026-11-25", "2026-11-26"):
        assert [c["title"] for c in server.get_events(d)["closures"]] == ["Christmas Closure"]
    assert server.get_events("2026-11-27")["closures"] == []


def test_type_filter_and_week(loaded):
    wk = server.get_week("this")
    assert wk["week_start"] == "2026-11-02" and len(wk["days"]) == 7
    assert wk["count"] == 2 and [d["events"][0]["title"] for d in wk["days"] if d["events"]] == ["Park Dale EarlyON", "Evening Fun"]
    assert server.get_events("2026-11-05", program_type="evening")["count"] == 1
    assert server.get_events("2026-11-05", program_type="morning")["count"] == 0


def test_range_search_details(loaded):
    rng = server.get_events_range("2026-11-01", "2026-11-30")
    assert rng["count"] == 8 and len(rng["closures"]) == 2
    hits = server.search_events("park dale", newest_first=True, limit=2)
    assert [h["date"] for h in hits["events"]] == ["2026-11-25", "2026-11-18"]
    d = server.get_event_details("1")  # bare series id -> next occurrence
    assert d["date"] == "2026-11-04" and "Fun for all" in d["description"] and d["address"] == "1 Main St, Belleville, ON"
    assert len(d["other_upcoming_dates"]) == 3
    with pytest.raises(ValueError):
        server.get_event_details("nope")


def test_horizon_note_and_bad_date(loaded):
    res = server.get_events("2027-03-01")
    assert res["count"] == 0 and any("only runs through" in n for n in res["notes"])
    with pytest.raises(ValueError):
        server.get_events("whenever")


def test_registrations_types_status_changes(loaded):
    regs = server.get_registrations()["registrations"]
    assert regs[0]["title"] == "ASQ Connection" and regs[0]["registration_state"] == "open" and regs[0]["capacity"] == 2
    types = {t["type"] for t in server.list_program_types()["types"]}
    assert {"Morning Indoor Program", "Evening Program", "Closure"} <= types
    assert server.get_status()["coverage"]["total_occurrences"] > 0
    assert server.get_recent_changes(7)["count"] == 0


def test_refresh_now_is_rate_limited(loaded):
    assert server.refresh_now()["skipped"] is True
