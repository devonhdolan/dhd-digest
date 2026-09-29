"""Score untriaged candidates against the archive."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import (ANTHROPIC_API_KEY, BLURB_MAX_WORDS_BY_SECTION,
                      CONVERGENCE_BOOST, TRIAGE_MODEL)
from ..corpus.embed import candidate_text, embed
from ..corpus.search import best_section_prior, editor_feedback, neighbors_by_section
from ..db.client import execute, query
from ..ingest.normalize import bad_link
from ..validation import TriageJudgment, validate_triage_judgment
from .prompts import SYSTEM, TRIAGE_TOOL, build_user_message

_client = None


def client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


@retry(stop=stop_after_attempt(4), wait=wait_exponential(min=2, max=30))
def judge(candidate: dict, neighbors: dict, prior: str,
          feedback: dict | None = None) -> TriageJudgment:
    resp = client().messages.create(
        model=TRIAGE_MODEL,
        max_tokens=600,
        system=SYSTEM,
        tools=[TRIAGE_TOOL],
        tool_choice={"type": "tool", "name": "record_judgment"},
        messages=[{"role": "user",
                   "content": build_user_message(candidate, neighbors, prior, feedback)}],
    )
    for block in resp.content:
        if block.type == "tool_use":
            return validate_triage_judgment(block.input)
    raise ValueError("no tool_use block returned")


def trim_blurb(blurb: str, section: str) -> str:
    cap = BLURB_MAX_WORDS_BY_SECTION.get(section, 12)
    words = blurb.split()
    return " ".join(words[:cap]) if len(words) > cap else blurb


def final_score(out: TriageJudgment, n_sources: int) -> float:
    """Resemblance plus the multi-source boost. Fit is not folded in: it is
    stored separately and gates the pool on its own (MIN_FIT), so an off-beat
    item stays out however well-shaped or widely carried it is."""
    resemblance = out.keep_score + CONVERGENCE_BOOST * max(n_sources - 1, 0)
    return min(resemblance, 10.0)


CANDIDATE_COLUMNS = ["id", "canonical_url", "domain", "anchor_text", "headline",
                     "excerpt", "sources"]


CHUNK = 100   # embed, look up and judge this many at a time


def score_candidates(cands: list[dict], workers: int = 4):
    """Yield (candidate, vector, judgment, final score) for each candidate
    that triaged cleanly. Reads only - callers decide what to write.

    Works in chunks: at the Voyage free tier, embedding 1,000+ texts in one
    go takes ~20 minutes, long enough for the database to drop the idle
    connection. Neighbour lookups share the one DB connection, so they run
    serially; the model calls run `workers` at a time."""
    def work(item):
        cand, vec, nbrs, prior, feedback = item
        try:
            out = judge(cand, nbrs, prior, feedback)
        except Exception as exc:              # never let one link stop the run
            print(f"  skip {cand['canonical_url']}: {exc}")
            return None
        return cand, vec, out, final_score(out, len(cand.get("sources") or []))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, len(cands), CHUNK):
            chunk = cands[start:start + CHUNK]
            vectors = embed([candidate_text(c) for c in chunk], input_type="query")
            prepared = []
            for cand, vec in zip(chunk, vectors):
                try:
                    nbrs = neighbors_by_section(vec)
                    prepared.append((cand, vec, nbrs, best_section_prior(nbrs)[0],
                                     editor_feedback(vec, cand["domain"])))
                except Exception as exc:
                    print(f"  skip {cand['canonical_url']}: {exc}")
            for result in pool.map(work, prepared):
                if result:
                    yield result
            print(f"  scored {min(start + CHUNK, len(cands))}/{len(cands)}")


def run(limit: int = 500):
    rows = query(
        f"""SELECT {', '.join(CANDIDATE_COLUMNS)}
            FROM candidates WHERE triaged_at IS NULL
            ORDER BY first_seen_at LIMIT %s""", (limit,))
    if not rows:
        print("nothing to triage")
        return

    cands = [dict(zip(CANDIDATE_COLUMNS, r)) for r in rows]

    # Links today's ingest would refuse (stored before those checks existed)
    # are closed out at zero without a model call.
    junk = {c["id"] for c in cands if bad_link(c["canonical_url"])}
    if junk:
        execute("""UPDATE candidates SET keep_score = 0, fit_score = 0, triaged_at = now(),
                          reasoning = 'bad link: tracker, junk or stale'
                   WHERE id = ANY(%s)""", (list(junk),))
        print(f"closed {len(junk)} bad links without scoring")
    cands = [c for c in cands if c["id"] not in junk]

    done = 0
    for cand, vec, out, score in score_candidates(cands):
        execute(
            """UPDATE candidates SET section=%s, keep_score=%s, fit_score=%s,
                   blurb=%s, reasoning=%s, embedding=%s, triaged_at=%s
               WHERE id=%s""",
            (out.section, score, out.fit,
             trim_blurb(out.blurb, out.section),
             out.reasoning, vec, datetime.now(timezone.utc), cand["id"]))
        done += 1
    print(f"triaged {done} of {len(cands)} candidates")
