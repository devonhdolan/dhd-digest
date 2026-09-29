"""Weekly assembly: pick, edit per section, enforce the historical mix, render."""
import math
from datetime import date
from pathlib import Path

import anthropic

from ..config import (ANTHROPIC_API_KEY, CANDIDATE_MAX_AGE_DAYS,
                      DOMAIN_CAP_DEFAULT, EDITOR_MODEL, MIN_FIT, MIN_KEEP_SCORE,
                      SECTION_MIX, SECTIONS, TARGET_LINKS_PER_ISSUE)
from ..corpus.search import style_examples
from ..db.client import conn, query
from ..ingest.normalize import bad_link
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


def domain_caps(section: str) -> dict[str, int]:
    """p90 links-per-issue for each domain in this section of the archive."""
    rows = query(
        """SELECT domain, percentile_disc(0.9) WITHIN GROUP (ORDER BY n)
           FROM (SELECT issue, domain, count(*) AS n FROM historical_links
                 WHERE section = %s GROUP BY issue, domain) per_issue
           GROUP BY domain""",
        (section,))
    return {d: max(int(n), DOMAIN_CAP_DEFAULT) for d, n in rows}


def cap_per_domain(items: list[dict], caps: dict[str, int], limit: int) -> list[dict]:
    """Walk items best-first, keeping at most caps[domain] from each domain."""
    taken: dict[str, int] = {}
    out = []
    for it in items:
        d = it["domain"]
        if taken.get(d, 0) >= caps.get(d, DOMAIN_CAP_DEFAULT):
            continue
        taken[d] = taken.get(d, 0) + 1
        out.append(it)
        if len(out) == limit:
            break
    return out


def select_pool(items: list[dict], caps: dict[str, int], limit: int,
                min_score: float = MIN_KEEP_SCORE,
                min_fit: float | None = MIN_FIT) -> list[dict]:
    """What the section editor gets offered: on the beat (fit), above the
    resemblance bar, no bad links, best first, at most caps[domain] per
    domain. min_fit=None skips the fit gate (scores from before it existed)."""
    items = sorted((it for it in items if it["keep_score"] >= min_score
                    and (min_fit is None or (it.get("fit") or 0) >= min_fit)
                    and not bad_link(it["canonical_url"])),
                   key=lambda it: (it["keep_score"], it.get("fit") or 0), reverse=True)
    return cap_per_domain(items, caps, limit)


def picks(section: str) -> list[dict]:
    """Links the editor forwarded in, for this section. No bars, no age
    window, no domain cap: they stay until published. A pick triage never
    reached (or failed on) lands in Collaborative on its headline."""
    rows = query(
        """SELECT id, coalesce(blurb, headline, anchor_text, canonical_url), domain,
                  coalesce(keep_score, 10), canonical_url, coalesce(fit_score, 10)
           FROM candidates
           WHERE pinned AND used_in_issue IS NULL
             AND (section = %s OR (section IS NULL AND %s = 'Collaborative'))
           ORDER BY first_seen_at""",
        (section, section))
    return [{**dict(zip(["id", "blurb", "domain", "keep_score", "canonical_url", "fit"], r)),
             "pinned": True} for r in rows]


def pool(section: str, limit: int) -> list[dict]:
    """The editor's picks, then the best of everything else."""
    rows = query(
        """SELECT id, blurb, domain, keep_score, canonical_url, fit_score
           FROM candidates
           WHERE used_in_issue IS NULL AND triaged_at IS NOT NULL AND NOT pinned
             AND section = %s AND keep_score >= %s AND fit_score >= %s
             AND NOT EXISTS (SELECT 1 FROM review_items r
                             WHERE r.candidate_id = candidates.id AND r.verdict = 'cut')
             AND first_seen_at > now() - make_interval(days => %s)
           ORDER BY keep_score DESC, fit_score DESC LIMIT %s""",
        # Over-fetch: the domain cap and bad-link filter cut some.
        (section, MIN_KEEP_SCORE, MIN_FIT, CANDIDATE_MAX_AGE_DAYS, limit * 4))
    items = [dict(zip(["id", "blurb", "domain", "keep_score", "canonical_url", "fit"], r))
             for r in rows]
    return picks(section) + select_pool(items, domain_caps(section), limit)


def with_picks(chosen: list[dict], items: list[dict]) -> list[dict]:
    """Every pick in the pool ends up in the section, whatever the editor
    model returned: missing ones are added at the end on their triage blurb."""
    have = {c["id"] for c in chosen}
    missing = [it for it in items if it.get("pinned") and it["id"] not in have]
    for it in missing:
        print(f"    pick {it['id']} was left out by the editor - adding it back")
    return chosen + missing


def pool_size(target: int) -> int:
    """Over-supply the editor so it has room to cut."""
    return int(target * 1.8)


def edit_section(section: str, target: int) -> list[dict]:
    items = pool(section, pool_size(target))
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
    out = [{**by_id[entry.id], "blurb": entry.blurb} for entry in chosen]
    return [{**it, "section": section} for it in with_picks(out, items)]


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

    # The review pass is a verdict on every drafted item: kept or cut.
    # (Drafts assembled before review_items existed have nothing listed.)
    from ..review.daily import record
    listed = [r[0] for r in query(
        "SELECT candidate_id FROM review_items WHERE review = %s", (f"weekly:{issue}",))]
    counts = record(f"weekly:{issue}", {cid: ("keep" if cid in set(ids) else "cut")
                                        for cid in listed})
    if listed:
        print(f"review verdicts: {counts['keep']} kept, {counts['cut']} cut")

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
