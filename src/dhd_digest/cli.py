"""dhd <command>

  init-db       apply schema.sql
  load-corpus   load + embed the 250-issue archive, seed seen_urls
  ingest        daily: fetch feeds/mail, canonicalize, dedup, store candidates
  feeds         read-only check of data/feeds.csv: items per feed, sample titles
  triage        daily: score untriaged candidates against the archive
  compare [F] [--feeds]  read-only before/after report for a scoring change;
                F = a draft to check, --feeds = also score the trade feeds' current items
  junk-report [D]  read-only: which links triage paid for that a free filter could drop
  retriage      queue this week's open candidates scored the old way for re-triage
  review-open   daily: open today's review issue (tick what doesn't belong)
  review-prune F    keep only draft F's items in its weekly review listing
  review-record N   record the verdicts on closed review issue N
  assemble      weekly: build drafts/issue-NNN.md
  publish N     mark issue N's surviving (reviewed) links as published
  stats         quick health check
"""
import sys


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "init-db":
        from .db.client import init_db
        init_db()
    elif cmd == "load-corpus":
        from .corpus.load import run
        run()
    elif cmd == "ingest":
        from .ingest.run import run
        run()
    elif cmd == "feeds":
        from .ingest.rss import check
        check()
    elif cmd == "triage":
        from .triage.score import run
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 500
        run(limit)
    elif cmd == "compare":
        from .triage.compare import run
        args = sys.argv[2:]
        draft = next((a for a in args if not a.startswith("--")), None)
        run(draft or None, feeds="--feeds" in args)
    elif cmd == "junk-report":
        from .triage.junk import run
        run(int(sys.argv[2]) if len(sys.argv) > 2 else 7)
    elif cmd == "retriage":
        from .config import CANDIDATE_MAX_AGE_DAYS
        from .db.client import execute
        # Worth re-scoring only what the old scoring rated 5+:
        # the new bars are stricter, so lower scorers can't clear them.
        floor = 5
        restored = execute(
            """UPDATE candidates SET triaged_at = now()
               WHERE triaged_at IS NULL AND fit_score IS NULL
                 AND keep_score IS NOT NULL AND keep_score < %s""", (floor,))
        n = execute(
            """UPDATE candidates SET triaged_at = NULL
               WHERE used_in_issue IS NULL AND fit_score IS NULL
                 AND triaged_at IS NOT NULL AND keep_score >= %s
                 AND first_seen_at > now() - make_interval(days => %s)""",
            (floor, CANDIDATE_MAX_AGE_DAYS))
        if restored:
            print(f"{restored} low scorers from an earlier retriage left as they were")
        print(f"{n} candidates queued for re-triage; run `dhd triage` next")
    elif cmd == "assemble":
        from .editor.assemble import build
        from .render.markdown import write
        from .review.daily import relist
        draft = build()
        write(draft)
        relist(f"weekly:{draft['issue']}",
                   [it["id"] for items in draft["sections"].values() for it in items])
    elif cmd == "review-open":
        from .review.daily import open_review
        open_review()
    elif cmd == "review-prune":
        # dhd review-prune drafts/issue-N.md : keep only that draft's items
        # listed under weekly:N (repairs a listing from a superseded draft)
        import re
        from .render.markdown import parse_published
        from .review.daily import prune
        path = sys.argv[2]
        n = int(re.search(r"issue-(\d+)\.md$", path).group(1))
        ids = [it["id"] for it in parse_published(path)]
        print(f"weekly:{n}: removed {prune(f'weekly:{n}', ids)} items not in {path}")
    elif cmd == "review-record":
        from .review.daily import close_review
        close_review(int(sys.argv[2]))
    elif cmd == "publish":
        if len(sys.argv) < 3:
            print("usage: dhd publish <issue-number>")
            sys.exit(1)
        from .editor.assemble import publish
        publish(int(sys.argv[2]))
    elif cmd == "stats":
        from .db.client import query
        for label, sql in [
            ("archive links", "SELECT count(*) FROM historical_links"),
            ("seen urls", "SELECT count(*) FROM seen_urls"),
            ("open candidates",
             "SELECT count(*) FROM candidates WHERE used_in_issue IS NULL"),
            ("untriaged", "SELECT count(*) FROM candidates WHERE triaged_at IS NULL"),
        ]:
            print(f"  {label:18s} {query(sql)[0][0]}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
