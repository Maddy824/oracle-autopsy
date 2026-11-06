import httpx
import pandas as pd
import pytest

from autopsy.news.headlines import HeadlineArchive, HeadlineError, fetch_feed, latest, parse_feed

FEED = b"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>
<item><title><![CDATA[ Old  headline ]]></title><link>https://example.com/old</link>
<pubDate>Fri, 06 Nov 2026 09:00:00 +0530</pubDate></item>
<item><title>New headline</title><link>https://example.com/new</link>
<pubDate>Fri, 06 Nov 2026 14:45:47 +0530</pubDate></item>
<item><title>Undated</title><link>https://example.com/undated</link></item>
<item><title>Not https</title><link>http://example.com/plain</link></item>
<item><title></title><link>https://example.com/empty</link></item>
</channel></rss>"""


def test_parse_keeps_titles_links_and_times():
    items = parse_feed(FEED)
    assert [i["title"] for i in items] == ["Old headline", "New headline", "Undated"]
    assert items[1]["published_at"] == pd.Timestamp("2026-11-06 14:45:47", tz="Asia/Kolkata")
    assert items[2]["published_at"] is None
    assert [i["title"] for i in latest(items, 2)] == ["New headline", "Old headline"]


@pytest.mark.parametrize("content", [
    b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "x">]><rss>&a;</rss>',
    b"<rss><unclosed></rss>", b"x" * 2_000_001,
    '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE r [<!ENTITY a "x">]><rss>&a;</rss>'.encode("utf-16"),
    b'<?xml version="1.0"?><!doctype rss SYSTEM "file:///etc/passwd"><rss/>'])
def test_parse_rejects_dtd_bad_xml_and_huge_feeds(content):
    with pytest.raises(HeadlineError):
        parse_feed(content)


def test_fetch_reports_http_failure():
    with pytest.raises(HeadlineError, match="HTTP 503"):
        fetch_feed(transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    assert len(fetch_feed(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=FEED)))) == 3


def test_archive_keeps_first_sighting_only(tmp_path):
    archive = HeadlineArchive(tmp_path / "h.jsonl")
    items = parse_feed(FEED)
    first = pd.Timestamp("2026-11-06 13:00", tz="UTC")
    assert archive.add(items, seen_at=first) == 3
    changed = [dict(items[0], title="Edited later")]
    assert archive.add(changed, seen_at=first + pd.Timedelta(hours=5)) == 0
    rows = archive.rows()
    assert [r["title"] for r in rows] == ["Old headline", "New headline", "Undated"]
    assert all(r["first_seen_utc"] == first.isoformat() and len(r["checksum"]) == 64 for r in rows)


def test_fetch_stops_reading_past_the_cap():
    big = httpx.Response(200, content=b"<rss>" + b"x" * 2_000_001 + b"</rss>")
    with pytest.raises(HeadlineError, match="too large"):
        fetch_feed(transport=httpx.MockTransport(lambda request: big))
    declared = httpx.Response(200, headers={"content-length": "9999999"}, content=b"<rss/>")
    with pytest.raises(HeadlineError, match="too large"):
        fetch_feed(transport=httpx.MockTransport(lambda request: declared))
