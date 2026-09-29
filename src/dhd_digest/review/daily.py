"""The daily review loop: the editor's verdicts, fed back into curation.

Each day, what cleared triage since the last review goes out as a GitHub
issue of checkboxes, grouped by section, plus a few near misses. The editor
ticks what doesn't belong (and any near miss that does) and closes the issue;
review.yml then records every verdict in review_items. From then on:

- a cut item never reaches a draft, and a rescued near miss is pinned;
- triage shows the editor's verdicts on similar past items next to the
  archive neighbours, and their keep rate for the candidate's domain.

The weekly draft feeds the same table: assemble lists its items, and
`dhd publish` records what survived review as kept and the rest as cut.
"""
import re
from datetime import date

from ..config import MIN_FIT, MIN_KEEP_SCORE, SECTIONS
from ..db.client import conn, query
from ..ingest.normalize import bad_link

MAX_ITEMS = 40
MAX_NEAR_MISSES = 8
NEAR_MISS_MARKER = "<!-- near-misses -->"
LINE = re.compile(r"^\s*- \[(?P<mark>[ xX])\] .*<!-- id:(?P<id>\d+) -->\s*$")


def _unlisted(where: str, params: tuple, limit: int) -> list[dict]:
    rows = query(
        f"""SELECT c.id, c.section, c.blurb, c.canonical_url, c.domain,
                   c.fit_score, c.keep_score
            FROM candidates c
            WHERE c.triaged_at IS NOT NULL AND c.used_in_issue IS NULL AND NOT c.pinned
              AND c.fit_score IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM review_items r WHERE r.candidate_id = c.id)
              AND c.first_seen_at > now() - interval '3 days'
              AND {where}
            ORDER BY c.keep_score DESC, c.fit_score DESC LIMIT %s""",
        params + (limit * 3,))
    items = [dict(zip(["id", "section", "blurb", "url", "domain", "fit", "score"], r)) for r in rows]
    return [it for it in items if not bad_link(it["url"])][:limit]


def todays_items() -> tuple[list[dict], list[dict]]:
    """What the weekly editor would be offered (not yet reviewed), and the
    items that just missed a bar - the likeliest false negatives."""
    pool = _unlisted("c.fit_score >= %s AND c.keep_score >= %s",
                     (MIN_FIT, MIN_KEEP_SCORE), MAX_ITEMS)
    near = _unlisted("""NOT (c.fit_score >= %s AND c.keep_score >= %s)
                        AND c.fit_score >= %s AND c.keep_score >= %s""",
                     (MIN_FIT, MIN_KEEP_SCORE, MIN_FIT - 1, MIN_KEEP_SCORE - 1),
                     MAX_NEAR_MISSES)
    return pool, near


def _line(it: dict, show_section: bool = False) -> str:
    where = f" · _{it['section']}_" if show_section else ""
    return (f"- [ ] {it['blurb']} — [{it['domain']}]({it['url']}) · "
            f"fit {it['fit']:.0f} · res {it['score']:.0f}{where} <!-- id:{it['id']} -->")


def render(pool: list[dict], near: list[dict]) -> str:
    md = [f"**{len(pool)} items cleared triage** since the last review.",
          "",
          "**Tick anything that shouldn't be in the dossier**, then close this issue. "
          "Unticked items count as keeps, so skim them all. "
          "To skip a day, close it as *not planned*: nothing is recorded.",
          ""]
    for s in SECTIONS:
        items = [it for it in pool if it["section"] == s]
        if items:
            md += [f"### {s}", ""] + [_line(it) for it in items] + [""]
    if near:
        md += [NEAR_MISS_MARKER, "---", "",
               "### Near misses: tick any that **should** be in", ""]
        md += [_line(it, show_section=True) for it in near] + [""]
    return "\n".join(md)


def parse(body: str) -> dict[int, str]:
    """Checkbox states -> verdicts. In the pool a tick is a cut and no tick a
    keep; among near misses a tick is a rescue and no tick records nothing."""
    pool_part, _, near_part = body.partition(NEAR_MISS_MARKER)
    verdicts = {}
    for line in pool_part.splitlines():
        m = LINE.match(line)
        if m:
            verdicts[int(m["id"])] = "cut" if m["mark"] != " " else "keep"
    for line in near_part.splitlines():
        m = LINE.match(line)
        if m and m["mark"] != " ":
            verdicts[int(m["id"])] = "rescue"
    return verdicts


def list_items(review: str, pool_ids: list[int], near_ids: list[int] = ()):
    with conn().cursor() as cur:
        cur.executemany(
            """INSERT INTO review_items (candidate_id, review, near_miss)
               VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
            [(i, review, False) for i in pool_ids] + [(i, review, True) for i in near_ids])


def record(review: str, verdicts: dict[int, str]) -> dict[str, int]:
    """Store verdicts for items listed under `review`. A rescue also pins
    the candidate so it goes in the next draft."""
    with conn().transaction(), conn().cursor() as cur:
        for cid, verdict in verdicts.items():
            cur.execute(
                """UPDATE review_items SET verdict = %s, reviewed_at = now()
                   WHERE candidate_id = %s AND review = %s""", (verdict, cid, review))
        rescued = [cid for cid, v in verdicts.items() if v == "rescue"]
        if rescued:
            cur.execute("UPDATE candidates SET pinned = TRUE WHERE id = ANY(%s)", (rescued,))
    counts = {v: 0 for v in ("keep", "cut", "rescue")}
    for v in verdicts.values():
        counts[v] += 1
    return counts


def open_review():
    from . import github
    pool, near = todays_items()
    if not pool and not near:
        print("nothing new to review today")
        return
    today = date.today()
    number = github.open_issue(f"Daily review – {today:%a %b %-d}", render(pool, near))
    list_items(f"daily:{number}", [it["id"] for it in pool], [it["id"] for it in near])
    print(f"opened review issue #{number}: {len(pool)} items, {len(near)} near misses")


def close_review(number: int):
    from . import github
    counts = record(f"daily:{number}", parse(github.issue_body(number)))
    msg = (f"Recorded: {counts['keep']} kept, {counts['cut']} cut, "
           f"{counts['rescue']} near misses pulled in. Cuts won't reach a draft; "
           "rescues are pinned for the next one.")
    github.comment(number, msg)
    print(msg)
