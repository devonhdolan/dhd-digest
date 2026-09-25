"""Weekly assembly: pick, edit per section, enforce the historical mix, render."""
import math
from datetime import date
from pathlib import Path

import anthropic

from ..config import (ANTHROPIC_API_KEY, EDITOR_MODEL, MIN_KEEP_SCORE,
                      SECTION_MIX, SECTIONS, TARGET_LINKS_PER_ISSUE)
from ..corpus.search import style_examples
from ..db.client import conn, query
from ..render.markdown import parse_published
from ..validation import validate_section_selection
from .prompts import SECTION_TOOL, SYSTEM, build_user_message

_client = None


def client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def quotas(total: int = TARGET_LINKS_PER_ISSUE) -> dict[str, int]:
    """Hold the mix the archive held for five years: 37/22/21/20.

    Largest-remainder allocation: floor each section's exact share, then
    hand the leftover slots (total minus the sum of floors) to whichever
    sections had the biggest fractional remainder. Plain floor()-per-section
    almost always under-allocates by a few links; this guarantees the
    result sums to exactly `total`.
    """
    exact = {s: total * SECTION_MIX[s] for s in SECTIONS}
    result = {s: math.floor(n) for s, n in exact.items()}

    remainder = total - sum(result.values())
    for section in sorted(SECTIONS, key=lambda s: exact[s] - result[s],
                           reverse=True)[:remainder]:
        result[section] += 1

    return result


def pool(section: str, limit: int) -> list[dict]:
    rows = query(
        """SELECT id, blurb, domain, keep_score, canonical_url
           FROM candidates
           WHERE used_in_issue IS NULL AND triaged_at IS NOT NULL
             AND section = %s AND keep_score >= %s
           ORDER BY keep_score DESC LIMIT %s""",
        (section, MIN_KEEP_SCORE, limit))
    return [dict(zip(["id", "blurb", "domain", "keep_score", "canonical_url"], r))
            for r in rows]


def edit_section(section: str, target: int) -> list[dict]:
    # Over-supply the editor so it has room to cut.
    items = pool(section, int(target * 1.8))
    if not items:
        return []
    resp = client().messages.create(
        model=EDITOR_MODEL,
        max_tokens=4000,
        system=SYSTEM,
        tools=[SECTION_TOOL],
        tool_choice={"type": "tool", "name": "build_section"},
        messages=[{"role": "user", "content": build_user_message(
            section, items, style_examples(section, 30), target)}],
    )
    raw = next(b.input for b in resp.content if b.type == "tool_use")
    by_id = {i["id"]: i for i in items}
    chosen = validate_section_selection(raw, pool_ids=set(by_id), target=target)
    return [{**by_id[entry.id], "blurb": entry.blurb, "section": section}
            for entry in chosen]


def tag_for(domain: str) -> str:
    rows = query("SELECT canonical_tag FROM source_tags WHERE domain=%s", (domain,))
    if rows:
        return rows[0][0]
    stem = domain.split(".")[0]
    return stem[:1].upper() + stem[1:]


def next_issue_number() -> int:
    rows = query("SELECT coalesce(max(issue), 250) FROM historical_links")
    used = query("SELECT coalesce(max(used_in_issue), 0) FROM candidates")
    return max(rows[0][0], used[0][0]) + 1


def build() -> dict:
    issue = next_issue_number()
    q = quotas()
    sections = {}
    for s in SECTIONS:
        try:
            sections[s] = edit_section(s, q[s])
        except Exception as exc:          # one bad section shouldn't sink the draft
            print(f"  {s}: section edit failed, leaving empty ({exc})")
            sections[s] = []
    for items in sections.values():
        for it in items:
            it["tag"] = tag_for(it["domain"])
    return {"issue": issue, "date": date.today(), "sections": sections}


def publish(issue: int, drafts_dir: str = "drafts") -> int:
    """Mark exactly what survived review as published.

    Reads the (possibly hand-edited) drafts/issue-N.md directly rather
    than recomputing a selection - the editor model never runs here, so
    what gets marked used always matches what a human actually reviewed
    and sent, cuts included. Call this once, after the issue has actually
    gone out.
    """
    path = Path(drafts_dir) / f"issue-{issue}.md"
    items = parse_published(path)
    ids = [it["id"] for it in items]
    if not ids:
        print(f"no surviving items found in {path} - nothing to publish")
        return 0

    with conn().cursor() as cur:
        cur.execute("UPDATE candidates SET used_in_issue=%s WHERE id = ANY(%s)",
                    (issue, ids))
        cur.execute(
            """INSERT INTO seen_urls (canonical_url, first_seen_on, issue)
               SELECT canonical_url, %s, %s FROM candidates WHERE id = ANY(%s)
               ON CONFLICT DO NOTHING""",
            (date.today(), issue, ids))
    print(f"published issue {issue}: {len(ids)} links marked used")
    return len(ids)
