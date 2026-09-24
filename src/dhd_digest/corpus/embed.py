"""Embedding helpers. Anthropic doesn't serve embeddings, so this uses Voyage."""
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


def candidate_text(row: dict) -> str:
    """Same shape for a new link, so the vectors are comparable."""
    head = row.get("headline") or row.get("anchor_text") or ""
    excerpt = (row.get("excerpt") or "")[:300]
    return f"{head} {excerpt} ({row['domain']})".strip()
