"""The local store: feedback, outcomes, self labels, baseline, export."""

import csv
import datetime

import pytest

from revolv.store import (EXPORT_COLUMNS, Store, call_id_for)


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "melody.db")
    yield s
    s.close()


DOCUMENT = {
    "run": {"run_id": "r1", "provider": "manual", "model": "m",
            "prompt_version": "p1.0.0"},
    "insights": [
        {"key": "k1", "layer": "unsaid", "channels": ["lexical", "timing"],
         "likelihood": "likely", "evidence_confidence": "low",
         "claim": "the secret claim text"},
        {"key": "k2", "layer": "relational", "channels": ["interaction",
                                                          "lexical"],
         "likelihood": "roughly even chance", "evidence_confidence":
         "moderate", "claim": "another secret"},
    ],
}


def test_call_id_is_stable_for_missing_files(tmp_path):
    a = call_id_for(tmp_path / "gone.mp4")
    b = call_id_for(tmp_path / "gone.mp4")
    assert a == b and len(a) == 40


def test_feedback_one_click_and_undo(store):
    store.record_call("c1")
    store.add_feedback("k1", "c1", "r1", "useful")
    assert store.feedback_for("c1")["k1"] == ("useful", None)
    store.add_feedback("k1", "c1", "r1", "bad_evidence", "wrong_quote")
    assert store.feedback_for("c1")["k1"] == ("bad_evidence", "wrong_quote")
    store.undo_feedback("k1", "c1")
    assert "k1" not in store.feedback_for("c1")


def test_feedback_enums_are_enforced(store):
    with pytest.raises(ValueError):
        store.add_feedback("k1", "c1", "r1", "amazing")
    with pytest.raises(ValueError):
        store.add_feedback("k1", "c1", "r1", "bad_evidence", "because")


def test_outcome_flow_asks_once_a_week(store):
    now = datetime.datetime.now()
    store.record_call("c1")
    # Backdate the call so it comes of age.
    store.db.execute("UPDATE calls SET first_seen=? WHERE call_id='c1'",
                     ((now - datetime.timedelta(days=8))
                      .isoformat(timespec="seconds"),))
    store.record_insights(DOCUMENT, "c1")

    due = store.pending_outcomes(now=now)
    assert {d["insight_key"] for d in due} == {"k1", "k2"}

    store.mark_asked("k1", "c1", now=now)
    due = store.pending_outcomes(now=now)
    assert {d["insight_key"] for d in due} == {"k2"}

    # A week later it becomes askable again, until answered.
    later = now + datetime.timedelta(days=8)
    assert {d["insight_key"] for d in store.pending_outcomes(now=later)} == \
        {"k1", "k2"}
    store.answer_outcome("k1", "c1", "yes")
    assert {d["insight_key"] for d in store.pending_outcomes(now=later)} == \
        {"k2"}


def test_fresh_calls_are_not_due_unless_named(store):
    store.record_call("c1")
    store.record_insights(DOCUMENT, "c1")
    assert store.pending_outcomes() == []
    # The same-person trigger names the call explicitly.
    due = store.pending_outcomes(call_ids={"c1"})
    assert len(due) == 2


def test_self_labels(store):
    store.add_self_label("c1", "T029", "yes")
    store.add_self_label("c1", "T029", "not_sure")  # replaces
    assert store.self_labels_for("c1") == {"T029": "not_sure"}
    with pytest.raises(ValueError):
        store.add_self_label("c1", "T001", "maybe")


def test_me_baseline_is_numbers_only(store):
    store.add_me_baseline("c1", "2026-09-01",
                          {"hedges_per_100w": 2.5, "pace": 180.0}, 12.0)
    with pytest.raises(ValueError):
        store.add_me_baseline("c2", "2026-09-02",
                              {"note": "spoke about the merger"}, 5.0)
    rows = store.me_baseline_rows()
    assert len(rows) == 1
    assert rows[0]["features"]["hedges_per_100w"] == 2.5
    store.reset_me_baseline()
    assert store.me_baseline_rows() == []


def test_export_is_content_free(store, tmp_path):
    store.record_call("c1")
    store.record_insights(DOCUMENT, "c1")
    store.add_feedback("k1", "c1", "r1", "useful")
    store.answer_outcome("k2", "c1", "no")
    out = store.export_csv(tmp_path / "export.csv")
    with open(out, encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == EXPORT_COLUMNS
    body = "\n".join(",".join(r) for r in rows)
    assert "secret" not in body
    assert "claim" not in body
    assert any("useful" in r for r in rows[1:])
    assert any("no" in r for r in rows[1:])


def test_delete_call_clears_every_table(store):
    store.record_call("c1")
    store.record_insights(DOCUMENT, "c1")
    store.add_feedback("k1", "c1", "r1", "useful")
    store.add_self_label("c1", "T001", "yes")
    store.add_me_baseline("c1", "2026-09-01", {"pace": 180.0}, 10.0)
    store.answer_outcome("k1", "c1", "yes")
    store.delete_call("c1")
    for table in ("calls", "insight_feedback", "outcomes", "self_labels",
                  "me_baseline", "insight_meta"):
        rows = store.db.execute(
            "SELECT * FROM {0}".format(table)).fetchall()
        assert rows == [], table
