"""Daily ingestion: fetch, canonicalize, dedup, store."""
import os
from collections import defaultdict

import httpx
from selectolax.parser import HTMLParser

from ..db.client import conn, query
from . import feedbin, imap
from .normalize import canonicalize, domain_of, unwrap

RESOLVE_REDIRECTS = os.environ.get("RESOLVE_REDIRECTS", "true").lower() == "true"


def _state(key: str) -> str | None:
    rows = query("SELECT last_id FROM fetch_state WHERE source_key=%s", (key,))
    return rows[0][0] if rows else None


def _save_state(key: str, last_id: str):
    with conn().cursor() as cur:
        cur.execute(
            """INSERT INTO fetch_state (source_key, last_id, last_run)
               VALUES (%s,%s,now()) ON CONFLICT (source_key)
               DO UPDATE SET last_id=EXCLUDED.last_id, last_run=now()""",
            (key, str(last_id)))


def collect() -> list[dict]:
    """Return raw link dicts from whichever backend is configured."""
    if os.environ.get("FEEDBIN_USER"):
        since = _state("feedbin")
        entries = feedbin.fetch_entries(since_id=since)
        links = [l for e in entries for l in feedbin.extract_links(e)]
        if entries:
            _save_state("feedbin", entries[-1]["id"])
        return links

    since = int(_state("imap") or 0)
    msgs = imap.fetch_messages(since_uid=since)
    links = [l for m in msgs for l in imap.extract_links(m)]
    if msgs:
        _save_state("imap", max(m["uid"] for m in msgs))
    return links


def enrich(canonical_url: str, client: httpx.Client) -> tuple[str, str]:
    """Fetch headline and opening text. Failure is fine - triage handles blanks."""
    try:
        r = client.get(canonical_url, timeout=8.0)
        tree = HTMLParser(r.text)
        title = ""
        for sel, attr in [('meta[property="og:title"]', "content"),
                          ("title", None), ("h1", None)]:
            node = tree.css_first(sel)
            if node:
                title = (node.attributes.get(attr, "") if attr else node.text()) or ""
                if title.strip():
                    break
        desc = ""
        for sel in ['meta[property="og:description"]', 'meta[name="description"]']:
            node = tree.css_first(sel)
            if node and node.attributes.get("content"):
                desc = node.attributes["content"]
                break
        if not desc:
            p = tree.css_first("article p") or tree.css_first("p")
            desc = (p.text() if p else "")[:500]
        return title.strip()[:300], desc.strip()[:800]
    except Exception:
        return "", ""


def run():
    raw = collect()
    print(f"fetched {len(raw)} raw anchors")

    merged: dict[str, dict] = {}
    sources = defaultdict(set)
    with httpx.Client(follow_redirects=True, timeout=8.0) as client:
        for item in raw:
            url = unwrap(item["raw_url"], client) if RESOLVE_REDIRECTS else item["raw_url"]
            cu = canonicalize(url)
            if not cu:
                continue
            sources[cu].add(item.get("source_title") or item.get("source") or "unknown")
            if cu not in merged:
                merged[cu] = {"canonical_url": cu, "raw_url": url,
                              "domain": domain_of(cu),
                              "anchor_text": item["anchor_text"],
                              "context": item["context"]}
        print(f"{len(merged)} distinct canonical urls")

        # Drop anything already published, or already a candidate.
        keys = list(merged)
        known = {r[0] for r in query(
            "SELECT canonical_url FROM seen_urls WHERE canonical_url = ANY(%s)", (keys,))}
        known |= {r[0] for r in query(
            "SELECT canonical_url FROM candidates WHERE canonical_url = ANY(%s)", (keys,))}
        fresh = [v for k, v in merged.items() if k not in known]
        print(f"{len(fresh)} new after dedup ({len(known)} already seen)")

        with conn().cursor() as cur:
            for row in fresh:
                headline, excerpt = enrich(row["canonical_url"], client)
                cur.execute(
                    """INSERT INTO candidates
                       (canonical_url, raw_url, domain, anchor_text, context,
                        headline, excerpt, sources)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (canonical_url) DO NOTHING""",
                    (row["canonical_url"], row["raw_url"], row["domain"],
                     row["anchor_text"], row["context"], headline, excerpt,
                     sorted(sources[row["canonical_url"]])))
    print("ingest complete")
