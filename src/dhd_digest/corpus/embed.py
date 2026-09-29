"""Embedding helpers. Anthropic doesn't serve embeddings, so this uses Voyage."""
import re
import time

import voyageai
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import EMBED_MODEL, VOYAGE_API_KEY

_client = None

# Voyage's free tier (no payment method on file) caps requests at 3/min.
# Space calls out so we ride under that instead of erroring into it.
_RPM_LIMIT = 3
_call_times: list[float] = []


def client():
    global _client
    if _client is None:
        _client = voyageai.Client(api_key=VOYAGE_API_KEY)
    return _client


def _throttle():
    now = time.monotonic()
    while _call_times and now - _call_times[0] > 60:
        _call_times.pop(0)
    if len(_call_times) >= _RPM_LIMIT:
        time.sleep(60 - (now - _call_times[0]) + 0.5)
    _call_times.append(time.monotonic())


@retry(stop=stop_after_attempt(5), wait=wait_exponential(min=1, max=30))
def embed(texts: list[str], input_type: str = "document") -> list[list[float]]:
    out = []
    for i in range(0, len(texts), 128):
        batch = texts[i:i + 128]
        _throttle()
        r = client().embed(batch, model=EMBED_MODEL, input_type=input_type)
        out.extend(r.embeddings)
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
