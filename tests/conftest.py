import json
import pathlib

import pytest

FIX = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def calendar_fixture():
    return json.loads((FIX / "calendar_2026-11-04.json").read_text())


@pytest.fixture(scope="session")
def rendered_fixture():
    return json.loads((FIX / "rendered_2026-11-04.json").read_text())


def make_event(**kw):
    base = {
        "id": 1, "title": "Test Program", "start": "2026-11-02T09:30", "end": "2026-11-02T12:00",
        "time_zone": "America/Toronto", "all_day": 0, "desc": "", "image": "[]",
        "venue": {"name": "Hall", "address": "1 Main St, Belleville, ON, Canada", "lat": "", "lng": ""},
        "repeat": {"type": "", "advanced": "", "end": "", "interval": "1", "exclude": [], "additionalDates": []},
        "categories": [{"id": 1, "name": "Morning Indoor Program"}],
    }
    repeat = kw.pop("repeat", None)
    base.update(kw)
    if repeat:
        base["repeat"] = {**base["repeat"], **repeat}
    return base
