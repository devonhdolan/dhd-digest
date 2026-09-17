"""Build a labelled eval set from the 2022 issues.

Positives: everything published in issues 219-250 (~4,500 links).
Negatives: links that ran in StrictlyVC / Future Party / DealBook during the
same weeks and never made the digest.

Fill SOURCE_ARCHIVES with archive URLs, run, then score your triage prompt
against holdout.csv and track precision@150.
"""
import csv
from pathlib import Path

SOURCE_ARCHIVES = {
    # "strictlyvc": "https://...",
    # "futureparty": "https://...",
    # "dealbook":    "https://...",
}

ROOT = Path(__file__).resolve().parents[1]


def positives(start_issue: int = 219) -> list[dict]:
    rows = []
    for r in csv.DictReader(open(ROOT / "data" / "links.csv")):
        if int(r["issue"]) >= start_issue:
            rows.append({"url": r["url"], "section": r["section"],
                         "date": r["date"], "label": 1})
    return rows


def negatives() -> list[dict]:
    raise NotImplementedError(
        "Scrape SOURCE_ARCHIVES for the matching weeks, canonicalize, and drop "
        "anything whose canonical_url appears in positives. Everything left is "
        "a labelled reject.")


if __name__ == "__main__":
    pos = positives()
    with open(ROOT / "eval" / "holdout.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["url", "section", "date", "label"])
        w.writeheader()
        w.writerows(pos)
    print(f"{len(pos)} positives written. Add negatives to make it a real eval.")
