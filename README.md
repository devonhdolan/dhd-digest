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
| Tech items about media, music, games, video, creators, ads or sport | ~60% (keyword estimate) | `fit` score in `triage/prompts.py`; pool requires fit ≥ `config.MIN_FIT` |
| Entertainment items that are fundraises | 1.0% | same |
| URLs ever repeated | 102 of 29,819 | `seen_urls`, seeded at load |
| Links from one domain in one section of an issue, p90 | 3 overall; per domain from the archive | `config.DOMAIN_CAP_DEFAULT`, `editor/assemble.py:domain_caps` |
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
Matthew Ball, Digital Native, The Generalist.

The trades are read directly as RSS, whichever inbox path you use:
`data/feeds.csv` lists Deadline, Variety, THR, IndieWire, TheWrap and
TechCrunch's media & entertainment feed. Newsletters carry little trade
dealflow, so without these Entertainment runs thin. `uv run dhd feeds` checks
the list without writing anything.

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
your ingestion credentials as repo secrets. Two Claude Routines start the
workflows through `workflow_dispatch`: daily at 6:17am Pacific and Sundays at
8:17am (Pacific time year-round). The workflows have no GitHub `schedule:`
because GitHub's cron ran hours late and sometimes not at all. To run either by
hand, use Actions → the workflow → Run workflow. If the two overlap on a Sunday,
one waits for the other. The weekly job opens a PR rather than publishing.

## Daily review (teaching the curation)

After each daily run, a GitHub issue titled **Daily review – <date>** lists
up to 40 items that cleared triage since the last review, by section, plus
up to 8 near misses.

- **Tick anything that shouldn't be in the dossier**, then close the issue.
  Unticked items count as keeps. Ticked near misses are pulled in.
- **Skip a day:** close it as *not planned*. Nothing is recorded.
- Closing runs **record-review**, which stores every verdict and comments
  the tally.
- **What your verdicts do:** a cut item never reaches a draft, and a pulled-in
  near miss is pinned for the next one. Triage then shows your verdicts on the
  most similar past items, and your keep rate for the candidate's domain, next
  to the archive examples. It weighs yours first.
- **The weekly draft counts too:** `dhd publish N` records what you kept and
  cut in draft N the same way.

Checkboxes work in the GitHub mobile app, so a day's review is a couple of
minutes of tapping. There are no extra model calls; the only added cost is
a few hundred tokens of context per triage call.

## Forwarding links in (picks)

Email a link to the digest inbox and it goes in the next draft, whatever
triage thinks of it. Picks skip the scoring bars, section limits, the domain
cap and the age window, and the editor model is told to keep them.

- **Counts as a pick:** mail from an address in the `OWNER_EMAILS` secret
  (comma-separated), or anything with a `Fwd:`/`FW:` subject. Newsletters
  auto-forwarded by a Gmail filter keep their own sender, so they don't count.
- **Which link:** any link you type above the forwarded part wins; your
  signature and links on your own email domain are ignored. With nothing
  typed, a forwarded email with up to 3 links is pinned whole. A forwarded
  newsletter with more is ambiguous and goes through normal scoring, so put
  the link you want at the top.
- **Where it's read:** the inbox (`IMAP_PICKS_FOLDER`, default `INBOX`) as
  well as `IMAP_FOLDER`. The Sunday job ingests again right before
  assembling, so anything forwarded before it starts (Sunday morning) makes
  that week's draft. Later forwards go into the next one.
- A pick already published in an earlier issue is skipped and logged.

## Changing the scoring

Triage gives each link two scores: `fit` (is it on the beat: the creative
and media industries and the tech reshaping them) and resemblance (did the
editor publish things like it). The stored `keep_score` is the lower of the two.

Any PR touching triage, retrieval, the editor or `config.py` runs the
**rescore** workflow in compare mode. It re-scores the week's candidates with
the PR's code and posts a before/after report as the job summary. Nothing is
written. After merging, run **rescore → apply** once, so candidates already
scored the old way get re-triaged before the next draft.

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

## Before triage (free filters)

Ingest drops, before any model call: tracker and personal links, social
"follow us" footers (bare profiles, not posts), a short list of recurring
sponsors (`normalize.BLOCKED_DOMAINS`) and newsletter furniture anchors
("Read online", "Sponsored by"). Paywalled papers (WSJ, NYT, Bloomberg,
Reuters, CNBC) block the page fetch, so when a fetch comes back as a captcha
or "Access Denied" the newsletter's own sentence about the story is used as
the headline instead. `uv run dhd junk-report` (or rescore → junk-report)
shows, free, what triage paid for that a filter could have dropped.

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
