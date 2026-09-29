import psycopg
import pytest

import dhd_digest.db.client as db


class FakeConn:
    def __init__(self, fail=False):
        self.fail, self.closed, self.broken = fail, False, False


def test_reconnects_once_after_a_dropped_connection(monkeypatch):
    used = []

    def fake_conn():                      # like db.conn(): open one if there isn't one
        if db._conn is None:
            db._conn = FakeConn()
        return db._conn

    monkeypatch.setattr(db, "_conn", FakeConn(fail=True))
    monkeypatch.setattr(db, "conn", fake_conn)

    @db._reconnecting
    def op():
        c = db.conn()
        used.append(c)
        if c.fail:
            c.broken = True               # what psycopg reports after a dropped link
            raise psycopg.OperationalError("the connection is lost")
        return "ok"

    assert op() == "ok"
    assert len(used) == 2 and used[0] is not used[1]


def test_a_real_error_on_a_healthy_connection_is_not_retried(monkeypatch):
    monkeypatch.setattr(db, "_conn", FakeConn())

    @db._reconnecting
    def op():
        raise psycopg.OperationalError("syntax-ish problem")

    with pytest.raises(psycopg.OperationalError):
        op()


def test_scoring_runs_in_chunks(monkeypatch):
    import dhd_digest.triage.score as score
    embedded = []
    monkeypatch.setattr(score, "CHUNK", 3)
    monkeypatch.setattr(score, "embed", lambda texts, input_type: embedded.append(len(texts)) or [[0.0]] * len(texts))
    monkeypatch.setattr(score, "neighbors_by_section", lambda v: {})
    monkeypatch.setattr(score, "editor_feedback", lambda v, d: {})
    monkeypatch.setattr(score, "judge", lambda *a: score.validate_triage_judgment(
        {"section": "Tech", "fit": 8, "keep_score": 7, "blurb": "b", "reasoning": "r"}))
    cands = [{"id": i, "canonical_url": f"https://x.com/{i}", "domain": "x.com",
              "headline": "h", "excerpt": "", "sources": []} for i in range(7)]
    out = list(score.score_candidates(cands, workers=2))
    assert embedded == [3, 3, 1]
    assert [c["id"] for c, *_ in out] == list(range(7))
