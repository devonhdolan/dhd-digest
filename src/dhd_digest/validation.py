"""Validate LLM tool-call output before it touches the database.

Anthropic's forced tool_choice plus a JSON schema make malformed output
unlikely, not impossible - a hallucinated id, an out-of-range score, or a
blurb that ignores every instruction can still come back. Validate once,
here, instead of trusting every call site to notice.
"""
from pydantic import BaseModel, Field, field_validator

from .config import SECTIONS

# Generous sanity cap, well above any section's real house-style limit
# (11-14 words). This is about catching broken output - a paragraph, a
# runaway explanation - not enforcing house style; BLURB_MAX_WORDS_BY_SECTION
# trimming handles the normal "a couple words over" case elsewhere.
MAX_BLURB_WORDS = 30


class TriageJudgment(BaseModel):
    section: str
    keep_score: int = Field(ge=1, le=10)
    blurb: str = Field(min_length=1)
    reasoning: str = Field(min_length=1)

    @field_validator("section")
    @classmethod
    def section_is_known(cls, v: str) -> str:
        if v not in SECTIONS:
            raise ValueError(f"unknown section {v!r}, expected one of {SECTIONS}")
        return v

    @field_validator("blurb")
    @classmethod
    def blurb_not_absurd(cls, v: str) -> str:
        if len(v.split()) > MAX_BLURB_WORDS:
            raise ValueError(f"blurb is {len(v.split())} words - way past any house-style cap")
        return v


def validate_triage_judgment(raw: dict) -> TriageJudgment:
    """Raises pydantic.ValidationError on malformed triage output."""
    return TriageJudgment.model_validate(raw)


class SectionItem(BaseModel):
    id: int
    blurb: str = Field(min_length=1)


class SectionSelection(BaseModel):
    items: list[SectionItem]
    dropped: list[int] = Field(default_factory=list)


def validate_section_selection(raw: dict, pool_ids: set[int], target: int) -> list[SectionItem]:
    """Parse the section editor's tool call, then drop anything a
    well-behaved model shouldn't have sent: ids outside the offered pool,
    duplicate ids, blurbs that blew past any reasonable length. Never
    raises for those - degrade gracefully rather than losing a whole
    section (or the whole draft) over one bad item. A structurally broken
    response (missing `items`, wrong types) still raises ValidationError.

    First occurrence wins on a duplicate id. Returns at most `target`
    items; the model is allowed to return fewer if it decided fewer
    survive the cut, per its own instructions.
    """
    selection = SectionSelection.model_validate(raw)

    seen: set[int] = set()
    out: list[SectionItem] = []
    for item in selection.items:
        if item.id not in pool_ids:
            print(f"    drop: id {item.id} not in offered candidate pool")
            continue
        if item.id in seen:
            print(f"    drop: duplicate id {item.id}")
            continue
        if len(item.blurb.split()) > MAX_BLURB_WORDS:
            print(f"    drop: id {item.id} blurb is {len(item.blurb.split())} words, way over cap")
            continue
        seen.add(item.id)
        out.append(item)

    if len(out) > target:
        print(f"    note: model returned {len(out)} items, requested {target} - truncating")
        out = out[:target]
    elif len(out) < target:
        print(f"    note: model returned {len(out)} of {target} requested")

    return out
