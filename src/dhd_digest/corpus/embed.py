"""Embedding helpers. Anthropic doesn't serve embeddings, so this uses Voyage."""
import re
import time

import voyageai
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import EMBED_MODEL, VOYAGE_API_KEY

_client = None

# Voyage's free tier (no payment method on file) caps requests at 3/min AND
# tokens at 10K/min. Space calls out so we ride under both instead of erroring
# into them. A full 128-text batch of candidates is ~13K tokens on its own, so
# batches are also sized by tokens.
_RPM_LIMIT = 3
_TPM_LIMIT = 10_000
_BATCH_TOKENS = 8_000
_BATCH_TEXTS = 128
_calls: list[tuple[float, int]] = []   # (monotonic time, estimated tokens)


def client():
    global _client
    if _client is None:
        _client = voyageai.Client(api_key=VOYAGE_API_KEY)
    return _client


def estimate_tokens(text: str) -> int:
    """Deliberately high (~3 chars/token) so the throttle errs safe."""
    return len(text) // 3 + 1


def batches(texts: list[str]) -> list[list[str]]:
    out, cur, cur_tokens = [], [], 0
    for t in texts:
        n = estimate_tokens(t)
        if cur and (len(cur) == _BATCH_TEXTS or cur_tokens + n > _BATCH_TOKENS):
            out.append(cur)
            cur, cur_tokens = [], 0
        cur.append(t)
        cur_tokens += n
    if cur:
        out.append(cur)
    return out


def _throttle(tokens: int):
    tokens = min(tokens, _TPM_LIMIT)       # an oversized batch still gets its own minute
    while True:
        now = time.monotonic()
        while _calls and now - _calls[0][0] > 60:
            _calls.pop(0)
        used = sum(n for _, n in _calls)
        if len(_calls) < _RPM_LIMIT and used + tokens <= _TPM_LIMIT:
            break
        time.sleep(60 - (now - _calls[0][0]) + 0.5)
    _calls.append((time.monotonic(), tokens))


@retry(stop=stop_after_attempt(5), wait=wait_exponential(min=5, max=60))
def _embed_batch(batch: list[str], input_type: str) -> list[list[float]]:
    _throttle(sum(estimate_tokens(t) for t in batch))
    return client().embed(batch, model=EMBED_MODEL, input_type=input_type).embeddings


def embed(texts: list[str], input_type: str = "document") -> list[list[float]]:
    out = []
    for batch in batches(texts):
        out.extend(_embed_batch(batch, input_type))
    return out


def historical_text(row: dict) -> str:
    """What we embed for an archive row.

    Blurb carries the judgment, domain carries the beat, section carries the
    house it lived in. Keep it short - boilerplate dilutes the signal.
    """
    return f"[{row['section']}] {row['blurb']} ({row['domain']})"


# Funding-round boilerplate. Left in, it dominates similarity: every "X raises
# $12m Series A" sits close to thousands of archive raises whatever X does, so
# a heart-device raise looks as on-brand as a music-app raise. Stripped from
# the query, neighbours are found by what the company does.
_RAISE_BOILERPLATE = re.compile(
    r"[$€£]?\s?\d[\d.,]*\s?(?:m|mn|b|bn|k|million|billion)\b"
    r"|[$€£]\s?\d[\d.,]*"
    r"|\b(?:pre-?)?seed\b|\bseries [a-h]\+?\b|\b(?:funding|financing|investment)\s+round\b"
    r"|\b(?:raises|raised|raising|secures|secured|closes|closed|lands|landed|nabs|bags)\b"
    r"|\bled by\b|\bvaluation\b|\bvalued at\b",
    re.I)


def strip_raise_boilerplate(text: str) -> str:
    return re.sub(r"\s{2,}", " ", _RAISE_BOILERPLATE.sub(" ", text)).strip()


def candidate_text(row: dict) -> str:
    """Same shape for a new link, so the vectors are comparable - minus
    funding-round wording, so the match is on subject, not format."""
    head = row.get("headline") or row.get("anchor_text") or ""
    excerpt = (row.get("excerpt") or "")[:300]
    return strip_raise_boilerplate(f"{head} {excerpt}") + f" ({row['domain']})"
