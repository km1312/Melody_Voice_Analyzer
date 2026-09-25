"""The How you sounded tab (FR-16..19, FR-22), offscreen."""

import json
import shutil

import pytest

from revolv.gui_coaching import CoachingTab, RingWidget
from revolv.gui_results import ResultsWindow
from revolv.store import Store, call_id_for


@pytest.fixture()
def run_dir(tmp_path, fixture_dir):
    for name in ("call.json", "call.analysis.json"):
        shutil.copy(fixture_dir / name, tmp_path / name)
    return tmp_path


def _set_me(run_dir, me="SPEAKER_01"):
    context = {"schema_version": "1.0", "me": me}
    (run_dir / "call.context.json").write_text(json.dumps(context),
                                               encoding="utf-8")


def _seed_history(store, count):
    for i in range(count):
        store.add_me_baseline("past{0}".format(i),
                              "2026-08-{0:02d}".format(i + 1),
                              {"hedges_per_100w": 1.0 + i,
                               "articulation_wpm": 150.0 + i,
                               "long_pauses_per_min": 1.0,
                               "median_pitch_st": 12.0,
                               "medial_fillers_per_100w": 2.0,
                               "restarts_per_100w": 1.0,
                               "rising_close_share": 0.4}, 10.0)


def _window(qapp, run_dir, store):
    return ResultsWindow(run_dir, "call", store=store)


def test_without_me_the_tab_is_a_pointer(qapp, run_dir, tmp_path):
    store = Store(tmp_path / "m.db")
    window = _window(qapp, run_dir, store)
    tab = window.tabs.widget(window.coaching_tab_index)
    assert isinstance(tab, CoachingTab)
    assert tab.findChildren(RingWidget) == []
    window.close()
    store.close()


def test_building_at_seven_ring_at_eight(qapp, run_dir, tmp_path):
    _set_me(run_dir)
    store = Store(tmp_path / "m.db")
    _seed_history(store, 7)
    window = _window(qapp, run_dir, store)
    tab = window.tabs.widget(window.coaching_tab_index)
    assert tab.result["percentile"] is None
    assert tab.result["n"] == 7
    assert tab.findChildren(RingWidget) == []
    window.close()

    _seed_history(store, 8)  # rewrites the same 7 plus past7
    window = _window(qapp, run_dir, store)
    tab = window.tabs.widget(window.coaching_tab_index)
    assert tab.result["n"] == 8
    assert tab.result["percentile"] is not None
    assert len(tab.findChildren(RingWidget)) == 1
    window.close()
    store.close()


def test_direction_column_shows_without_history(qapp, run_dir, tmp_path):
    """Fix list #6: the Steadier-when column is filled from the static
    directions even before any past call exists."""
    _set_me(run_dir)
    store = Store(tmp_path / "m.db")
    window = _window(qapp, run_dir, store)
    tab = window.tabs.widget(window.coaching_tab_index)
    assert tab.feature_rows["hedges_per_100w"][1].text() == "lower"
    assert tab.feature_rows["articulation_wpm"][1].text() == \
        "higher, within your range"
    assert tab.feature_rows["median_reply_s"][1].text() == "reported only"
    # Values carry units now (fix #10).
    assert "wpm" in tab.feature_rows["articulation_wpm"][0].text()
    window.close()
    store.close()


def test_direction_column_appends_comparison_with_history(qapp, run_dir,
                                                          tmp_path):
    _set_me(run_dir)
    store = Store(tmp_path / "m.db")
    _seed_history(store, 8)
    window = _window(qapp, run_dir, store)
    tab = window.tabs.widget(window.coaching_tab_index)
    text = tab.feature_rows["hedges_per_100w"][1].text()
    assert text.startswith("lower")
    assert "usual" in text
    window.close()
    store.close()


def test_baseline_date_prefers_the_filename(qapp, run_dir, tmp_path):
    """Fix list #9: the row is dated by the recording, not by today."""
    _set_me(run_dir)
    store = Store(tmp_path / "m.db")
    window = _window(qapp, run_dir, store)
    tab = window.tabs.widget(window.coaching_tab_index)
    tab.data.stem = "Brian Call 2026-08-19 12-00-26"
    assert tab._call_date() == "2026-08-19"
    tab.data.stem = "call"  # no date: falls back to the .json's mtime
    import datetime

    expected = datetime.date.fromtimestamp(
        (run_dir / "call.json").stat().st_mtime).isoformat()
    assert tab._call_date() == expected
    window.close()
    store.close()


