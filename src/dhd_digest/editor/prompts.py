"""Section editor prompt. One call per section, with real archive lines as style."""

SECTION_BRIEFS = {
    "Tech": "Startup and platform news. Funding-round shaped: 'Company, what it does, raised $Xm'. About half of historical items are raises.",
    "Media": "The business of media and sport: rights, carriage, ad markets, valuations, layoffs, streaming economics.",
    "Entertainment": "Trade dealflow: attachments, options, greenlights, acquisitions, festival and award lists. Rarely funding.",
    "Collaborative": "Essays, reports, profiles, papers, trailers, playlists. Interesting rather than transactional. The largest and loosest section.",
}

SYSTEM = """You are the section editor for one section of a weekly link digest. You are given the links that survived triage and thirty real lines from the 250-issue archive as style reference.

Produce the final ordered list for your section.

Rules:
- Match the archive voice exactly. Telegraphic, verb-forward, median 8 words.
- Order by interest, not by score. Lead with the item a reader would stop on.
- Group naturally: related items adjacent, funding runs together, award and list items at the end.
- Cut anything redundant with another item in the list. Say so in `dropped`.
- Never write parenthetical asides. The editor adds those by hand.
- Do not invent facts. If a blurb overclaims relative to its headline, tighten it.
- Return exactly the number of items requested, unless fewer survive the cut."""


def build_user_message(section, items, examples, target_count):
    lines = [f"SECTION: {section}", SECTION_BRIEFS[section], "",
             f"TARGET COUNT: {target_count}", "",
             "STYLE REFERENCE (real lines from the archive):"]
    for e in examples:
        lines.append(f"  {e['blurb']}  [{e['tag']}]")
    lines += ["", "CANDIDATES (id | score | blurb | domain):"]
    for it in items:
        lines.append(f"  {it['id']} | {it['keep_score']:.1f} | {it['blurb']} | {it['domain']}")
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
