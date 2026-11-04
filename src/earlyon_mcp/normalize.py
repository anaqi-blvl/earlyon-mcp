"""Cleaning helpers: titles, HTML descriptions, venues, program types."""
from __future__ import annotations

import re
from collections import Counter
from html.parser import HTMLParser
from typing import Any, Iterable

CLOSURE_TYPE = "Closure"
SPECIAL_TYPE = "Special Event"

_BLOCK = {"p", "div", "br", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "section"}


def clean_title(title: str) -> str:
    """Strip whitespace and the trailing dots the calendar editor appends to dodge duplicate-title checks."""
    t = re.sub(r"\s+", " ", title or "").strip()
    t = re.sub(r"[.\s]+$", "", t)
    return t or (title or "").strip()


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self._href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("\n- ")
        if tag == "a":
            self._href = dict(attrs).get("href") or None
            self._link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK:
            self.parts.append("\n")
        if tag == "a" and self._href:
            text = re.sub(r"\s+", " ", "".join(self._link_text)).strip()
            self.links.append({"text": text, "url": self._href})
            self._href = None

    def handle_data(self, data: str) -> None:
        self.parts.append(data)
        if self._href is not None:
            self._link_text.append(data)


def html_to_text(html: str) -> tuple[str, list[dict[str, str]]]:
    """Convert an HTML description to readable plain text plus its links."""
    if not html:
        return "", []
    ex = _TextExtractor()
    ex.feed(html)
    ex.close()
    text = "".join(ex.parts).replace("\xa0", " ")
    text = "\n".join(line.strip() for line in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    seen: set[str] = set()
    links = []
    for link in ex.links:
        if link["url"] not in seen:
            seen.add(link["url"])
            links.append(link)
    return text, links


def address_from_description(text: str) -> str | None:
    """Pull the address from a '📍 ...' line in the description, if present."""
    for line in text.splitlines():
        if "📍" in line:
            addr = line.replace("📍", "").strip(" |:-​")
            return addr or None
    return None


def program_type(event: dict[str, Any]) -> str:
    cats = event.get("categories") or []
    name = (cats[0].get("name") if cats and isinstance(cats[0], dict) else None) or ""
    name = name.strip()
    if not name:
        return SPECIAL_TYPE
    if name.upper() == "CLOSURES":
        return CLOSURE_TYPE
    return name


def type_matches(query: str | None, type_name: str) -> bool:
    """Case-insensitive substring match: 'morning' matches every morning program type."""
    if not query:
        return True
    return query.strip().lower() in type_name.lower()


_ALIASES = [
    (re.compile(r"south\s+potter'?s?\s+creek", re.I), "South Potters Creek Conservation Area"),
]


def _street_key(address: str) -> str:
    street = address.split(",")[0].lower()
    street = re.sub(r"\bhwy\b", "highway", street)
    street = re.sub(r"\bst\.?$", "st", street)
    return re.sub(r"[^a-z0-9 ]", "", street).strip()


def _tidy_address(address: str) -> str:
    a = re.sub(r"\s+", " ", address or "").strip()
    a = re.sub(r",\s*Canada$", "", a)
    return re.sub(r"\bHwy\b", "Highway", a)


def build_venue_resolver(events: Iterable[dict[str, Any]]):
    """Return ``resolve(event, description_text) -> (name, address)``.

    Venue names are inconsistent in the source ('South Potter's Creek...', empty names, program names used
    as venue names). We pick the most common name per street address and fall back to the 📍 line.
    """
    events = list(events)
    counts: dict[str, Counter] = {}
    for ev in events:
        v = ev.get("venue") or {}
        addr, name = (v.get("address") or "").strip(), (v.get("name") or "").strip()
        if addr and name and "closed" not in addr.lower():
            for pat, canon in _ALIASES:
                if pat.search(name):
                    name = canon
            counts.setdefault(_street_key(addr), Counter())[name] += 1
    by_street = {k: c.most_common(1)[0][0] for k, c in counts.items()}

    def resolve(event: dict[str, Any], description_text: str = "") -> tuple[str | None, str | None]:
        v = event.get("venue") or {}
        addr = (v.get("address") or "").strip()
        name = (v.get("name") or "").strip()
        if "closed" in addr.lower():  # closure notices stuff their message in the address field
            addr = ""
        if not addr:
            addr = address_from_description(description_text) or ""
        for pat, canon in _ALIASES:
            if pat.search(name):
                name = canon
        if addr:
            name = by_street.get(_street_key(addr), name)
        return (name or None), (_tidy_address(addr) or None)

    return resolve
