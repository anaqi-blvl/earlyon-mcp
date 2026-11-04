from earlyon_mcp.normalize import (address_from_description, build_venue_resolver, clean_title, html_to_text,
                                   program_type, type_matches)


def test_clean_title_strips_dup_dots():
    assert clean_title("Daddy N Me..") == "Daddy N Me"
    assert clean_title("  St. Joseph EarlyON Program. ") == "St. Joseph EarlyON Program"
    assert clean_title("St. Joseph") == "St. Joseph"


def test_html_to_text_and_links():
    html = ("<p><strong>Tales on the Trails</strong></p><p>\U0001F4CD <strong>2061 Old Hwy 2, Belleville</strong></p></br>"
            "<ul><li>one</li><li>two&nbsp;x</li></ul>"
            '<p>Watch <a href="https://example.org/v">the video</a> now &amp; later</p>')
    text, links = html_to_text(html)
    assert "Tales on the Trails" in text and "- one" in text and "- two x" in text
    assert "&amp;" not in text and "now & later" in text
    assert links == [{"text": "the video", "url": "https://example.org/v"}]
    assert "\n\n\n" not in text


def test_address_from_description():
    assert address_from_description("hello\n\U0001F4CD 2056 Old Hwy 2, Belleville\nbye") == "2056 Old Hwy 2, Belleville"
    assert address_from_description("nothing") is None


def test_program_type():
    assert program_type({"categories": []}) == "Special Event"
    assert program_type({"categories": [{"name": "CLOSURES"}]}) == "Closure"
    assert program_type({"categories": [{"name": "Evening Program"}]}) == "Evening Program"


def test_type_matches_substring():
    assert type_matches("morning", "Morning Outdoor") and type_matches("MORNING", "Morning Indoor Program")
    assert not type_matches("evening", "Morning Indoor Program") and type_matches(None, "x")


def test_venue_resolver_canonicalizes_by_street_and_falls_back_to_description():
    ev = lambda n, a: {"venue": {"name": n, "address": a}}  # noqa: E731
    events = [ev("St. Joseph Catholic School", "405 Bridge St E, Belleville, ON K8N 1P7, Canada")] * 3 + [
        ev("St. Joseph EarlyON Program", "405 Bridge St E, Belleville, ON K8N 1P7, Canada"),
        ev("South Potter's Creek Conservation Area", "2056 Old Highway 2, Belleville, ON K8N 4Z2, Canada"),
        ev("South Potters Creek Conservation Area", "2056 Old Hwy 2, Belleville"),
    ]
    resolve = build_venue_resolver(events)
    assert resolve(events[3])[0] == "St. Joseph Catholic School"
    assert resolve(events[4])[0] == "South Potters Creek Conservation Area"
    assert resolve(events[5])[1] == "2056 Old Highway 2, Belleville"
    name, addr = resolve({"venue": {"name": "", "address": ""}}, "x\n\U0001F4CD 405 Bridge St E, Belleville\n")
    assert addr == "405 Bridge St E, Belleville" and name == "St. Joseph Catholic School"
    assert resolve({"venue": {"name": "", "address": "All EarlyON Programs & Office Location Closed"}}) == (None, None)
