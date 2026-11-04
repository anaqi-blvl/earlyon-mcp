from datetime import date

import pytest

from earlyon_mcp.dates import parse_date, week_bounds

TODAY = date(2026, 11, 4)  # a Wednesday


@pytest.mark.parametrize("text,expected", [
    ("today", date(2026, 11, 4)), ("", date(2026, 11, 4)), ("tomorrow", date(2026, 11, 5)),
    ("yesterday", date(2026, 11, 3)), ("2026-12-24", date(2026, 12, 24)), ("in 3 days", date(2026, 11, 7)),
    ("friday", date(2026, 11, 6)), ("wednesday", date(2026, 11, 4)), ("monday", date(2026, 11, 9)),
    ("next monday", date(2026, 11, 9)), ("next friday", date(2026, 11, 13)), ("last friday", date(2026, 10, 30)),
    ("Nov 12", date(2026, 11, 12)), ("november 12 2027", date(2027, 11, 12)), ("12 nov", date(2026, 11, 12)),
    ("Sept 3rd", date(2026, 9, 3)),
])
def test_parse(text, expected):
    assert parse_date(text, TODAY) == expected


@pytest.mark.parametrize("bad", ["someday", "2026-13-45", "feb 30"])
def test_bad(bad):
    with pytest.raises(ValueError):
        parse_date(bad, TODAY)


def test_week_bounds():
    assert week_bounds(TODAY) == (date(2026, 11, 2), date(2026, 11, 8))
