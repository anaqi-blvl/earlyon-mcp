"""Runtime configuration (all overridable via environment variables)."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    site_url: str = "https://www.familyspacequinte.com"
    calendar_page: str = "/earlyon-calendar"
    # Wix app-definition id of the Boom Calendar widget embedded on the site.
    boom_app_def_id: str = "13b4a028-00fa-7133-242f-4628106b8c91"
    # Widget instance (component) id of the desktop month-grid calendar.
    comp_id: str = "comp-mg88ldq7"
    api_base: str = "https://calendar.apiboomtech.com/api"
    # Sanity gate: the calendar's display name must start with this, otherwise we refuse the snapshot.
    expected_name_prefix: str = "EarlyON Program Calendar"
    db_path: str = "earlyon.db"
    timezone: str = "America/Toronto"
    refresh_hours: float = 3.0
    min_manual_refresh_minutes: float = 10.0
    user_agent: str = "earlyon-mcp/0.1 (personal calendar mirror; low volume)"
    http_timeout: float = 30.0

    @classmethod
    def from_env(cls) -> "Config":
        d = cls()

        def s(name: str, default: str) -> str:
            return os.environ.get(name) or default

        def f(name: str, default: float) -> float:
            v = os.environ.get(name)
            return float(v) if v else default

        return cls(
            site_url=s("EARLYON_SITE_URL", d.site_url).rstrip("/"),
            calendar_page=s("EARLYON_CALENDAR_PAGE", d.calendar_page),
            boom_app_def_id=s("EARLYON_BOOM_APP_ID", d.boom_app_def_id),
            comp_id=s("EARLYON_COMP_ID", d.comp_id),
            api_base=s("EARLYON_API_BASE", d.api_base).rstrip("/"),
            expected_name_prefix=s("EARLYON_EXPECTED_NAME", d.expected_name_prefix),
            db_path=s("EARLYON_DB_PATH", d.db_path),
            timezone=s("EARLYON_TZ", d.timezone),
            refresh_hours=f("EARLYON_REFRESH_HOURS", d.refresh_hours),
            min_manual_refresh_minutes=f("EARLYON_MIN_MANUAL_REFRESH_MIN", d.min_manual_refresh_minutes),
            user_agent=s("EARLYON_USER_AGENT", d.user_agent),
            http_timeout=f("EARLYON_HTTP_TIMEOUT", d.http_timeout),
        )
