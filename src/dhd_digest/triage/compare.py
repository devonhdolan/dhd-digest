"""Before/after report for a scoring change. Read-only: nothing is written to
the database.

    dhd compare [drafts/issue-N.md]

Re-scores this week's open candidates with the current triage prompt and
scoring, then shows what the section editor would be offered under the stored
(old) scores versus the new ones, section by section. Given a draft, it also
says which of that draft's items would still make the pool.
"""
import os
from collections import Counter
from pathlib import Path

from ..config import CANDIDATE_MAX_AGE_DAYS, MIN_FIT, MIN_KEEP_SCORE, SECTIONS
from ..db.client import query
from ..editor.assemble import bad_link, domain_caps, pool_size, quotas, select_pool
from ..render.markdown import parse_published
from .score import CANDIDATE_COLUMNS, score_candidates

# The bar before this change. Anything the old scoring put below RESCORE_FLOOR
# is very unlikely to clear the new resemblance bar (resemblance is the old
# judgment, re-asked), so it isn't worth a model call.
OLD_MIN_KEEP_SCORE = 6
RESCORE_FLOOR = 5
LIST_LIMIT = 40


def load(days: int, include_ids: list[int]) -> list[dict]:
    """Open candidates from the window, plus every item of the draft being
    compared whatever its age."""
    cols = CANDIDATE_COLUMNS + ["section", "keep_score", "blurb"]
    rows = query(
        f"""SELECT {', '.join(cols)} FROM candidates
            WHERE triaged_at IS NOT NULL
              AND ((used_in_issue IS NULL
                    AND first_seen_at > now() - make_interval(days => %s)
                    AND keep_score >= %s)
                   OR id = ANY(%s))""",
        (days, RESCORE_FLOOR, include_ids))
    return [dict(zip(cols, r)) for r in rows]


def line(it: dict) -> str:
    return f"- {it['blurb']} — `{it['domain']}`"


def rescored_line(it: dict) -> str:
    return (f"- {it['new_blurb']} — `{it['domain']}` · fit {it['fit']}, "
            f"resemblance {it['resemblance']}, was {it['old_score']:.1f} in "
            f"{it['old_section']}  \n  _{it['reasoning']}_")


