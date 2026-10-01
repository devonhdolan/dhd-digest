"""Where triage spend goes to waste. Read-only, no model calls.

    dhd junk-report [days]

Looks at what triage scored over the last `days` and finds the links a free
filter could have dropped before the model call: link shapes that never make
the dossier (podcast apps, homepages, social profiles), domains that never
clear the bars and were never published in the archive, and newsletters
whose links almost never clear.
"""
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

from ..config import MIN_FIT, MIN_KEEP_SCORE
from ..db.client import query

# Link shapes worth checking. Each is a guess until the numbers say otherwise.
SHAPES = [
    ("homepage (no path)", lambda u, p: p.path in ("", "/") and not p.query),
    ("podcast/music app", lambda u, p: re.search(
        r"(podcasts\.apple|open\.spotify|music\.apple|overcast\.fm|pca\.st|"
        r"pocketcasts|castbox|podcasts\.google)", p.netloc)),
    ("social profile/post", lambda u, p: re.search(
        r"(^|\.)(twitter|x|instagram|tiktok|linkedin|facebook|threads|bsky)\.(com|net|app)$",
        p.netloc)),
    ("substack profile/redirect", lambda u, p: "substack.com" in p.netloc and
        (p.path.startswith(("/@", "/redirect")) or p.path in ("", "/"))),
    ("youtube", lambda u, p: re.search(r"(youtube\.com|youtu\.be)$", p.netloc)),
    ("app store", lambda u, p: re.search(r"(apps\.apple\.com|play\.google\.com)", p.netloc)),
    ("forms/scheduling/events", lambda u, p: re.search(
        r"(docs\.google\.com/forms|forms\.gle|typeform|calendly|eventbrite|lu\.ma|zoom\.us)",
        u)),
    ("jobs/careers", lambda u, p: re.search(r"(/jobs?\b|/careers?\b|greenhouse\.io|lever\.co)", u)),
]
PAPERS = ["wsj.com", "nytimes.com", "bloomberg.com", "reuters.com", "cnbc.com",
          "ft.com", "washingtonpost.com", "latimes.com", "theinformation.com"]
SHORT_ANCHOR = re.compile(r"^\W*(\w+\W*){0,2}$")   # "Read more", "here", "Listen"


def cleared(fit, keep):
    return fit is not None and fit >= MIN_FIT and (keep or 0) >= MIN_KEEP_SCORE


