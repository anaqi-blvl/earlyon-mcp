"""Forgiving date parsing for tool arguments (all relative to the configured timezone)."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"])}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})
_MONTHS["sept"] = 9

HELP = (
    "Use 'today', 'tomorrow', 'yesterday', an ISO date (2026-11-12), a weekday ('friday' = next one on/after "
    "today, 'next friday' = that weekday next week, 'last friday'), 'in 3 days', or 'Nov 12' / 'November 12 2026'."
)


def today_in(tz: str) -> date:
    return datetime.now(ZoneInfo(tz)).date()


def week_bounds(d: date) -> tuple[date, date]:
    mon = d - timedelta(days=d.weekday())
    return mon, mon + timedelta(days=6)


def parse_date(text: str | None, today: date) -> date:
    s = (text or "today").strip().lower()
    if s in ("", "today", "now"):
        return today
    if s == "tomorrow":
        return today + timedelta(days=1)
    if s == "yesterday":
        return today - timedelta(days=1)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        try:
            return date.fromisoformat(s)
        except ValueError as e:
            raise ValueError(f"Invalid date {text!r}. {HELP}") from e
    m = re.fullmatch(r"in (\d{1,3}) days?", s)
    if m:
        return today + timedelta(days=int(m.group(1)))
    m = re.fullmatch(r"(?:(next|last|this)\s+)?(" + "|".join(_WEEKDAYS) + ")", s)
    if m:
        mod, wd = m.group(1), _WEEKDAYS.index(m.group(2))
        if mod == "next":
            return week_bounds(today)[0] + timedelta(days=7 + wd)
        if mod == "last":
            back = (today.weekday() - wd) % 7 or 7
            return today - timedelta(days=back)
        return today + timedelta(days=(wd - today.weekday()) % 7)
    m = re.fullmatch(r"([a-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?", s) or re.fullmatch(
        r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\.?(?:,?\s+(\d{4}))?", s)
    if m:
        a, b, year = m.groups()
        mon_name, day = (a, b) if a.isalpha() else (b, a)
        if mon_name in _MONTHS:
            try:
                return date(int(year) if year else today.year, _MONTHS[mon_name], int(day))
            except ValueError as e:
                raise ValueError(f"Invalid date {text!r}. {HELP}") from e
    raise ValueError(f"Couldn't understand date {text!r}. {HELP}")
