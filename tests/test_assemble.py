from dhd_digest.editor.assemble import cap_per_domain
from dhd_digest.validation import validate_section_selection


def test_cap_per_domain_keeps_best_first_and_fills_from_others():
    items = ([{"id": i, "domain": "spyglass.org"} for i in range(10)]
             + [{"id": 100 + i, "domain": "deadline.com"} for i in range(10)]
             + [{"id": 200, "domain": "thespl.it"}])
    out = cap_per_domain(items, {"deadline.com": 8}, limit=20)
    ids = [it["id"] for it in out]
    assert ids[:3] == [0, 1, 2]                    # default cap of 3 for unknown domain
    assert sum(it["domain"] == "deadline.com" for it in out) == 8
    assert ids[-1] == 200
    assert len(cap_per_domain(items, {}, limit=4)) == 4


def test_strips_copied_source_tags_from_blurbs():
    raw = {"items": [{"id": 1, "blurb": "50skills, HR automation, raised $6m.  [SVC]"},
                     {"id": 2, "blurb": "Paramount buys [redacted] studio."}]}
    out = validate_section_selection(raw, pool_ids={1, 2}, target=2)
    assert out[0].blurb == "50skills, HR automation, raised $6m."
    assert out[1].blurb == "Paramount buys [redacted] studio."
