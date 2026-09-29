"""Direct RSS for the trades, alongside the newsletter inbox.

Newsletters carry little trade dealflow - acquisitions, options,
attachments, greenlights - so Entertainment ran thin without these. The feed
list lives in data/feeds.csv. No checkpoint is needed: a feed only holds its
latest items, and anything already a candidate is dropped at dedup before it
costs a fetch or a model call.
"""
import csv
from calendar import timegm
from datetime import date, datetime, timezone
from pathlib import Path

import feedparser
import httpx
from selectolax.parser import HTMLParser

from .normalize import is_stale

FEEDS = Path(__file__).resolve().parents[3] / "data" / "feeds.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; dhd-digest/0.1; +RSS reader)"}


def load_feeds(path: Path = FEEDS) -> list[dict]:
    return list(csv.DictReader(open(path)))


def _published(entry) -> date | None:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime.fromtimestamp(timegm(t), timezone.utc).date() if t else None


def parse_feed(content: bytes, name: str) -> list[dict]:
    """Feed XML -> raw link dicts in the same shape the newsletter paths return."""
    out = []
    for e in feedparser.parse(content).entries:
        link = e.get("link") or ""
        if not link or is_stale(_published(e)):
            continue
        summary = HTMLParser(e.get("summary") or "").text() or ""
        out.append({
            "raw_url": link,
            "anchor_text": (e.get("title") or "").strip()[:200],
            "context": " ".join(summary.split())[:400],
            "source": name,
            "source_title": name,
        })
    return out


def fetch_links(feeds: list[dict] | None = None) -> list[dict]:
    links = []
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=20.0) as client:
        for feed in feeds or load_feeds():
            try:
                r = client.get(feed["url"])
                r.raise_for_status()
                items = parse_feed(r.content, feed["name"])
            except Exception as exc:          # one dead feed shouldn't stop ingest
                print(f"  feed {feed['name']}: failed ({exc})")
                continue
            print(f"  feed {feed['name']}: {len(items)} items")
            links.extend(items)
    return links


def check():
    """Read-only: fetch every feed and show what it would contribute."""
    for feed in load_feeds():
        items = fetch_links([feed])
        for it in items[:5]:
            print(f"      {it['anchor_text']}")
