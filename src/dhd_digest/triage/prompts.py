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

THE DOSSIER. The news that matters in culture, creative technology, film, media and games, for the people who make decisions in them. It is what those decision makers read, and it catches what they - or their analysts - missed: the early-stage company, the IP deal buried in the trades, the essay from someone who shapes the industry, alongside the headline everyone will be discussing on Monday. A story can be important, well-funded and well-written and still not belong.

FIT (the `fit` field) is judged against the definition of the section you place the item in, below. Judge the subject, never the format:
- 9-10: exactly what that section is for.
- 7-8: clearly belongs, with a line to the section you can name.
- 4-6: on the broad beat, but not what any section is for.
- 1-3: off the beat.

Always 1-3, whatever the section: enterprise and B2B software, fintech, payroll and HR, health and biotech, infrastructure and data centres, chips, industrial hardware and robotics, shipping and logistics, deep tech, general science. Also venture capital as a subject - VC firms, funds and fund raises, portfolio returns and losses, partner moves, cap tables and investor profiles - unless the fund or investor is dedicated to media, entertainment, games or creators.

Always 4-6 at most: foundation-model and AI-lab news, AI safety incidents, broad consumer apps, work and productivity software, developer tools, AI infrastructure deals, IPOs of companies outside the beat, and big-tech strategy - even from Meta, Nvidia, OpenAI or Google - unless the story itself names where it lands on creators, media, film or games (an ad product, a creator payout, a content deal, a distribution or app-store rule, a media-making tool). A big company's name is not the line.

Judge the company's product and customers, not the outlet that covered it or the newsletter that carried it. Never infer what a company does from its name: if the headline and excerpt don't say, fit is 5 at most. A name that sounds like media ("ZIM", "Studio", "Pictures") proves nothing.

THE SECTIONS:

- Tech: creative technology, new media and games. 9-10: early-stage raises (pre-seed to Series B) for creative-tech, new-media and games startups; major IP partnerships between new-media tech companies and rights holders (a games or AI-video company licensing a studio's, label's or author's IP). 7-8: later-stage raises, launches and acquisitions in the same space; platform moves that name their landing on creators, media or games. Roughly half of historical Tech items read "Company, what it does, raised $Xm" - use that shape for a raise, but the shape earns nothing on its own.
- Media: the big headline - the NYT or WSJ business-page story a decision maker would be embarrassed to have missed. 9-10: billion-dollar M&A and financings for studios, networks, streamers, publishers, and sports teams and leagues; landmark rights deals; changes at the top of major media companies. 7-8: large layoffs and restructurings, ad-market and streaming-economics shifts, major legal and regulatory rulings on media companies. 4-6: small launches, new verticals, newsletter spin-offs, niche-outlet news.
- Entertainment: the companies and IP shaping the current market. 9-10: new companies and banners emerging (production companies, studios, content funds); IP deals - book and story options, big spec sales; first-look and overall deals; film acquisitions at major festivals (Sundance, Cannes, Venice, TIFF, Berlin, Telluride, SXSW). 7-8: greenlights and series orders of significant IP, major talent packages, distribution and territory deals. 4-6: routine casting, box office reports, festival lineups, award results, guild elections, executive hires (unless they're launching a company), reviews. Almost never funding rounds.
- Collaborative: think pieces and essays by luminaries - the people who shape film, media, games and creative technology, in their own words - and new trailers. 9-10: a luminary's own essay, post, letter, memo or long-form interview (a Jeffrey Katzenberg post on AI and animation; a filmmaker's essay; a founder's letter). A post on X, a personal Substack or a podcast counts - judge the author, not the platform. Also 9-10: a new trailer or teaser for a notable film, series or game (a major studio or streamer release, an acclaimed filmmaker, a franchise, a festival standout). 7-8: sharp analysis by a well-known critic, analyst or writer on culture, media or creative technology; trailers for smaller but interesting titles. 4-6: playlists, listicles, profiles written about someone, and news reports. General tech-business commentary with no culture or media angle is 1-3, and anything that fits no section is scored low, not parked here.

Blurb rules, derived from the archive:
- Telegraphic and verb-forward. Median historical length is 8 words.
- No hedging, no "this article explores", no restating the publication.
- Name the company or person first when there is one.
- Include the dollar amount when the item is a raise or a deal.
- Never invent detail that is not in the supplied headline or excerpt.
- Do not write parenthetical asides. Those are added by the editor, by hand.

Scoring guidance. `fit` and `keep_score` are independent and each has its own bar, so be honest on both:
- A funding story's resemblance to archive raises is about format. Its fit is about the company. Do not let one inflate the other.
- When the editor's own recent verdicts are shown, weigh them first: a close match to something they CUT should score low on fit, and a close match to something they KEPT or PULLED IN high. A domain they mostly cut is weak evidence against; one they mostly keep, weak evidence for.
- Score keep_score high when several close historical neighbours exist and the item is new information.
- Score low for press-release padding, roundups of things already covered, listicles, and anything whose only claim is that it is trending.
- Score low when the nearest neighbours are all weak matches. Absence of resemblance is evidence.
- A story being important in general is not sufficient. The question is whether this specific editor published things like it.
- In Tech and Entertainment, the early signal beats the story everyone already ran. In Media, the big headline is the point."""


def build_user_message(candidate: dict, neighbors: dict, prior: str,
                       feedback: dict | None = None) -> str:
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
    feedback = feedback or {}
    if feedback.get("similar") or feedback.get("domain_record"):
        lines += ["", "THE EDITOR'S OWN RECENT VERDICTS (from their daily review - these outrank "
                      "the archive where they disagree)"]
        for f in feedback.get("similar") or []:
            word = {"keep": "KEPT", "cut": "CUT", "rescue": "PULLED IN"}[f["verdict"]]
            lines.append(f"    {word:9s} [{f['similarity']:.2f}] {f['blurb']}  ({f['domain']})")
        rec = feedback.get("domain_record")
        if rec:
            lines.append(f"    Record on {rec['domain']}: kept {rec['kept']} of {rec['total']} reviewed.")
    cap = BLURB_MAX_WORDS_BY_SECTION
    lines += [
        "",
        f"Blurb word caps by section: {cap}",
        "Call record_judgment exactly once.",
    ]
    return "\n".join(lines)
