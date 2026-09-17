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
