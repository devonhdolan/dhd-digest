"""Nearest-neighbour retrieval against the archive.

Query per section, never globally. The four sections have very different
acceptance bars - 52% of Tech items are fundraises, versus 1% of Entertainment -
so a single global query blurs exactly the signal we want.
"""
from ..config import NEIGHBORS_PER_SECTION, SECTIONS
from ..db.client import query


def neighbors_by_section(vector, k: int = NEIGHBORS_PER_SECTION) -> dict[str, list[dict]]:
    out = {}
    for section in SECTIONS:
        rows = query(
            """SELECT blurb, domain, tag, published_on,
                      1 - (embedding <=> %s::vector) AS similarity
               FROM historical_links
               WHERE section = %s AND embedding IS NOT NULL
               ORDER BY embedding <=> %s::vector
               LIMIT %s""",
            (vector, section, vector, k),
        )
        out[section] = [
            {"blurb": r[0], "domain": r[1], "tag": r[2],
             "date": str(r[3]), "similarity": round(float(r[4]), 4)}
            for r in rows
        ]
    return out


def best_section_prior(neighbors: dict[str, list[dict]]) -> tuple[str, float]:
    """Cheap prior: which section's neighbours sit closest on average."""
    scores = {
        s: sum(n["similarity"] for n in ns[:5]) / max(len(ns[:5]), 1)
        for s, ns in neighbors.items() if ns
    }
    if not scores:
        return "Collaborative", 0.0
    section = max(scores, key=scores.get)
    return section, scores[section]


def style_examples(section: str, n: int = 30) -> list[dict]:
    """Real archive lines used as few-shot style reference for the editors."""
    rows = query(
        """SELECT blurb, tag, domain, aside FROM historical_links
           WHERE section = %s AND blurb_words BETWEEN 5 AND 14
           ORDER BY random() LIMIT %s""",
        (section, n),
    )
    return [{"blurb": r[0], "tag": r[1], "domain": r[2], "aside": r[3]} for r in rows]
