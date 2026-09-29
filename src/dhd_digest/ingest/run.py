"""Daily ingestion: fetch, canonicalize, dedup, store."""
import os
from collections import defaultdict
from datetime import date, datetime

import httpx
from selectolax.parser import HTMLParser

from ..config import MAX_ARTICLE_AGE_DAYS
from ..db.client import conn, query
from . import feedbin, imap, rss
from .normalize import (canonicalize, domain_of, is_stale, is_tracker_url,
                        unwrap, url_date)

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


def _imap_folder(folder: str, key: str, picks_only: bool) -> tuple[list[dict], int | None]:
    msgs = imap.fetch_messages(since_uid=int(_state(key) or 0), folder=folder)
    links = []
    for m in msgs:
        pinned = imap.pick_links(m) if imap.is_pick(m) else []
        if pinned:
            links += pinned
        elif not picks_only:
            links += imap.extract_links(m)
    return links, max((m["uid"] for m in msgs), default=None)


def collect() -> tuple[list[dict], list[tuple[str, str | int]]]:
    """Return raw link dicts from whichever backend is configured, plus the
    checkpoints to save once those links are durably written to candidates.

    Fetching never advances fetch_state itself - if the run dies before the
    candidates land, the next run must see the same messages again rather
    than silently skipping them.

    On IMAP, links the editor forwards in come back pinned (see imap.is_pick).
    Forwards usually land in the inbox rather than the newsletter folder, so
    IMAP_PICKS_FOLDER (default INBOX) is read too, for picks only.
    """
    if os.environ.get("FEEDBIN_USER"):
        since = _state("feedbin")
        entries = feedbin.fetch_entries(since_id=since)
        links = [l for e in entries for l in feedbin.extract_links(e)]
        return links, ([("feedbin", entries[-1]["id"])] if entries else [])

    main = os.environ.get("IMAP_FOLDER") or "Newsletters"
    picks = os.environ.get("IMAP_PICKS_FOLDER") or "INBOX"
    links, checkpoints = [], []
    for folder, key, picks_only in [(main, "imap", False)] + (
            [(picks, f"imap:{picks}", True)] if picks != main else []):
        found, uid = _imap_folder(folder, key, picks_only)
        links += found
        if uid is not None:
            checkpoints.append((key, uid))
    return links, checkpoints


def published_date(tree: HTMLParser) -> date | None:
    for sel in ('meta[property="article:published_time"]',
                'meta[name="article:published_time"]', 'meta[itemprop="datePublished"]'):
        node = tree.css_first(sel)
        value = node.attributes.get("content") if node else None
        if value:
            try:
                return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()
            except ValueError:
                continue
    return None


def enrich(canonical_url: str, client: httpx.Client) -> tuple[str, str, date | None]:
    """Fetch headline, opening text and publish date. Failure is fine -
    triage handles blanks, and an unknown date counts as fresh."""
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
        return title.strip()[:300], desc.strip()[:800], published_date(tree)
    except Exception:
        return "", "", None


def run():
    raw, checkpoints = collect()
    picks = sum(1 for r in raw if r.get("pinned"))
    print(f"fetched {len(raw)} raw anchors from newsletters, {picks} of them editor picks")
    raw += rss.fetch_links()
    print(f"{len(raw)} with trade RSS feeds")

    merged: dict[str, dict] = {}
    sources = defaultdict(set)
    enriched: list[tuple[dict, str, str]] = []
    with httpx.Client(follow_redirects=True, timeout=8.0) as client:
        for item in raw:
            pinned = bool(item.get("pinned"))
            url = unwrap(item["raw_url"], client) if RESOLVE_REDIRECTS else item["raw_url"]
            # Never publish a tracker or a stale link - unless the editor
            # forwarded it: their picks are always kept, and they'll see it.
            if is_tracker_url(url) and not pinned:
                continue
            cu = canonicalize(url)
            if not cu or (is_stale(url_date(cu)) and not pinned):
                continue
            sources[cu].add(item.get("source_title") or item.get("source") or "unknown")
            if cu not in merged:
                merged[cu] = {"canonical_url": cu, "raw_url": url,
                              "domain": domain_of(cu),
                              "anchor_text": item["anchor_text"],
                              "context": item["context"], "pinned": pinned}
            elif pinned:
                merged[cu]["pinned"] = True
        print(f"{len(merged)} distinct canonical urls")

        # Drop anything already published, or already a candidate. A pick that
        # is already a candidate gets pinned in place (below) instead.
        keys = list(merged)
        already_published = {r[0] for r in query(
            "SELECT canonical_url FROM seen_urls WHERE canonical_url = ANY(%s)", (keys,))}
        existing = {r[0] for r in query(
            "SELECT canonical_url FROM candidates WHERE canonical_url = ANY(%s)", (keys,))}
        known = already_published | existing
        fresh = [v for k, v in merged.items() if k not in known]
        print(f"{len(fresh)} new after dedup ({len(known)} already seen)")
        repin = [k for k, v in merged.items() if v["pinned"] and k in existing - already_published]
        for k, v in merged.items():
            if v["pinned"] and k in already_published:
                print(f"  pick already published in an earlier issue, skipped: {k}")

        stale = 0
        for row in fresh:
            headline, excerpt, published = enrich(row["canonical_url"], client)
            if is_stale(published) and not row["pinned"]:
                stale += 1
                continue
            # Trade sites often block the page fetch; the feed's own title and
            # summary are a good stand-in.
            enriched.append((row, headline or row["anchor_text"],
                             excerpt or row["context"]))
        print(f"{stale} dropped as older than {MAX_ARTICLE_AGE_DAYS} days")

    # Everything from here is one transaction: candidates land and the
    # checkpoint advances together, or neither does. A crash mid-loop must
    # not advance past messages whose links never made it into the table.
    with conn().transaction():
        with conn().cursor() as cur:
            for row, headline, excerpt in enriched:
                cur.execute(
                    """INSERT INTO candidates
                       (canonical_url, raw_url, domain, anchor_text, context,
                        headline, excerpt, sources, pinned)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (canonical_url) DO UPDATE
                       SET sources = (
                           SELECT ARRAY(
                               SELECT DISTINCT unnest(
                                   candidates.sources || EXCLUDED.sources))
                       ),
                       pinned = candidates.pinned OR EXCLUDED.pinned""",
                    (row["canonical_url"], row["raw_url"], row["domain"],
                     row["anchor_text"], row["context"], headline, excerpt,
                     sorted(sources[row["canonical_url"]]), row["pinned"]))
            if repin:
                cur.execute(
                    "UPDATE candidates SET pinned = TRUE WHERE canonical_url = ANY(%s)",
                    (repin,))
        for key, value in checkpoints:
            _save_state(key, value)
        print(f"{len(repin) + sum(1 for r, *_ in enriched if r['pinned'])} editor picks pinned")
    print("ingest complete")
