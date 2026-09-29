"""Direct RSS for the trades, alongside the newsletter inbox.

Newsletters carry little trade dealflow - acquisitions, options,
attachments, greenlights - so Entertainment ran thin without these. The feed
list lives in data/feeds.csv. No checkpoint is needed: a feed only holds its
latest items, and anything already a candidate is dropped at dedup before it
costs a fetch or a model call.

A feed page holds only the newest ~10 items, fewer than a trade's film desk
publishes in a day, so each feed is paged (WordPress `?paged=N`) back until it
reaches items older than PAGE_BACK_DAYS or MAX_PAGES.
"""
import csv
import re
from calendar import timegm
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import feedparser
import httpx
from selectolax.parser import HTMLParser

from .normalize import is_stale

FEEDS = Path(__file__).resolve().parents[3] / "data" / "feeds.csv"
# Trade-feed staples the digest never runs. Dropped on the headline alone, so
# they never cost a page fetch, an embedding or a model call.
SKIP_TITLES = re.compile(
    r"\breview\b|\bphotos?\b|\bgallery\b|how to watch|where to (watch|stream)|"
    r"streaming (guide|this week)|\bquiz\b|\bhoroscope|\bcrossword\b|\brecap\b",
    re.I)
MAX_PAGES = 5
PAGE_BACK_DAYS = 2      # a little over the daily cadence, so a late or skipped run loses nothing
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
        title = (e.get("title") or "").strip()
        if not link or is_stale(_published(e)) or SKIP_TITLES.search(title):
            continue
        summary = HTMLParser(e.get("summary") or "").text() or ""
        out.append({
            "raw_url": link,
            "anchor_text": title[:200],
            "context": " ".join(summary.split())[:400],
            "source": name,
            "source_title": name,
            "published": _published(e),
        })
    return out


def page_url(url: str, page: int) -> str:
    if page == 1:
        return url
    p = urlparse(url)
    q = dict(parse_qsl(p.query))
    q["paged"] = str(page)
    return urlunparse(p._replace(query=urlencode(q)))


def fetch_feed(client: httpx.Client, feed: dict) -> list[dict]:
    cutoff = date.today() - timedelta(days=PAGE_BACK_DAYS)
    items, seen = [], set()
    for page in range(1, MAX_PAGES + 1):
        r = client.get(page_url(feed["url"], page))
        if page > 1 and r.status_code == 404:       # ran off the end of the feed
            break
        r.raise_for_status()
        batch = [it for it in parse_feed(r.content, feed["name"]) if it["raw_url"] not in seen]
        if not batch:                               # empty, or paging unsupported
            break
        seen.update(it["raw_url"] for it in batch)
        items += batch
        dates = [it["published"] for it in batch if it["published"]]
        if not dates or min(dates) < cutoff:
            break
    return items


def fetch_links(feeds: list[dict] | None = None) -> list[dict]:
    links = []
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=20.0) as client:
        for feed in feeds or load_feeds():
            try:
                items = fetch_feed(client, feed)
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
