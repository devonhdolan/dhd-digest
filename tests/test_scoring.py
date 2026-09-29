from dhd_digest.corpus.embed import candidate_text, strip_raise_boilerplate
from dhd_digest.triage.score import final_score
from dhd_digest.validation import validate_triage_judgment


def judgment(fit, resemblance):
    return validate_triage_judgment({"section": "Tech", "fit": fit, "keep_score": resemblance,
                                     "blurb": "x", "reasoning": "y"})


def test_final_score_is_resemblance_plus_boost():
    assert final_score(judgment(fit=2, resemblance=9), n_sources=1) == 9.0
    assert final_score(judgment(fit=9, resemblance=6), n_sources=3) == 7.5
    assert final_score(judgment(fit=10, resemblance=10), n_sources=5) == 10.0


def test_pool_gates_on_fit_and_resemblance_separately():
    from dhd_digest.editor.assemble import select_pool

    def item(i, fit, score, url="https://variety.com/2026/x"):
        return {"id": i, "fit": fit, "keep_score": score, "domain": f"d{i}.com",
                "canonical_url": url + str(i)}

    items = [item(1, fit=2, score=10),   # well-shaped, off the beat
             item(2, fit=7, score=6),    # on the beat, resemblance at the bar
             item(3, fit=9, score=5),    # on the beat, below resemblance bar
             item(4, fit=8, score=9),
             item(5, fit=8, score=9, url="https://spyglass.org/r/1af18231?m=")]  # tracker
    assert [it["id"] for it in select_pool(items, {}, 10)] == [4, 2]
    # min_fit=None: scores from before fit existed
    assert [it["id"] for it in select_pool(items, {}, 10, min_fit=None)] == [1, 4, 2]


def test_fit_is_required():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        validate_triage_judgment({"section": "Tech", "keep_score": 8,
                                  "blurb": "x", "reasoning": "y"})


def test_strips_funding_boilerplate_but_keeps_the_subject():
    s = strip_raise_boilerplate(
        "Topdog raises $2.5 million seed financing to scale real-time multiplayer gaming")
    assert "raises" not in s and "2.5" not in s and "seed" not in s
    assert "Topdog" in s and "multiplayer gaming" in s
    s = strip_raise_boilerplate("Rightway, pharmacy benefits manager, raised $155m Series E led by X")
    assert s.startswith("Rightway, pharmacy benefits manager")
    assert "Series E" not in s and "led by" not in s
    assert strip_raise_boilerplate("Wealthcome raises €15m Series B") == "Wealthcome"


def test_candidate_text_keeps_domain():
    t = candidate_text({"headline": "Maykit raises $4m for social music creation",
                        "excerpt": "", "domain": "techcrunch.com"})
    assert t == "Maykit for social music creation (techcrunch.com)"


def test_embed_batches_stay_under_the_token_limit():
    from dhd_digest.corpus.embed import _BATCH_TOKENS, batches, estimate_tokens
    texts = ["x" * 400] * 300                      # ~134 estimated tokens each
    bs = batches(texts)
    assert sum(len(b) for b in bs) == 300
    assert all(sum(estimate_tokens(t) for t in b) <= _BATCH_TOKENS for b in bs)
    assert len(batches(["short"] * 300)) == 3      # still capped at 128 texts
    assert batches([]) == []
