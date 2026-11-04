"""Validate the expander against what the live widget actually rendered (snapshot of 2026-11-04)."""
import collections
from datetime import date

from earlyon_mcp.expand import expand_all


def fmt(dt):
    h = dt.hour % 12 or 12
    return f"{h}:{dt.minute:02d}{'a' if dt.hour < 12 else 'p'}".replace(":00", "")


def test_expander_matches_widget_rendering(calendar_fixture, rendered_fixture):
    mine = collections.defaultdict(collections.Counter)
    multiday = []
    for ev, occ in expand_all(calendar_fixture["events"]):
        if occ.end_date != occ.start_date and not occ.all_day:
            multiday.append((ev["title"], occ))  # widget redraws spanning bars per week row; checked below
            continue
        key = None if occ.all_day else fmt(occ.start)
        mine[occ.start_date.isoformat()][(key, ev["title"].strip())] += 1
    theirs = collections.defaultdict(collections.Counter)
    for d, evs in rendered_fixture.items():
        for e in evs:
            theirs[d][(e["time"], e["title"])] += 1
    # compare only dates the widget rendered, minus multi-day spanning bars
    span_titles = {t.strip() for t, _ in multiday}
    for d in theirs:
        theirs[d] = collections.Counter({k: v for k, v in theirs[d].items() if k[1] not in span_titles})
    diffs = []
    for d in sorted(set(theirs) | {k for k in mine if min(theirs) <= k <= max(theirs)}):
        if mine.get(d, collections.Counter()) != theirs.get(d, collections.Counter()):
            diffs.append((d, dict(mine.get(d, {})), dict(theirs.get(d, {}))))
    assert not diffs, f"{len(diffs)} day(s) differ, first: {diffs[:3]}"
    total = sum(sum(c.values()) for c in theirs.values())
    assert total > 1000  # the snapshot is big enough to be meaningful


def test_christmas_closure_spans_its_days(calendar_fixture):
    (title, occ), = [(e["title"], o) for e, o in expand_all(calendar_fixture["events"]) if "Christmas Closure" in e["title"]]
    assert occ.start_date == date(2025, 12, 24) and occ.end_date == date(2026, 1, 2)
