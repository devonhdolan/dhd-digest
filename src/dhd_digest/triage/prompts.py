"""Triage prompt and tool-use schema.

The model never sees a keyword list. It sees the candidate plus real examples
of what was kept in each section, and decides by resemblance.
"""
from ..config import BLURB_MAX_WORDS_BY_SECTION

TRIAGE_TOOL = {
    "name": "record_judgment",
    "description": "Record the curation decision for one candidate link.",
    "input_schema": {
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "enum": ["Tech", "Media", "Entertainment", "Collaborative"],
                "description": "Which section this belongs in, if kept.",
            },
            "keep_score": {
                "type": "integer", "minimum": 1, "maximum": 10,
                "description": (
                    "10 = certain include, 1 = certain drop. Score against the "
                    "supplied historical examples, not against general interest."
                ),
            },
            "blurb": {
                "type": "string",
                "description": (
                    "House-style one-liner. No trailing period unless the "
                    "archive examples use one. No source name - that is tagged "
                    "separately."
                ),
            },
            "reasoning": {
                "type": "string",
                "description": "One sentence. Which historical items it resembles, or why not.",
            },
        },
        "required": ["section", "keep_score", "blurb", "reasoning"],
    },
}

SYSTEM = """You are the triage editor for a weekly link digest that ran for 250 issues between 2017 and 2022. Your only job is to decide whether a link belongs in the next issue, in which section, and to write the one-line blurb.

The four sections behave differently, and you must respect the difference:

- Tech: startup and platform news, heavily fundraise-shaped. Roughly half of all historical Tech items follow the pattern "Company, what it does, raised $Xm". Match that shape whenever the item is a funding story.
- Media: the business of media and sport. Carriage deals, rights, ad markets, layoffs, valuations, streaming economics. Company-level, not title-level.
- Entertainment: trade dealflow. Talent attachments, IP options, greenlights, acquisitions, festival and award lists. Almost never funding rounds.
- Collaborative: essays, reports, profiles, trailers, papers, playlists, and anything that is interesting rather than transactional. The loosest section and the largest.

Blurb rules, derived from the archive:
- Telegraphic and verb-forward. Median historical length is 8 words.
- No hedging, no "this article explores", no restating the publication.
- Name the company or person first when there is one.
- Include the dollar amount when the item is a raise or a deal.
- Never invent detail that is not in the supplied headline or excerpt.
- Do not write parenthetical asides. Those are added by the editor, by hand.

Scoring guidance:
- Score high when several close historical neighbours exist and the item is new information.
- Score low for press-release padding, roundups of things already covered, listicles, and anything whose only claim is that it is trending.
- Score low when the nearest neighbours are all weak matches. Absence of resemblance is evidence.
- A story being important in general is not sufficient. The question is whether this specific editor published things like it."""


def build_user_message(candidate: dict, neighbors: dict, prior: str) -> str:
    lines = [
        "CANDIDATE",
        f"  headline: {candidate.get('headline') or candidate.get('anchor_text')}",
        f"  domain:   {candidate['domain']}",
        f"  excerpt:  {(candidate.get('excerpt') or '')[:600]}",
        f"  carried by: {', '.join(candidate.get('sources') or []) or 'unknown'}",
        "",
        f"NEAREST-SECTION PRIOR: {prior}",
        "",
        "HISTORICAL NEIGHBOURS (things previously published, by section)",
    ]
    for section, items in neighbors.items():
        if not items:
            continue
        lines.append(f"\n  {section}:")
        for n in items[:8]:
            lines.append(f"    [{n['similarity']:.2f}] {n['blurb']}  ({n['domain']}, {n['date']})")
    cap = BLURB_MAX_WORDS_BY_SECTION
    lines += [
        "",
        f"Blurb word caps by section: {cap}",
        "Call record_judgment exactly once.",
    ]
    return "\n".join(lines)
