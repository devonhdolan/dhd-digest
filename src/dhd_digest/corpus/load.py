"""One-time loader: archive CSV -> Postgres, embedded and indexed.

    dhd load-corpus

~30k rows. A few minutes and well under a dollar of embedding spend.
"""
import csv
from pathlib import Path

from ..db.client import conn, executemany
from ..ingest.normalize import canonicalize
from .embed import embed, historical_text

DATA = Path(__file__).resolve().parents[3] / "data"


def load_source_tags():
    rows = list(csv.DictReader(open(DATA / "source_tags.csv")))
    executemany(
        """INSERT INTO source_tags (domain, canonical_tag, uses, variants)
           VALUES (%s,%s,%s,%s) ON CONFLICT (domain) DO UPDATE
           SET canonical_tag = EXCLUDED.canonical_tag""",
        [(r["domain"], r["canonical_tag"], int(r["uses"]), r["variants"]) for r in rows],
    )
    print(f"source_tags: {len(rows)} domains")


def load_links(batch_size: int = 500):
    rows = list(csv.DictReader(open(DATA / "links.csv")))
    print(f"embedding {len(rows)} archive links...")
    inserted = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        vectors = embed([historical_text(r) for r in batch])
        payload = []
        for r, v in zip(batch, vectors):
            cu = canonicalize(r["url"])
            payload.append((
                int(r["issue"]), r["date"] or None, r["section"], r["tag"],
                r["url"], cu, r["domain"], r["blurb"], int(r["blurb_words"] or 0),
                r["aside"] or None, r["is_raise"] == "True", r["amount"] or None, v,
            ))
        executemany(
            """INSERT INTO historical_links
               (issue, published_on, section, tag, url, canonical_url, domain,
                blurb, blurb_words, aside, is_raise, amount, embedding)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            payload,
        )
        inserted += len(payload)
        print(f"  {inserted}/{len(rows)}")
    print("historical_links loaded")


def seed_seen_urls():
    """Everything ever published is off the table forever."""
    with conn().cursor() as cur:
        cur.execute(
            """INSERT INTO seen_urls (canonical_url, first_seen_on, issue)
               SELECT DISTINCT ON (canonical_url) canonical_url, published_on, issue
               FROM historical_links
               WHERE canonical_url IS NOT NULL
               ORDER BY canonical_url, published_on
               ON CONFLICT DO NOTHING""")
        cur.execute("SELECT count(*) FROM seen_urls")
        print(f"seen_urls seeded: {cur.fetchone()[0]}")


def run():
    load_source_tags()
    load_links()
    seed_seen_urls()
