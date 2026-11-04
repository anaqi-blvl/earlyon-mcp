"""HTTP access to the public calendar endpoints (stdlib only)."""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .config import Config

log = logging.getLogger("earlyon.fetch")


class FetchError(RuntimeError):
    pass


def _get(url: str, cfg: Config, retries: int = 3) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": cfg.user_agent, "Accept": "*/*"})
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=cfg.http_timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                raise FetchError(f"HTTP {e.code} for {url.split('?')[0]}") from e
            last = e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
        time.sleep(2**attempt)
    raise FetchError(f"giving up on {url.split('?')[0]}: {last}")


def fetch_instance_token(cfg: Config) -> str:
    """The site hands every visitor the widget's app-instance token."""
    data = json.loads(_get(f"{cfg.site_url}/_api/v1/access-tokens", cfg))
    try:
        return data["apps"][cfg.boom_app_def_id]["instance"]
    except KeyError as e:
        raise FetchError("calendar app instance token not found (site changed?)") from e


def fetch_calendar(cfg: Config, token: str) -> dict[str, Any]:
    qs = urllib.parse.urlencode({"comp_id": cfg.comp_id, "instance": token})
    raw = _get(f"{cfg.api_base}/published_calendar?{qs}", cfg)
    try:
        cal = json.loads(raw)
    except json.JSONDecodeError as e:
        raise FetchError("calendar API returned non-JSON") from e
    if not isinstance(cal, dict) or not isinstance(cal.get("events"), list):
        raise FetchError("calendar API payload missing 'events'")
    return cal


def fetch_calendar_page(cfg: Config) -> str:
    return _get(f"{cfg.site_url}{cfg.calendar_page}", cfg).decode("utf-8", "replace")


def parse_registrations(html: str, site_url: str, now_iso: str) -> list[dict[str, Any]]:
    """Extract the native (pre-registration) events embedded in the calendar page's server-rendered JSON."""
    marker = '"events":{"events":['
    i = html.find(marker)
    if i < 0:
        return []
    start = html.index("[", i + len('"events":{"events"'))
    try:
        events, _ = json.JSONDecoder().raw_decode(html, start)
    except json.JSONDecodeError:
        return []
    out = []
    for e in events:
        sched = (e.get("scheduling") or {})
        cfg = sched.get("config") or {}
        reg = e.get("registration") or {}
        rsvp = ((reg.get("rsvpCollection") or {}).get("config")) or {}
        loc = e.get("location") or {}
        opens, closes = rsvp.get("startDate"), rsvp.get("endDate")
        if opens and closes:
            state = "upcoming" if now_iso < opens else "open" if now_iso <= closes else "closed"
        else:
            state = "unknown"
        slug = e.get("slug") or ""
        out.append(
            {
                "event_id": e.get("id"),
                "title": (e.get("title") or "").strip(),
                "when": sched.get("formatted"),
                "start": None if cfg.get("scheduleTbd") else cfg.get("startDate"),
                "end": None if cfg.get("scheduleTbd") else cfg.get("endDate"),
                "timezone": cfg.get("timeZoneId"),
                "venue": loc.get("name"),
                "address": loc.get("address"),
                "description": (e.get("description") or "").strip(),
                "registration_state": state,
                "registration_opens": opens,
                "registration_closes": closes,
                "capacity": rsvp.get("limit"),
                "url": f"{site_url}/event-details-registration/{slug}" if slug else None,
            }
        )
    return out
