"""Expand Boom Calendar event records (recurrence rules) into concrete occurrences.

The semantics below were decoded from the calendar widget's own JavaScript and validated against the
widget's rendered month grids (see tests/test_golden.py):

* ``repeat.type``: ``Day`` | ``Week`` | ``Month`` | ``Year`` | ``""`` (single event).
* ``repeat.interval``: repeat every N units.
* ``repeat.end``: ``YYYY-MM-DD`` (occurrences strictly *before* midnight of that date are kept, so the end
  date itself is exclusive), an integer count, or empty/``never`` (widget defaults apply).
* ``repeat.exclude``: ``YYYY-MM-DD`` dates to skip (matched on the occurrence's local start date).
* ``repeat.additionalDates``: extra one-off ``{start, end, allDay}`` occurrences.
* Weekly ``repeat.advanced``: list of ISO weekdays (Mon=1 .. Sun=7). One record then means "every
  Tue/Wed/Thu"; each weekday forms its own series starting on/after the record's start date.
* Monthly ``repeat.advanced``: ``"1"`` = nth weekday of the month (n taken from the start date),
  ``"2"``/empty = same day-of-month (months lacking that day are skipped), ``"3"`` = last such weekday.
* All-day events carry date-only strings; their ``end`` date is inclusive.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Iterable
from zoneinfo import ZoneInfo

_TS_FMT = "%Y-%m-%dT%H:%M"
HARD_CAP = 5000
_UNBOUNDED_COUNTS = {"Day": 720, "Week": 104, "Month": 24, "Year": 10}
_TYPE_ALIASES = {"Weekly": "Week", "Weekl": "Week", "Daily": "Day", "Monthly": "Month", "Yearly": "Year"}


@dataclass(frozen=True)
class Occurrence:
    """One concrete occurrence in the target timezone.

    For all-day events ``start``/``end`` are midnight datetimes and ``end`` is the *inclusive* last day.
    """

    start: datetime
    end: datetime
    all_day: bool

    @property
    def start_date(self) -> date:
        return self.start.date()

    @property
    def end_date(self) -> date:
        return self.end.date()


def _parse(s: str) -> datetime:
    s = s.strip()
    if len(s) <= 10:
        return datetime.strptime(s[:10], "%Y-%m-%d")
    return datetime.strptime(s[:16].replace(" ", "T"), _TS_FMT)


def _nth_weekday(year: int, month: int, isoweekday: int, n: int) -> date:
    d = date(year, month, 1)
    while d.isoweekday() != isoweekday:
        d += timedelta(days=1)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, isoweekday: int) -> date:
    d = date(year, month, calendar.monthrange(year, month)[1])
    while d.isoweekday() != isoweekday:
        d -= timedelta(days=1)
    return d


def _add_months(year: int, month: int, k: int) -> tuple[int, int]:
    y, m = divmod(month - 1 + k, 12)
    return year + y, m + 1


def _limits(repeat: dict[str, Any], typ: str) -> tuple[datetime | None, int | None]:
    rend = (repeat.get("end") or "").strip()
    if rend and rend != "never":
        if rend.isdigit():
            return None, int(rend)
        return _parse(rend[:10] + "T00:00" if len(rend) == 10 else rend), None
    return None, _UNBOUNDED_COUNTS[typ]


def _series_local(event: dict[str, Any]) -> list[tuple[datetime, datetime]]:
    """Occurrences as naive datetimes in the event's own timezone."""
    repeat = event.get("repeat") or {}
    typ = _TYPE_ALIASES.get(repeat.get("type") or "", repeat.get("type") or "")
    start, end = _parse(event["start"]), _parse(event["end"])
    dur = end - start
    out: list[tuple[datetime, datetime]] = []

    if typ not in ("Day", "Week", "Month", "Year"):
        out.append((start, end))
    else:
        interval = max(int(repeat.get("interval") or 1), 1)
        adv = repeat.get("advanced")
        adv = adv if adv is not None else ""
        excl = set(repeat.get("exclude") or [])
        limit_dt, limit_n = _limits(repeat, typ)

        def room(cur: datetime, produced: int, i: int) -> bool:
            return (limit_dt is None or cur < limit_dt) and (limit_n is None or produced < limit_n) and i < HARD_CAP

        if typ == "Week" and isinstance(adv, list) and adv:
            produced = 0
            for wd in sorted({int(x) for x in adv}):
                cur = start + timedelta(days=wd - start.isoweekday())
                if cur.date() < start.date():
                    cur += timedelta(weeks=1)
                i = 0
                while room(cur, produced, i):
                    if cur.strftime("%Y-%m-%d") not in excl:
                        out.append((cur, cur + dur))
                        produced += 1
                    cur += timedelta(weeks=interval)
                    i += 1
        else:
            cur, produced, i = start, 0, 0
            while room(cur, produced, i):
                if cur.strftime("%Y-%m-%d") not in excl:
                    out.append((cur, cur + dur))
                    produced += 1
                if typ == "Day":
                    cur += timedelta(days=interval)
                elif typ == "Week":
                    cur += timedelta(weeks=interval)
                elif typ == "Month":
                    cur = _next_month(cur, start, interval, str(adv))
                else:  # Year
                    try:
                        cur = cur.replace(year=cur.year + interval)
                    except ValueError:  # Feb 29
                        cur = cur.replace(year=cur.year + interval, day=28)
                i += 1

    for extra in repeat.get("additionalDates") or []:
        out.append((_parse(extra["start"]), _parse(extra["end"])))
    return out


def _next_month(cur: datetime, start: datetime, interval: int, adv: str) -> datetime:
    if adv == "1":  # nth weekday of the month
        nth = -(-start.day // 7)
        y, m = _add_months(cur.year, cur.month, interval)
        return datetime.combine(_nth_weekday(y, m, start.isoweekday(), nth), start.time())
    if adv not in ("2", ""):  # "3": last matching weekday
        y, m = _add_months(cur.year, cur.month, interval)
        return datetime.combine(_last_weekday(y, m, start.isoweekday()), start.time())
    k = 1  # same day-of-month, skipping months that lack the day
    while True:
        y, m = _add_months(cur.year, cur.month, k * interval)
        if start.day <= calendar.monthrange(y, m)[1]:
            return datetime(y, m, start.day, start.hour, start.minute)
        k += 1


def occurrences(event: dict[str, Any], tz: str = "America/Toronto") -> list[Occurrence]:
    """All occurrences of one event record, converted to ``tz`` (naive local datetimes returned)."""
    target = ZoneInfo(tz)
    src = ZoneInfo(event.get("time_zone") or tz)
    all_day = bool(event.get("all_day"))
    res: list[Occurrence] = []
    for s, e in _series_local(event):
        if all_day:
            res.append(Occurrence(datetime.combine(s.date(), time()), datetime.combine(e.date(), time()), True))
            continue
        s2 = s.replace(tzinfo=src).astimezone(target).replace(tzinfo=None)
        e2 = e.replace(tzinfo=src).astimezone(target).replace(tzinfo=None)
        res.append(Occurrence(s2, e2, False))
    return res


def expand_all(events: Iterable[dict[str, Any]], tz: str = "America/Toronto") -> list[tuple[dict[str, Any], Occurrence]]:
    """Expand every event record; returns ``(event, occurrence)`` pairs sorted by start."""
    pairs = [(ev, occ) for ev in events for occ in occurrences(ev, tz)]
    pairs.sort(key=lambda p: (p[1].start, p[0].get("title", "")))
    return pairs
