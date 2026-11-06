"""Economic Times markets headlines: context for the owner's brief, archived as first seen.

ET's RSS terms allow personal, non-commercial use with attribution and a
personal-storage exception (docs/research/sources/2026-11-06-codex-factors-and-news.md).
We keep only what the feed supplies (headline, link, stated publication time)
plus our first-seen time, append-only, so a later test cannot use hindsight.
No article pages are fetched; nothing is summarised or scored.
"""

import hashlib
import json
from pathlib import Path
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ElementTree

import httpx
import pandas as pd

ET_MARKETS = "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"
MAX_BYTES = 2_000_000


class HeadlineError(RuntimeError):
    """Feed unavailable or malformed; the brief carries on without news."""


def parse_feed(content, *, source="Economic Times"):
    if not isinstance(content, bytes) or len(content) > MAX_BYTES:
        raise HeadlineError("feed too large or not bytes")
    # Refuse DTDs and entities outright: an RSS feed never needs them.
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise HeadlineError("feed declares a DTD")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        raise HeadlineError("feed is not valid XML") from None
    items = []
    for item in root.iter("item"):
        title = " ".join((item.findtext("title") or "").split())
        link = (item.findtext("link") or "").strip()
        if not title or not link.startswith("https://"):
            continue
        published = None
        try:
            published = pd.Timestamp(parsedate_to_datetime(item.findtext("pubDate") or "")).tz_convert("Asia/Kolkata")
        except (TypeError, ValueError, IndexError):
            pass
        items.append({"source": source, "title": title, "link": link, "published_at": published})
    return items


def fetch_feed(url=ET_MARKETS, *, transport=None):
    try:
        with httpx.Client(transport=transport, timeout=20., follow_redirects=False) as client:
            response = client.get(url, headers={"User-Agent": "oracle-autopsy personal brief"})
    except httpx.HTTPError:
        raise HeadlineError("feed unavailable") from None
    if response.status_code != 200:
        raise HeadlineError(f"feed unavailable (HTTP {response.status_code})")
    return parse_feed(response.content)


class HeadlineArchive:
    """Append-only JSON lines keyed by link; the first sighting is kept forever."""

    def __init__(self, path=None):
        from autopsy.research.trials import data_path
        self.path = Path(path).expanduser() if path is not None else data_path("news/headlines.jsonl")

    def rows(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line]

    def add(self, items, *, seen_at=None):
        seen = pd.Timestamp.now(tz="UTC") if seen_at is None else pd.Timestamp(seen_at).tz_convert("UTC")
        known = {row["link"] for row in self.rows()}
        new = []
        for item in items:
            if item["link"] in known:
                continue
            row = {"source": item["source"], "title": item["title"], "link": item["link"],
                   "published_at": item["published_at"].isoformat() if item["published_at"] is not None else None,
                   "first_seen_utc": seen.isoformat()}
            row["checksum"] = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
            new.append(row)
            known.add(item["link"])
        if new:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                for row in new:
                    stream.write(json.dumps(row, sort_keys=True) + "\n")
        return len(new)


def latest(items, n=3):
    """Newest first by stated publication time; undated items last."""
    floor = pd.Timestamp.min.tz_localize("UTC")
    return sorted(items, key=lambda i: i["published_at"] if i["published_at"] is not None else floor,
                  reverse=True)[:n]
