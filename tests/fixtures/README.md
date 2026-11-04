# Fixtures

* `calendar_2026-11-04.json` - the calendar API payload captured 2026-11-04, **sanitized**: descriptions, images,
  organizer/contact fields and all site/account identifiers removed. Keeps titles, times, recurrence rules,
  categories and public venue names/addresses.
* `rendered_2026-11-04.json` - what the live month-grid widget displayed for Sep 2025 - Dec 2026 on the same day
  (per date: displayed time + title). Used as ground truth by `tests/test_golden.py`.

Dates in tests are explicit, so these files never need refreshing unless the recurrence rules change.
