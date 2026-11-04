# earlyon-mcp

An [MCP](https://modelcontextprotocol.io) server that exposes the **Family Space Quinte EarlyON** program
calendar (Belleville / Quinte West / Tweed / Madoc / Marmora, Ontario) as tools an AI assistant can call:
"what's on today?", "any evening programs next week?", "when was the last Wildwood at Potters Creek?",
"is everything closed on the 20th?".

> **Unofficial.** Not affiliated with or endorsed by Family Space Quinte. It reads the same public data the
> website's own calendar widget loads, at very low volume (one fetch every few hours by default).
> Please keep it that way.

## What you get

| Tool | Purpose |
|---|---|
| `get_events(date, program_type?)` | One day: time, type, venue, plus closure notices. `date` accepts `today`, `tomorrow`, `friday`, `next monday`, `in 3 days`, `2026-11-12`, `Nov 12` |
| `get_week(week_of, program_type?)` | A Monday-Sunday week grouped by day (`this`, `next`, `last`, or any date in the week) |
| `get_events_range(start, end, ...)` | Any span, past or future |
| `search_events(query, since?, until?, newest_first?)` | Find programs by name / place / topic; works on history |
| `get_event_details(event_id)` | Full description text, links, venue, other upcoming dates |
| `list_program_types()` | Morning Indoor, Afternoon Indoor, Wildwood Outdoor, Evening, Morning Outdoor, Special Event, Closure |
| `get_closures(start?, end?)` | Stat holidays / program closures |
| `get_registrations()` | Pre-registration programs (e.g. Infant Massage, ASQ Connection) and whether registration is open |
| `get_recent_changes(days)` | Programs added / removed (usually cancelled) / edited recently |
| `get_status()` / `refresh_now()` | Data freshness, coverage, forced refresh (rate limited) |

Every response carries `notes` that call out the data horizon (the site only publishes as far ahead as the
organisation has scheduled) and staleness, so "nothing scheduled yet" is never confused with "nothing on".

## How it works

The site's calendar is a Wix widget (Boom Calendar). It loads one JSON document containing **event records
with recurrence rules**, not individual dates. This project:

1. fetches that document (two plain HTTP GETs, no browser, no login),
2. expands the rules into concrete occurrences using a re-implementation of the widget's own recurrence logic
   (weekly multi-weekday series, exclusion dates, nth/last-weekday monthly rules, exclusive end dates,
   multi-day closures; see `src/earlyon_mcp/expand.py`),
3. normalises titles, venues and HTML descriptions,
4. stores them in SQLite and serves read-only MCP tools over stdio.

The expansion is validated by `tests/test_golden.py`, which compares it against a snapshot of what the live
widget actually rendered for 16 months (1,150 events, exact match).

**History is kept.** Occurrences that have ended are frozen and never rewritten, so past schedules survive
later edits on the site. Today-onward occurrences mirror each fresh snapshot, and differences are logged
(that is how cancellations show up in `get_recent_changes`).

**Safety gates.** A refresh is rejected (previous data kept) if the calendar name is unexpected, it is empty,
or the occurrence total shrinks by more than 30%. Failures never wipe data.

## Run it

```bash
pip install .
earlyon-mcp refresh      # one-shot fetch into ./earlyon.db
earlyon-mcp serve        # stdio MCP server (also refreshes in the background every 3h)
earlyon-mcp status
```

Claude Desktop / any stdio client:

```json
{ "mcpServers": { "earlyon": { "command": "earlyon-mcp", "args": ["serve"],
  "env": { "EARLYON_DB_PATH": "/path/to/earlyon.db" } } } }
```

### Docker (streamable HTTP)

The image wraps the stdio server with [`mcp-proxy`](https://github.com/sparfenyuk/mcp-proxy) and serves
`http://<host>:3000/mcp`:

```bash
docker build -t earlyon-mcp .
docker run -d --name earlyon-mcp -p 127.0.0.1:3110:3000 -v earlyon-data:/data earlyon-mcp
```

There is no authentication in the container. Put it behind your own reverse proxy / auth if you expose it.

### Configuration (environment)

| Variable | Default | Meaning |
|---|---|---|
| `EARLYON_DB_PATH` | `earlyon.db` (`/data/earlyon.db` in Docker) | SQLite file |
| `EARLYON_TZ` | `America/Toronto` | Timezone used for "today" and output times |
| `EARLYON_REFRESH_HOURS` | `3` | Background refresh interval |
| `EARLYON_MIN_MANUAL_REFRESH_MIN` | `10` | Minimum gap for `refresh_now` |
| `EARLYON_COMP_ID` | `comp-mg88ldq7` | Widget instance id of the calendar on the page |
| `EARLYON_SITE_URL`, `EARLYON_CALENDAR_PAGE`, `EARLYON_API_BASE`, `EARLYON_BOOM_APP_ID`, `EARLYON_EXPECTED_NAME`, `EARLYON_USER_AGENT`, `EARLYON_HTTP_TIMEOUT` | see `config.py` | Source overrides |

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest                        # offline: unit + golden + tool tests
EARLYON_LIVE=1 pytest tests/test_live.py   # also checks the real site still has the expected shape
```

`tests/fixtures/` holds sanitized snapshots (schedule structure only: no descriptions, contact details or
site/account identifiers); see the README in that folder.

## Limitations

* This depends on an undocumented widget endpoint. If the site changes, refreshes are rejected and
  `get_status` shows why while the last good data keeps being served.
* Descriptions belong to a program series; there is no per-date description.
* The calendar runs only as far as the organisation has published. History starts where the current
  calendar system was adopted (September 2025).
* If the widget's component id changes, set `EARLYON_COMP_ID`.

## License

MIT
