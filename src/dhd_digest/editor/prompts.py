"""Section editor prompt. One call per section, with real archive lines as style."""

SECTION_BRIEFS = {
    "Tech": "Creative technology, new media and games: early-stage raises (pre-seed to Series B) and major IP partnerships between new-media tech companies and rights holders lead. Funding-round shaped: 'Company, what it does, raised $Xm'. Prefer the early signal over the story everyone ran.",
    "Media": "The big headline: the NYT/WSJ business-page story a decision maker can't miss. Billion-dollar M&A and financings for studios, networks, streamers, publishers and sports teams lead; then landmark rights deals, changes at the top, major restructurings and rulings. Company-level, not title-level.",
    "Entertainment": "The companies and IP shaping the market: new companies and banners, book and story options, big spec sales, first-look and overall deals, and film acquisitions at major festivals lead; then greenlights of significant IP and major packages. Name the project, the buyer or talent, and the deal. Routine casting, box office and award results go last or not at all.",
    "Collaborative": "Think pieces and essays by luminaries - people who shape film, media, games and creative tech, in their own words (a Katzenberg post, a filmmaker's essay, a founder's letter) - and new trailers for notable films, series and games; then sharp analysis by well-known writers. Name the author first, or the title for a trailer ('Dune: Part Three' teaser). Not a catch-all.",
}

SYSTEM = """You are the section editor for one section of a weekly link digest. You are given the links that survived triage and thirty real lines from the 250-issue archive as style reference.

Produce the final ordered list for your section.

Rules:
- Match the archive voice exactly. Telegraphic, verb-forward, median 8 words.
- Order by interest, not by score. Lead with the item a reader would stop on.
- Group naturally: related items adjacent, funding runs together, award and list items at the end.
- Cut anything redundant with another item in the list. Say so in `dropped`.
- Cut anything off the dossier's beat - culture, creative technology, film, media and games, as defined in the section brief - however well it scored.
- Never write parenthetical asides. The editor adds those by hand.
- Never add a source tag like [TC] or [SVC]. The renderer adds the link.
- Do not invent facts. If a blurb overclaims relative to its headline, tighten it.
- Items marked PICK were chosen by the editor. Always include every one, whatever you think of it; you may only edit its blurb and choose its position. They count toward the maximum.
- The count is a ceiling, not a target. Return up to that many items; a thin week gets a short section. Never include an item just to reach the count."""


def build_user_message(section, items, examples, target_count):
    lines = [f"SECTION: {section}", SECTION_BRIEFS[section], "",
             f"MAXIMUM COUNT: {target_count}", "",
             "STYLE REFERENCE (real lines from the archive):"]
    for e in examples:
        lines.append(f"  {e['blurb']}")
    lines += ["", "CANDIDATES (id | score | blurb | domain):"]
    for it in items:
        score = "PICK" if it.get("pinned") else f"{it['keep_score']:.1f}"
        lines.append(f"  {it['id']} | {score} | {it['blurb']} | {it['domain']}")
    lines += ["", "Call build_section once."]
    return "\n".join(lines)


SECTION_TOOL = {
    "name": "build_section",
    "description": "Return the final ordered items for this section.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "blurb": {"type": "string",
                                  "description": "Final blurb, edited to house voice."},
                    },
                    "required": ["id", "blurb"],
                },
            },
            "dropped": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Candidate ids cut as redundant or weak.",
            },
        },
        "required": ["items"],
    },
}
