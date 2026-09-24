"""Feedbin ingestion: one API for both RSS feeds and newsletter-to-feed addresses.

Feedbin gives every subscription an email address, so paid newsletters tied to
your real inbox can be forwarded in with a Gmail filter.
"""
import os
import httpx
from selectolax.parser import HTMLParser

BASE = "https://api.feedbin.com/v2"


def _auth():
    return (os.environ["FEEDBIN_USER"], os.environ["FEEDBIN_PASSWORD"])


def fetch_entries(since_id: str | None = None, per_page: int = 100) -> list[dict]:
    """Return entries newer than since_id, oldest first."""
    params = {"per_page": per_page}
    if since_id:
        params["since"] = since_id
    out, page = [], 1
    with httpx.Client(auth=_auth(), timeout=30.0) as c:
        while True:
            r = c.get(f"{BASE}/entries.json", params={**params, "page": page})
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            out.extend(batch)
            if len(batch) < per_page or page >= 20:
                break
            page += 1
    return sorted(out, key=lambda e: e["published"])


def extract_links(entry: dict) -> list[dict]:
    """Pull every anchor out of an entry, with its surrounding sentence."""
    html = entry.get("content") or entry.get("summary") or ""
    tree = HTMLParser(html)
    source = entry.get("feed_id")
    results = []
    for node in tree.css("a[href]"):
        href = node.attributes.get("href") or ""
        anchor = (node.text() or "").strip()
        parent = node.parent
        context = (parent.text() or "").strip()[:400] if parent else anchor
        results.append({
            "raw_url": href,
            "anchor_text": anchor[:200],
            "context": context,
            "source": str(source),
            "source_title": entry.get("feed", {}).get("title") or str(source),
        })
    return results
