# dhd-digest

Automated link curator for the Devon H. Dolan Link Digest, calibrated on the
250-issue archive (Sept 2017 – Dec 2022, 29,928 links).

The premise: the archive is a labelled dataset of one editor's taste. Every new
link is scored by resemblance to what was actually published, not by keyword
match.

## How it works

```
feeds + newsletter inbox
        ↓  ingest      daily — canonicalize, unwrap trackers, dedup vs 29,819 published urls
    candidates
        ↓  triage      daily — embed, pull 20 archive neighbours per section, Haiku judges
   scored candidates
        ↓  assemble    weekly — one Sonnet call per section, mix enforced at 37/22/21/20
     drafts/issue-NNN.md → pull request → your review → publish
```

## What's calibrated from the archive

| Measurement | Value | Where it's enforced |
|---|---|---|
| Section mix, stable ±3pts for 5 years | Collab 37.1 / Tech 22.5 / Ent 20.6 / Media 19.7 | `config.SECTION_MIX` |
| Blurb length | median 8 words, p99 17 | `config.BLURB_MAX_WORDS_BY_SECTION` |
| Tech items that are fundraises | 52.5% | `triage/prompts.py` section brief |
| Entertainment items that are fundraises | 1.0% | same |
| URLs ever repeated | 102 of 29,819 | `seen_urls`, seeded at load |
| Links carrying an aside | 5.4% (~8/issue) | left to the human pass |
| Domains tagged inconsistently | 318 of 386 | `data/source_tags.csv` |

## Setup

**1. Database.** Neon free tier, or any Postgres 15+ with `pgvector`.

```bash
cp .env.example .env     # fill in DATABASE_URL, ANTHROPIC_API_KEY, VOYAGE_API_KEY
uv sync
uv run dhd init-db
```

**2. Load the corpus.** Do this before anything else — nothing downstream works
without it. Takes a few minutes and well under a dollar of embedding spend.

```bash
uv run dhd load-corpus
```

Sanity check before moving on: embed a few 2022 items and look at their
neighbours. If they aren't from the same section and obviously related, the
embedding string in `corpus/embed.py:historical_text` needs work.

**3. Ingestion.** Pick one.

*Feedbin (recommended, ~$5/mo).* One API for both RSS and newsletter-to-feed
addresses. Set `FEEDBIN_USER` / `FEEDBIN_PASSWORD`.

*Gmail IMAP (free).* New account, one label, 2FA plus a 16-character app
password. Set the `IMAP_*` vars. Google keeps narrowing this path; expect to
migrate to the Gmail API eventually.

Either way, subscribe to: StrictlyVC, Future Party, DealBook, Axios Pro Rata and
Media Trends, The Ankler, Puck, Stratechery, The Information, Screentime,
Matthew Ball, Digital Native, The Generalist. Add straight RSS for the top
domains — Deadline, Variety, THR, TechCrunch, The Verge, VentureBeat, IndieWire —
which are ~47% of the archive between them and don't depend on send schedules.

Paid newsletters tied to your real address usually can't be re-subscribed under
a second one. Handle those with a forwarding filter on your primary Gmail:
match sender → forward to the digest address → archive. Set this up on day one.

**4. Run it.**

```bash
uv run dhd ingest      # fetch, canonicalize, dedup
uv run dhd triage      # score against the archive
uv run dhd assemble    # writes drafts/issue-251.md
```

**5. Schedule.** Add `DATABASE_URL`, `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, and
your ingestion credentials as repo secrets. The two workflows then run daily at
6am and Sunday at 6pm Pacific. The weekly job opens a PR rather than publishing.

## The human pass

Review the PR. Three jobs, ~15 minutes:

1. Delete the dozen items that are on-target but dull.
2. Add asides to the ~8 that deserve one. This is the only part a model can't do.
3. Fill in Listen / Read / Watch.

Merging the PR does not publish. Run `dhd publish <issue-number>` after the
issue actually goes out — that's what marks the links as used and adds them
to `seen_urls`. It reads `drafts/issue-N.md` directly, so whatever you cut
or edited during review is exactly what gets published; it never re-runs
the editor model.

## Measuring it

`eval/build_holdout.py` extracts issues 219–250 as positives (~4,500 links). Add
negatives by scraping StrictlyVC, Future Party and DealBook for the same weeks;
anything they ran that never made the digest is a labelled reject. Then score
the triage prompt and track precision@150. Without this you're guessing about
whether the kNN prior is doing work or Claude is just being agreeable.

## Tuning

- `config.MIN_KEEP_SCORE` — how selective triage is. Start at 6.
- `config.CONVERGENCE_BOOST` — reward for links carried by multiple sources.
  Cross-source agreement was historically the strongest signal.
- `config.NEIGHBORS_PER_SECTION` — more context per judgment, more tokens.
- `RESOLVE_REDIRECTS=false` — stops unwrapping tracker links, which avoids
  registering clicks with newsletter ESPs. Some links then stay wrapped and get
  dropped as junk.

## Costs

A few hundred Haiku triage calls plus four Sonnet calls a week, one embedding
pass at setup, and an incremental embed per candidate. Small, but check current
API rates rather than trusting an estimate.
