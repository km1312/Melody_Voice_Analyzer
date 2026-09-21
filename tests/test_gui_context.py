"""The context window, offscreen: FR-1, FR-2, FR-4."""

import numpy as np
import pytest

from revolv.gui_context import ContextWindow, me_sample_ranges
from revolv.interpret import context as context_module
from revolv.player import Player


@pytest.fixture()
def window(qapp, tmp_path, fixture_report):
    win = ContextWindow(tmp_path / "call.context.json", fixture_report)
    yield win
    win.deleteLater()


def test_sample_ranges_cover_main_speakers_only(fixture_report):
    ranges = me_sample_ranges(fixture_report)
    assert "SPEAKER_00" in ranges
    assert "SPEAKER_01" in ranges
    assert "SPEAKER_02" not in ranges  # under five seconds of talk
    for begin, end in ranges.values():
        assert 0 < end - begin <= 3000


def test_sample_avoids_overlapped_turns(fixture_report):
    events = fixture_report["overlap_events"]
    ranges = me_sample_ranges(fixture_report)
    for label, (begin, end) in ranges.items():
        for event in events:
            overlap = (begin / 1000 < event["end"]
                       and event["start"] < end / 1000)
            # The sample sits inside a turn no event touches, so any event
            # overlapping the sample range would be a selection bug.
            assert not overlap, (label, event)


def test_untouched_window_saves_a_valid_default(window):
    problems = window.save()
    assert problems == []
    loaded = context_module.load(window.context_path)
    assert context_module.validate(loaded) == []
    assert loaded["me"] is None
    assert loaded["goal"] == ""
    assert loaded["consent"]["cloud_ok"] is False


def test_one_click_sets_me_and_it_can_change(window):
    window.me_buttons["SPEAKER_00"].click()
    assert window.collect()["me"] == "SPEAKER_00"
    window.me_buttons["SPEAKER_01"].click()
    assert window.collect()["me"] == "SPEAKER_01"
    window.clear_me()
    assert window.collect()["me"] is None


def test_fields_round_trip(window):
    window.type_box.setCurrentIndex(window.type_box.findData("negotiation"))
    window.goal_edit.setText("Agree the price")
    window.name_edits["SPEAKER_01"].setText("Brian")
    window.consent_buttons["yes"].click()
    window.save()
    loaded = context_module.load(window.context_path)
    assert loaded["meeting_type"] == "negotiation"
    assert loaded["goal"] == "Agree the price"
    assert loaded["speaker_names"] == {"SPEAKER_01": "Brian"}
    assert loaded["consent"]["all_parties_knew"] == "yes"


def test_topic_chips_update_important_topics(window):
    window.set_topics([{"id": "tp1", "label": "Timeline"},
                       {"id": "tp2", "label": "Price"}])
    seen = []
    window.topicsChanged.connect(seen.append)
    window.topic_chips["tp2"].setChecked(True)
    assert seen[-1] == ["tp2"]
    assert window.collect()["important_topics"] == ["tp2"]
    window.topic_chips["tp2"].setChecked(False)
    assert window.collect()["important_topics"] == []


def test_edits_schedule_a_debounced_save(qapp, tmp_path, fixture_report):
    """Fix list #2: editing arms the autosave timer; the save emits `saved`
    once per change, and closing with changes emits `closedSaved` once."""
    win = ContextWindow(tmp_path / "call.context.json", fixture_report)
    assert not win._save_timer.isActive()
    win.goal_edit.setText("Agree the price")
    win.goal_edit.textEdited.emit("Agree the price")
    assert win._save_timer.isActive()
    assert win._save_timer.interval() == 500

    saved, closed = [], []
    win.saved.connect(saved.append)
    win.closedSaved.connect(closed.append)
    win._save_timer.stop()
    win.save()  # what the timer would have run
    assert len(saved) == 1
    assert context_module.load(win.context_path)["goal"] == \
        "Agree the price"
    win.save()  # unchanged: no second emit
    assert len(saved) == 1
    win.close()
    assert len(closed) == 1


def test_untouched_close_emits_no_change_signal(qapp, tmp_path,
                                                fixture_report):
    win = ContextWindow(tmp_path / "call.context.json", fixture_report)
    closed = []
    win.closedSaved.connect(closed.append)
    win.close()
    assert closed == []


def test_play_sample_uses_the_player(qapp, tmp_path, fixture_report,
                                     fixture_meta):
    calls = []

    class FakePlayer:
        available = True

        def play(self, begin, end):
            calls.append((begin, end))

    win = ContextWindow(tmp_path / "call.context.json", fixture_report,
                        player=FakePlayer())
    win.play_sample("SPEAKER_00")
    assert calls == [me_sample_ranges(fixture_report)["SPEAKER_00"]]
    win.deleteLater()


def test_unavailable_player_does_not_crash(window):
    window.player = Player(samples=np.zeros(10), sample_rate=16000)
    window.player._unavailable("no device")
    window.play_sample("SPEAKER_00")  # no crash, no play