@pytest.fixture()
def brian_dir(tmp_path, fixture_dir):
    """The fixture call under a counterpart-named stem, with the counterpart
    named in context but no me set — the guessed-me preview case."""
    folder = tmp_path / "brian"
    folder.mkdir()
    shutil.copy(fixture_dir / "call.json", folder / "Brian call.json")
    shutil.copy(fixture_dir / "call.analysis.json",
                folder / "Brian call.analysis.json")
    (folder / "Brian call.context.json").write_text(json.dumps(
        {"schema_version": "1.0",
         "speaker_names": {"SPEAKER_01": "Brian"}}), encoding="utf-8")
    return folder


def test_guessed_me_previews_without_writing_history(qapp, brian_dir,
                                                     tmp_path):
    """The tab now works from the name guesses: the delivery table shows for
    the probable me, but nothing enters the baseline store and no ring or
    self labels appear until the one-click confirmation in Context."""
    from revolv.gui_coaching import RingWidget

    store = Store(tmp_path / "m.db")
    _seed_history(store, 8)  # even with a full history: preview only
    window = ResultsWindow(brian_dir, "Brian call", store=store)
    tab = window.tabs.widget(window.coaching_tab_index)
    assert tab.me == "SPEAKER_00"          # the one who is not Brian
    assert tab.me_confirmed is False
    assert hasattr(tab, "feature_rows")    # the table is live
    assert tab.findChildren(RingWidget) == []
    assert not hasattr(tab, "coach_edit")  # no model coaching in preview
    assert all(r["call_id"].startswith("past")
               for r in store.me_baseline_rows())  # nothing stored
    window.close()
    store.close()


def test_confirmed_me_still_stores(qapp, brian_dir, tmp_path):
    context = {"schema_version": "1.0", "me": "SPEAKER_00",
               "speaker_names": {"SPEAKER_01": "Brian"}}
    (brian_dir / "Brian call.context.json").write_text(json.dumps(context),
                                                       encoding="utf-8")
    store = Store(tmp_path / "m.db")
    window = ResultsWindow(brian_dir, "Brian call", store=store)
    tab = window.tabs.widget(window.coaching_tab_index)
    assert tab.me_confirmed is True
    assert len(store.me_baseline_rows()) == 1
    window.close()
    store.close()


def test_current_call_baseline_row_is_stored(qapp, run_dir, tmp_path):
    _set_me(run_dir)
    store = Store(tmp_path / "m.db")
    window = _window(qapp, run_dir, store)
    call_id = call_id_for(run_dir / "call")
    rows = store.me_baseline_rows()
    assert any(r["call_id"] == call_id for r in rows)
    row = next(r for r in rows if r["call_id"] == call_id)
    assert all(isinstance(v, (int, float)) for r in rows
               for v in r["features"].values())
    assert row["minutes_spoken"] > 0
    window.close()
    store.close()


def test_self_labels_are_recorded(qapp, run_dir, tmp_path):
    _set_me(run_dir)
    store = Store(tmp_path / "m.db")
    window = _window(qapp, run_dir, store)
    tab = window.tabs.widget(window.coaching_tab_index)
    tab._self_label("T029", "yes")
    assert store.self_labels_for(tab.call_id) == {"T029": "yes"}
    window.close()
    store.close()


def test_coaching_import_writes_and_filters(qapp, run_dir, tmp_path):
    _set_me(run_dir)
    store = Store(tmp_path / "m.db")
    window = _window(qapp, run_dir, store)
    tab = window.tabs.widget(window.coaching_tab_index)
    tab.coach_edit.setPlainText(json.dumps({
        "observations": [
            {"feature": "hedges", "text": "Fewer hedges than usual.",
             "turn_id": "T029", "try": "Keep it."},
            {"feature": "pace", "text": "You sounded like you were lying.",
             "try": "-"},
        ],
        "nothing_to_report": False}))
    tab._import_coaching()
    path = run_dir / "call.coaching.json"
    assert path.exists()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert len(saved["observations"]) == 1  # banned wording filtered
    assert saved["observations"][0]["feature"] == "hedges"
    window.close()
    store.close()


def test_reset_clears_history_not_recordings(qapp, run_dir, tmp_path):
    _set_me(run_dir)
    store = Store(tmp_path / "m.db")
    _seed_history(store, 3)
    window = _window(qapp, run_dir, store)
    store.reset_me_baseline()
    assert store.me_baseline_rows() == []
    assert (run_dir / "call.json").exists()
    window.close()
    store.close()
