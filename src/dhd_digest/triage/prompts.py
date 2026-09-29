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
            "fit": {
                "type": "integer", "minimum": 1, "maximum": 10,
                "description": (
                    "Subject fit with the digest's beat, per the FIT rubric. "
                    "Judge what the story is about, never its format."
                ),
            },
            "keep_score": {
                "type": "integer", "minimum": 1, "maximum": 10,
                "description": (
                    "Resemblance: 10 = the editor clearly published things like "
                    "this, 1 = nothing like it. Score against the supplied "
                    "historical examples, not against general interest."
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
        "required": ["section", "fit", "keep_score", "blurb", "reasoning"],
    },
}

SYSTEM = """You are the triage editor for a weekly link digest that ran for 250 issues between 2017 and 2022. Your only job is to decide whether a link belongs in the next issue, in which section, and to write the one-line blurb.

THE BEAT. The digest covers the creative and media industries - film, TV, music, games, publishing, news, sport, creators, advertising - and the technology and money reshaping them. Every section is read through that lens. A story can be important, well-funded and well-written and still be off-beat.

FIT rubric (the `fit` field). Judge the subject, never the format:
- 9-10: squarely on the beat. The company, person or story is in, or sells into, a creative or media industry: a music-rights startup, a studio deal, a streamer's ad tier, a creator-tools raise, a games platform, a sports-media rights fight.
- 7-8: adjacent with a clear line to the beat: consumer social platforms, devices and AI that directly change how culture and media are made or consumed; platform moves by Apple, Google, Meta, Amazon, Netflix, Spotify, TikTok that land on media, creators or distribution.
- 4-6: general tech with a thin line to the beat: foundation-model news, broad consumer apps, big-tech strategy with no media angle.
- 1-3: off the beat: enterprise and B2B software, fintech, payroll and HR, health and biotech, infrastructure and data centres, chips, industrial hardware and robotics, deep tech, general science, general VC and fund news.

Judge the company's product and customers, not the outlet that covered it or the newsletter that carried it. A payroll company's growth story is off the beat even in a creator-economy newsletter; a robotics startup is off the beat unless its robots make or perform media.

The four sections behave differently, and you must respect the difference:

- Tech: startups and platforms building for, or disrupting, the creative and media industries. Heavily fundraise-shaped: roughly half of historical Tech items read "Company, what it does, raised $Xm". Use that shape for a funding story, but the shape earns nothing on its own - a raise for a company off the beat gets a low fit.
- Media: the business of media and sport. Carriage deals, rights, ad markets, layoffs, valuations, streaming economics. Company-level, not title-level.
- Entertainment: trade dealflow. Talent attachments, IP options, greenlights, acquisitions, festival and award lists. Almost never funding rounds.
- Collaborative: essays, profiles, interviews, trailers, research and playlists about creativity, media, entertainment and culture, and the technology changing them. Interesting rather than transactional. It is not a catch-all: general tech-business or strategy commentary with no media or culture angle gets a low fit, and anything that fits no section should be scored low, not parked here.

Blurb rules, derived from the archive:
- Telegraphic and verb-forward. Median historical length is 8 words.
- No hedging, no "this article explores", no restating the publication.
- Name the company or person first when there is one.
- Include the dollar amount when the item is a raise or a deal.
- Never invent detail that is not in the supplied headline or excerpt.
- Do not write parenthetical asides. Those are added by the editor, by hand.

Scoring guidance. `fit` and `keep_score` are independent and each has its own bar, so be honest on both:
- A funding story's resemblance to archive raises is about format. Its fit is about the company. Do not let one inflate the other.
- Score keep_score high when several close historical neighbours exist and the item is new information.
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
