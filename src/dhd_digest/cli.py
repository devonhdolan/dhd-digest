"""dhd <command>

  init-db       apply schema.sql
  load-corpus   load + embed the 250-issue archive, seed seen_urls
  ingest        daily: fetch feeds/mail, canonicalize, dedup, store candidates
  triage        daily: score untriaged candidates against the archive
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
    elif cmd == "triage":
        from .triage.score import run
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 500
        run(limit)
    elif cmd == "assemble":
        from .editor.assemble import build
        from .render.markdown import write
        write(build())
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
