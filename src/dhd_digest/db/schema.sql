-- Postgres 15+ with pgvector. Run once: dhd init-db
CREATE EXTENSION IF NOT EXISTS vector;

-- The 29,928-link archive. Ground truth for taste.
CREATE TABLE IF NOT EXISTS historical_links (
    id            BIGSERIAL PRIMARY KEY,
    issue         INT,
    published_on  DATE,
    section       TEXT NOT NULL,
    tag           TEXT,
    url           TEXT,
    canonical_url TEXT,
    domain        TEXT,
    blurb         TEXT NOT NULL,
    blurb_words   INT,
    aside         TEXT,
    is_raise      BOOLEAN DEFAULT FALSE,
    amount        TEXT,
    embedding     vector(1024)
);
CREATE INDEX IF NOT EXISTS hist_section_idx ON historical_links (section);
CREATE INDEX IF NOT EXISTS hist_embed_idx
    ON historical_links USING hnsw (embedding vector_cosine_ops);

-- domain -> canonical source tag, majority vote across five years.
CREATE TABLE IF NOT EXISTS source_tags (
    domain        TEXT PRIMARY KEY,
    canonical_tag TEXT NOT NULL,
    uses          INT,
    variants      TEXT
);

-- Every URL ever published, so nothing repeats. Seeded from the archive.
CREATE TABLE IF NOT EXISTS seen_urls (
    canonical_url TEXT PRIMARY KEY,
    first_seen_on DATE,
    issue         INT
);

-- Links pulled this week, pre-triage.
CREATE TABLE IF NOT EXISTS candidates (
    id            BIGSERIAL PRIMARY KEY,
    canonical_url TEXT UNIQUE NOT NULL,
    raw_url       TEXT,
    domain        TEXT,
    anchor_text   TEXT,
    context       TEXT,
    headline      TEXT,
    excerpt       TEXT,
    sources       TEXT[] DEFAULT '{}',   -- which newsletters/feeds carried it
    first_seen_at TIMESTAMPTZ DEFAULT now(),
    embedding     vector(1024),
    -- triage output
    section       TEXT,
    keep_score    REAL,
    blurb         TEXT,
    reasoning     TEXT,
    triaged_at    TIMESTAMPTZ,
    used_in_issue INT
);
-- Added after launch: subject fit (1-10), gated separately from keep_score.
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS fit_score REAL;
-- Links the editor forwarded in: always included in the next draft.
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS pinned BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS cand_untriaged_idx ON candidates (triaged_at)
    WHERE triaged_at IS NULL;
CREATE INDEX IF NOT EXISTS cand_open_idx ON candidates (keep_score DESC)
    WHERE used_in_issue IS NULL;

-- Ingestion bookkeeping so reruns are idempotent.
CREATE TABLE IF NOT EXISTS fetch_state (
    source_key TEXT PRIMARY KEY,
    last_id    TEXT,
    last_run   TIMESTAMPTZ
);

-- The editor's own verdicts: every item shown for review (daily issue or
-- weekly draft), and what they decided. verdict is NULL until reviewed:
-- 'keep' | 'cut' (shown in the pool) or 'rescue' (a near miss they pulled in).
CREATE TABLE IF NOT EXISTS review_items (
    candidate_id  BIGINT NOT NULL REFERENCES candidates(id),
    review        TEXT NOT NULL,          -- 'daily:<issue>' or 'weekly:<issue>'
    near_miss     BOOLEAN NOT NULL DEFAULT FALSE,
    listed_at     TIMESTAMPTZ DEFAULT now(),
    verdict       TEXT,
    reviewed_at   TIMESTAMPTZ,
    PRIMARY KEY (candidate_id, review)
);
CREATE INDEX IF NOT EXISTS review_verdict_idx ON review_items (verdict) WHERE verdict IS NOT NULL;
