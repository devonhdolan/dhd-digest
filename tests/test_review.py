from dhd_digest.review.daily import NEAR_MISS_MARKER, parse, render
from dhd_digest.triage.prompts import build_user_message


def item(i, section, blurb):
    return {"id": i, "section": section, "blurb": blurb, "url": f"https://x.com/{i}",
            "domain": "x.com", "fit": 8.0, "score": 7.0}


POOL = [item(1, "Tech", "Topdog, multiplayer games, raised $2.5m."),
        item(2, "Tech", "O-ID, humanoid robots, raised $1.2m."),
        item(3, "Entertainment", "Neon buys TIFF drama.")]
NEAR = [item(4, "Collaborative", "Katzenberg on AI and animation."),
        item(5, "Media", "Small newsletter launch.")]


def tick(body, i):
    return "\n".join(l.replace("- [ ]", "- [x]", 1) if f"<!-- id:{i} -->" in l else l
                     for l in body.splitlines())


def test_render_groups_by_section_and_marks_near_misses():
    body = render(POOL, NEAR)
    assert body.index("### Tech") < body.index("### Entertainment") < body.index(NEAR_MISS_MARKER)
    assert "_Collaborative_" in body.split(NEAR_MISS_MARKER)[1]
    assert body.count("- [ ]") == 5


def test_untouched_issue_keeps_the_pool_and_records_no_near_misses():
    assert parse(render(POOL, NEAR)) == {1: "keep", 2: "keep", 3: "keep"}


def test_ticks_become_cuts_and_rescues():
    body = tick(tick(render(POOL, NEAR), 2), 4)
    assert parse(body) == {1: "keep", 2: "cut", 3: "keep", 4: "rescue"}


def test_github_style_capital_x_counts():
    body = render(POOL, []).replace("- [ ] O-ID", "- [X] O-ID")
    assert parse(body)[2] == "cut"


def test_feedback_reaches_the_triage_prompt():
    msg = build_user_message(
        {"headline": "Acme robots raise $3m", "domain": "tech.eu", "excerpt": "", "sources": []},
        {}, "Tech",
        {"similar": [{"blurb": "O-ID, humanoid robots, raised $1.2m.", "domain": "tech.eu",
                      "verdict": "cut", "similarity": 0.83}],
         "domain_record": {"domain": "tech.eu", "kept": 1, "total": 9}})
    assert "THE EDITOR'S OWN RECENT VERDICTS" in msg
    assert "CUT       [0.83] O-ID" in msg
    assert "Record on tech.eu: kept 1 of 9 reviewed." in msg
    # and nothing extra when there is no feedback yet
    assert "EDITOR'S OWN" not in build_user_message(
        {"headline": "h", "domain": "d", "excerpt": "", "sources": []}, {}, "Tech")


def test_parse_published_keeps_section_and_tag(tmp_path):
    from dhd_digest.render.markdown import parse_published
    f = tmp_path / "issue-251.md"
    f.write_text("### Issue 251\n\n**Tech**\n\n"
                 "Topdog raised $2.5m. [TC](https://techcrunch.com/a) <!-- id:1 -->\n\n"
                 "**Media**\n\n"
                 "Paramount sells bonds. [WSJ](https://wsj.com/b) <!-- id:2 -->\n\n"
                 "Cut line without marker. [X](https://x.com/c)\n")
    items = parse_published(f)
    assert [(i["id"], i["section"], i["tag"]) for i in items] == [(1, "Tech", "TC"), (2, "Media", "WSJ")]
