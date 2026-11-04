from datetime import date

from conftest import make_event
from earlyon_mcp.expand import occurrences


def dates(ev):
    return [o.start_date.isoformat() for o in occurrences(ev)]


def test_single_event():
    assert dates(make_event()) == ["2026-11-02"]


def test_weekly_end_date_is_exclusive():
    ev = make_event(repeat={"type": "Week", "end": "2026-11-16"})
    assert dates(ev) == ["2026-11-02", "2026-11-09"]


def test_weekly_interval_two():
    ev = make_event(repeat={"type": "Week", "end": "2026-12-01", "interval": "2"})
    assert dates(ev) == ["2026-11-02", "2026-11-16", "2026-11-30"]


def test_weekly_exclusions():
    ev = make_event(repeat={"type": "Week", "end": "2026-11-30", "exclude": ["2026-11-09"]})
    assert dates(ev) == ["2026-11-02", "2026-11-16", "2026-11-23"]


def test_weekly_multi_weekday_starts_on_or_after_start():
    # Start Monday Nov 2, run Tue/Wed/Thu: Monday itself is not an occurrence.
    ev = make_event(repeat={"type": "Week", "end": "2026-11-12", "advanced": ["2", "3", "4"]})
    assert sorted(dates(ev)) == ["2026-11-03", "2026-11-04", "2026-11-05", "2026-11-10", "2026-11-11"]


def test_weekly_multi_weekday_includes_start_weekday_when_listed():
    ev = make_event(repeat={"type": "Week", "end": "2026-11-09", "advanced": ["1", "5"]})
    assert sorted(dates(ev)) == ["2026-11-02", "2026-11-06"]


def test_monthly_same_day_skips_short_months():
    ev = make_event(start="2026-01-31T09:00", end="2026-01-31T10:00", repeat={"type": "Month", "end": "2026-06-01", "advanced": "2"})
    assert dates(ev) == ["2026-01-31", "2026-03-31", "2026-05-31"]


def test_monthly_nth_weekday():
    # 2026-11-14 is the 2nd Saturday -> Dec 12, Jan 9
    ev = make_event(start="2026-11-14T09:30", end="2026-11-14T12:00", repeat={"type": "Month", "end": "2027-01-31", "advanced": "1"})
    assert dates(ev) == ["2026-11-14", "2026-12-12", "2027-01-09"]


def test_monthly_last_weekday():
    ev = make_event(start="2026-10-31T09:30", end="2026-10-31T12:00", repeat={"type": "Month", "end": "2027-01-30", "advanced": "3"})
    assert dates(ev) == ["2026-10-31", "2026-11-28", "2026-12-26"]


def test_daily():
    ev = make_event(repeat={"type": "Day", "end": "2026-11-05", "interval": "1"})
    assert dates(ev) == ["2026-11-02", "2026-11-03", "2026-11-04"]


def test_count_based_end():
    ev = make_event(repeat={"type": "Week", "end": "3"})
    assert len(dates(ev)) == 3


def test_additional_dates_added():
    ev = make_event(repeat={"additionalDates": [{"start": "2026-12-24T10:00", "end": "2026-12-24T11:00", "allDay": False}]})
    assert dates(ev) == ["2026-11-02", "2026-12-24"]


def test_all_day_end_is_inclusive_date_without_tz_shift():
    ev = make_event(all_day=1, start="2026-12-25", end="2026-12-27")
    (o,) = occurrences(ev)
    assert o.all_day and o.start_date == date(2026, 12, 25) and o.end_date == date(2026, 12, 27)


def test_timezone_conversion():
    ev = make_event(time_zone="America/Los_Angeles", start="2026-11-02T09:30", end="2026-11-02T10:30")
    (o,) = occurrences(ev, "America/Toronto")
    assert o.start.hour == 12 and o.start.minute == 30


def test_multi_day_timed_event():
    ev = make_event(start="2025-12-24T08:30", end="2026-01-02T16:00")
    (o,) = occurrences(ev)
    assert o.start_date == date(2025, 12, 24) and o.end_date == date(2026, 1, 2)
