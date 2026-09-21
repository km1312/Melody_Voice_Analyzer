"""Feedback buttons on cards, wired to the store (FR-20)."""

import json
import shutil

import pytest

from revolv.gui_results import ResultsWindow
from revolv.store import Store
from test_gui_results import _valid_response


@pytest.fixture()
def run_dir(tmp_path, fixture_dir):
    for name in ("call.json", "call.analysis.json"):
        shutil.copy(fixture_dir / name, tmp_path / name)
    return tmp_path


@pytest.fixture()
def window(qapp, run_dir, fixture_report, tmp_path):
    store = Store(tmp_path / "melody.db")
    win = ResultsWindow(run_dir, "call", store=store)
    win.import_edit.setPlainText(_valid_response(fixture_report))
    win._import_pasted()
    yield win, store
    win.close()
    store.close()


def test_cards_have_the_three_buttons(window):
    win, _store = window
    card = win.cards[0]
    assert set(card.feedback_buttons) == {"useful", "not_useful",
                                          "bad_evidence"}


def test_useful_click_records_and_second_click_undoes(window):
    win, store = window
    from revolv.gui_feedback import _call_id

    card = win.cards[0]
    call_id = _call_id(win.data)
    card.feedback_buttons["useful"].click()
    assert store.feedback_for(call_id)[card.insight["key"]] == \
        ("useful", None)
    card.feedback_buttons["useful"].click()
    assert card.insight["key"] not in store.feedback_for(call_id)


def test_import_records_insight_meta(window):
    win, store = window
    from revolv.gui_feedback import _call_id

    call_id = _call_id(win.data)
    rows = store.db.execute(
        "SELECT layer, channels FROM insight_meta WHERE call_id=?",
        (call_id,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["layer"] == "unsaid"
    assert "lexical" in rows[0]["channels"]
    # The store holds no words from the call.
    dump = "\n".join(str(dict(r)) for r in store.db.execute(
        "SELECT * FROM insight_meta").fetchall())
    assert "worth checking" not in dump


def test_outcome_dialog_answers(qapp):
    from revolv.gui_feedback import OutcomeDialog

    dialog = OutcomeDialog("A claim.")
    dialog._pick("unknown")
    assert dialog.answer == "unknown"