def run(days: int = 7, out_path: str = "junk-report.md") -> str:
    rows = query(
        """SELECT canonical_url, domain, anchor_text, sources, fit_score, keep_score,
                  coalesce(reasoning, '') LIKE 'bad link%%'
           FROM candidates
           WHERE triaged_at IS NOT NULL AND NOT coalesce(pinned, false)
             AND first_seen_at > now() - make_interval(days => %s)""", (days,))
    archive = {d: n for d, n in query(
        "SELECT domain, count(*) FROM historical_links GROUP BY domain")}

    closed_free = sum(1 for r in rows if r[6])
    scored = [r for r in rows if not r[6] and r[4] is not None]
    n = len(scored)
    ok = [r for r in scored if cleared(r[4], r[5])]

    md = [f"# Where triage spend goes — last {days} days", "",
          f"{n} links went to the model ({closed_free} more were closed free as bad links). "
          f"{len(ok)} cleared both bars (fit ≥ {MIN_FIT}, resemblance ≥ {MIN_KEEP_SCORE}): "
          f"{100 * len(ok) / max(n, 1):.0f}%.", "",
          "| Fit | Links |", "|---|---|"]
    bands = Counter("1–3" if r[4] <= 3 else "4–6" if r[4] <= 6 else "7–10" for r in scored)
    md += [f"| {b} | {bands[b]} |" for b in ("1–3", "4–6", "7–10")]

    # Link shapes
    md += ["", "## Link shapes", "",
           "A shape is safe to drop before triage if almost none of it clears.", "",
           "| Shape | Links | Cleared | Example that cleared |", "|---|---|---|---|"]
    shape_hits = set()
    for name, test in SHAPES:
        hit = [r for r in scored if test(r[0], urlparse(r[0]))]
        good = [r for r in hit if cleared(r[4], r[5])]
        shape_hits.update(r[0] for r in hit)
        md.append(f"| {name} | {len(hit)} | {len(good)} | "
                  f"{good[0][0] if good else '—'} |")
    short = [r for r in scored if r[2] and SHORT_ANCHOR.match(r[2])]
    md.append(f"| anchor of ≤3 words (\"Read more\") | {len(short)} | "
              f"{sum(cleared(r[4], r[5]) for r in short)} | — |")

    # Domains
    by_dom = defaultdict(list)
    for r in scored:
        by_dom[r[1]].append(r)
    never = sorted(((d, rs) for d, rs in by_dom.items()
                    if len(rs) >= 3 and not any(cleared(r[4], r[5]) for r in rs)
                    and archive.get(d, 0) == 0),
                   key=lambda x: -len(x[1]))
    md += ["", "## Domains that never cleared and were never published", "",
           f"Seen 3+ times, nothing cleared, and 0 links in the 250-issue archive. "
           f"{sum(len(rs) for _, rs in never)} links across {len(never)} domains.", "",
           "| Domain | Links | Best fit | Sample anchor |", "|---|---|---|---|"]
    for d, rs in never[:40]:
        best = max(rs, key=lambda r: r[4])
        md.append(f"| {d} | {len(rs)} | {best[4]} | {(best[2] or '')[:60]} |")

    # High-volume domains with a low hit rate, but published before: not for a blocklist
    md += ["", "## Busiest domains", "",
           "| Domain | Links | Cleared | In archive |", "|---|---|---|---|"]
    for d, rs in sorted(by_dom.items(), key=lambda x: -len(x[1]))[:25]:
        md.append(f"| {d} | {len(rs)} | {sum(cleared(r[4], r[5]) for r in rs)} | "
                  f"{archive.get(d, 0)} |")

    # Sources
    by_src = defaultdict(list)
    for r in scored:
        for s in (r[3] or ["?"]):
            by_src[s].append(r)
    md += ["", "## Newsletters and feeds", "",
           "Links each source sent to triage and how many cleared. A source with "
           "many links and few clears is the costliest per useful link.", "",
           "| Source | Links | Cleared | Rate |", "|---|---|---|---|"]
    for s, rs in sorted(by_src.items(), key=lambda x: -len(x[1]))[:30]:
        good = sum(cleared(r[4], r[5]) for r in rs)
        md.append(f"| {s} | {len(rs)} | {good} | {100 * good / len(rs):.0f}% |")

    # What triage saw for the big paywalled papers
    papers = query(
        """SELECT domain, headline, anchor_text, left(context, 140), left(excerpt, 140),
                  fit_score, left(reasoning, 160)
           FROM candidates
           WHERE triaged_at IS NOT NULL AND fit_score IS NOT NULL
             AND domain = ANY(%s)
             AND first_seen_at > now() - make_interval(days => %s)
           ORDER BY first_seen_at DESC LIMIT 25""", (PAPERS, days))
    md += ["", "## What triage saw for the big papers", ""]
    for d, h, a, c, e, f, why in papers:
        md += [f"- **{d}** · fit {f}", f"  - headline: {h!r}", f"  - anchor: {a!r}",
               f"  - context: {c!r}", f"  - excerpt: {e!r}", f"  - why: {why}"]

    # Bottom line
    droppable = shape_hits | {r[0] for _, rs in never for r in rs}
    lost = [r for r in scored if r[0] in droppable and cleared(r[4], r[5])]
    md += ["", "## If all of the above were filtered", "",
           f"{len(droppable)} of {n} model calls saved "
           f"({100 * len(droppable) / max(n, 1):.0f}%), losing {len(lost)} links that cleared:", ""]
    md += [f"- {r[0]} · fit {r[4]}" for r in lost[:30]] or ["_none_"]

    report = "\n".join(md) + "\n"
    Path(out_path).write_text(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(report)
    print(report)
    return report
