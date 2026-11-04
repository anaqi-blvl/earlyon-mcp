"""Hits the real website. Run with: EARLYON_LIVE=1 pytest tests/test_live.py"""
import os

import pytest

from earlyon_mcp import fetch
from earlyon_mcp.config import Config
from earlyon_mcp.refresh import build_rows

pytestmark = pytest.mark.skipif(not os.environ.get("EARLYON_LIVE"), reason="set EARLYON_LIVE=1 to hit the real site")


def test_live_calendar_shape():
    cfg = Config.from_env()
    cal = fetch.fetch_calendar(cfg, fetch.fetch_instance_token(cfg))
    assert cal["name"].startswith(cfg.expected_name_prefix)
    rows = build_rows(cal, cfg.timezone)
    assert len(rows) > 100
