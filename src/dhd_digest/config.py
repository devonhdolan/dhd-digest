"""Central configuration. Everything tunable lives here."""
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
VOYAGE_API_KEY = os.environ.get("VOYAGE_API_KEY", "")

# Models
EMBED_MODEL = "voyage-3"
EMBED_DIM = 1024
TRIAGE_MODEL = "claude-haiku-4-5-20251001"   # cheap, high volume
EDITOR_MODEL = "claude-sonnet-5"             # one call per section

SECTIONS = ["Tech", "Media", "Entertainment", "Collaborative"]

# Measured from issues 1-250 (n=29,928). The mix held within ~3pts every year.
SECTION_MIX = {
    "Collaborative": 0.371,
    "Tech": 0.225,
    "Entertainment": 0.206,
    "Media": 0.197,
}

# Measured blurb lengths: median 8 words, p90 12, p99 17.
BLURB_MAX_WORDS = 12
BLURB_MAX_WORDS_BY_SECTION = {
    "Tech": 12, "Media": 12, "Entertainment": 14, "Collaborative": 11,
}

TARGET_LINKS_PER_ISSUE = 150
MIN_KEEP_SCORE = 6
NEIGHBORS_PER_SECTION = 20

# Boost for links that showed up in more than one source that week.
CONVERGENCE_BOOST = 0.75