def run(draft: str | None = None, days: int = CANDIDATE_MAX_AGE_DAYS,
        out_path: str = "compare-report.md") -> str:
    draft_items = parse_published(draft) if draft and Path(draft).exists() else []
    cands = load(days, [it["id"] for it in draft_items])
    print(f"re-scoring {len(cands)} candidates: open ones from the last {days} days "
          f"with a stored score >= {RESCORE_FLOOR}, plus {len(draft_items)} draft items")

    old, new = [], []
    for cand, _vec, judgment, score in score_candidates(cands, workers=8):
        base = {"id": cand["id"], "domain": cand["domain"],
                "canonical_url": cand["canonical_url"]}
        old.append({**base, "section": cand["section"], "keep_score": cand["keep_score"],
                    "blurb": cand["blurb"]})
        new.append({**base, "section": judgment.section, "keep_score": score,
                    "blurb": judgment.blurb, "new_blurb": judgment.blurb,
                    "fit": judgment.fit, "resemblance": judgment.keep_score,
                    "reasoning": judgment.reasoning,
                    "old_section": cand["section"], "old_score": cand["keep_score"]})
    new_by_id = {it["id"]: it for it in new}

    q = quotas()
    pools_old, pools_new = {}, {}
    for s in SECTIONS:
        caps, size = domain_caps(s), pool_size(q[s])
        pools_old[s] = select_pool([i for i in old if i["section"] == s], caps, size,
                                   OLD_MIN_KEEP_SCORE, min_fit=None)
        pools_new[s] = select_pool([i for i in new if i["section"] == s], caps, size)

    md = [f"# Scoring comparison — last {days} days",
          "",
          f"{len(new)} open candidates re-scored (of {len(cands)} with a stored "
          f"score of {RESCORE_FLOOR}+). Old bar: score ≥ {OLD_MIN_KEEP_SCORE}. "
          f"New bar: fit ≥ {MIN_FIT} and resemblance ≥ {MIN_KEEP_SCORE}. "
          "“Pool” is what the section editor is offered: best first, capped per "
          "domain, up to 1.8× the section's slots. Both pools drop tracker, junk "
          "and stale links, so differences here are down to scoring alone.",
          "",
          "| Section | Slots | Eligible before | Eligible after | Pool before | Pool after |",
          "|---|---|---|---|---|---|"]
    for s in SECTIONS:
        elig_old = sum(1 for i in old if i["section"] == s and i["keep_score"] >= OLD_MIN_KEEP_SCORE)
        elig_new = sum(1 for i in new if i["section"] == s and i["fit"] >= MIN_FIT
                       and i["keep_score"] >= MIN_KEEP_SCORE)
        md.append(f"| {s} | {q[s]} | {elig_old} | {elig_new} | "
                  f"{len(pools_old[s])} | {len(pools_new[s])} |")

    md += ["", "## Fit by section (new scoring, all re-scored candidates)", "",
           "| Section | fit 1–3 | fit 4–6 | fit 7–8 | fit 9–10 |", "|---|---|---|---|---|"]
    for s in SECTIONS:
        f = Counter("1–3" if i["fit"] <= 3 else "4–6" if i["fit"] <= 6
                    else "7–8" if i["fit"] <= 8 else "9–10"
                    for i in new if i["section"] == s)
        md.append(f"| {s} | {f['1–3']} | {f['4–6']} | {f['7–8']} | {f['9–10']} |")

    for s in SECTIONS:
        old_ids = {i["id"] for i in pools_old[s]}
        new_ids = {i["id"] for i in pools_new[s]}
        out = [new_by_id[i] for i in old_ids - new_ids]
        out.sort(key=lambda it: (it["fit"], it["resemblance"]))
        came_in = [new_by_id[i] for i in new_ids - old_ids]
        came_in.sort(key=lambda it: -it["keep_score"])
        kept = [i for i in pools_new[s] if i["id"] in old_ids]
        md += ["", f"## {s}", "",
               f"{len(kept)} stay, {len(out)} leave, {len(came_in)} come in.", "",
               f"### Leaves the pool ({len(out)})", ""]
        md += [rescored_line(it) for it in out[:LIST_LIMIT]] or ["_none_"]
        if len(out) > LIST_LIMIT:
            md.append(f"- …and {len(out) - LIST_LIMIT} more")
        md += ["", f"### Comes into the pool ({len(came_in)})", ""]
        md += [rescored_line(it) for it in came_in[:LIST_LIMIT]] or ["_none_"]
        md += ["", f"### Stays ({len(kept)})", ""]
        md += [line(it) for it in kept[:LIST_LIMIT]] or ["_none_"]

    if draft_items:
        items = draft_items
        in_new_pool = {i["id"] for s in SECTIONS for i in pools_new[s]}
        labels = {"stays": "Still offered to the editor",
                  "bad link": "Out: tracker, junk or stale link (link filters, not scoring)",
                  "off beat": f"Out: off the beat (fit < {MIN_FIT})",
                  "resemblance": f"Out: on the beat but resemblance < {MIN_KEEP_SCORE}",
                  "squeezed": "Out: cleared both bars but lost to better items or the domain cap",
                  "not re-scored": "Not re-scored"}
        verdicts = {k: [] for k in labels}
        for it in items:
            n = new_by_id.get(it["id"])
            if n is None:
                verdicts["not re-scored"].append(f"- {it['blurb']}")
                continue
            detail = f" · {n['section']}, fit {n['fit']}, resemblance {n['resemblance']}"
            if it["id"] in in_new_pool:
                key = "stays"
            elif bad_link(n["canonical_url"]):
                key = "bad link"
            elif n["fit"] < MIN_FIT:
                key = "off beat"
            elif n["keep_score"] < MIN_KEEP_SCORE:
                key = "resemblance"
            else:
                key = "squeezed"
            line_ = f"- {it['blurb']}{detail}"
            if key in ("off beat", "resemblance"):
                line_ += f"  \n  _{n['reasoning']}_"
            verdicts[key].append(line_)
        md += ["", f"## Draft {Path(draft).name} under the new scoring", "",
               f"Of {len(items)} items: " + ", ".join(
                   f"{len(v)} {k}" for k, v in verdicts.items() if v) + ".", ""]
        for key, label in labels.items():
            if verdicts[key]:
                md += [f"### {label} ({len(verdicts[key])})", ""]
                md += verdicts[key] + [""]

    report = "\n".join(md) + "\n"
    Path(out_path).write_text(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(report)
    print(report)
    return report
