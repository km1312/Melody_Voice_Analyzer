"""The results window offscreen: loading, tabs, sync, import (FR-10..15)."""

import json
import shutil

import pytest

from revolv.gui_results import (ResultsData, ResultsWindow, latest_insights,
                                questions_asked, speaker_facts)


@pytest.fixture()
def run_dir(tmp_path, fixture_dir):
    for name in ("call.json", "call.analysis.json", "meta.json"):
        shutil.copy(fixture_dir / name, tmp_path / name)
    return tmp_path


def _valid_response(report):
    """One verifiable reading about the hesitation-cluster turn."""
    cluster = next(m for m in report["moments"]
                   if any(e["feature"] == "medial_fillers"
                          for e in m["evidence"]))
    position = report["moments"].index(cluster) + 1
    turn = report["turns"][cluster["turn"]]
    tid = "T{0:03d}".format(cluster["turn"] + 1)
    mid = "M{0:03d}".format(position)
    quote = " ".join(turn["text"].split()[:6])
    return json.dumps({
        "topics": [{"id": "tp1", "label": "The plan",
                    "spans": [["T001", "T005"]], "raised_by": "SPEAKER_00"}],
        "notes": {"summary": "A synthetic call about the widget plan.",
                  "decisions": [{"text": "Keep the plan",
                                 "turn_ids": ["T001"]}],
                  "action_items": [], "open_questions": [], "key_numbers": []},
        "speakers": [{"label": "SPEAKER_01", "nothing_notable": False,
                      "cares_about": []}],
        "insights": [{
            "id": "ins_001", "layer": "unsaid", "speaker": turn["speaker"],
            "topic_id": "tp1",
            "claim": "May have held something back here; worth checking.",
            "likelihood": "roughly even chance",
            "evidence_confidence": "low",
            "evidence": [
                {"turn_id": tid, "quote": quote, "channel": "lexical",
                 "moment_ids": [], "description": "soft agreement"},
                {"turn_id": tid, "quote": "", "channel": "timing",
                 "moment_ids": [], "description": "slow reply"},
                {"turn_id": tid, "quote": "", "channel": "disfluency",
                 "moment_ids": [mid], "description": "fillers"},
            ],
            "alternatives": ["Thinking time"],
            "follow_up": "What would make this solid?",
        }],
        "so_what": [{"text": "Check the reservation.", "refs": ["ins_001"]}],
    })


def test_speaker_facts_are_measured_only(fixture_report):
    facts = speaker_facts(fixture_report)
    assert set(facts) == {"SPEAKER_00", "SPEAKER_01", "SPEAKER_02"}
    s0 = facts["SPEAKER_00"]
    assert 0.4 < s0["talk_share"] < 0.6
    assert s0["floor_takes"] == 1
    assert facts["SPEAKER_02"]["backchannels"] == 1
    for entry in facts.values():
        assert set(entry) == {"talk_share", "turns", "median_reply",
                              "articulation_wpm", "floor_takes",
                              "backchannels", "questions_asked"}


def test_window_without_insights_shows_import(qapp, run_dir):
    window = ResultsWindow(run_dir, "call")
    labels = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert labels[0] == "Import"
    assert "Under the surface" not in labels
    window.close()


def test_missing_media_disables_playback_only(qapp, run_dir):
    window = ResultsWindow(run_dir, "call")
    assert window.player.state == "unavailable"
    assert window.player_note.text().startswith("Playback off:")
    assert window.transcript.count() == 41  # everything else works
    window.close()


def test_import_round_trip_builds_the_tabs(qapp, run_dir, fixture_report):
    window = ResultsWindow(run_dir, "call")
    window.import_edit.setPlainText(_valid_response(fixture_report))
    window._import_pasted()
    assert latest_insights(run_dir, "call") is not None
    labels = [window.tabs.tabText(i) for i in range(window.tabs.count())]
    assert labels == ["Notes", "Under the surface", "Speakers",
                      "How you sounded"]
    assert len(window.cards) == 1
    card = window.cards[0]
    assert "worth checking" in card.insight["claim"]
    window.close()


def test_import_problems_are_shown_in_plain_words(qapp, run_dir):
    window = ResultsWindow(run_dir, "call")
    window.import_edit.setPlainText("{}")
    window._import_pasted()
    assert window.import_problems.text()
    assert latest_insights(run_dir, "call") is None
    window.close()


def test_notes_links_select_and_cue(qapp, run_dir, fixture_report):
    window = ResultsWindow(run_dir, "call")
    window.import_edit.setPlainText(_valid_response(fixture_report))
    window._import_pasted()
    played = []
    window.player.play = lambda b, e: played.append((b, e)) or True
    html = window._notes_html()
    assert 'href="turn:T001"' in html
    window.select_turn(0, play=True)
    assert window.transcript.currentRow() == 0
    assert played and played[0][0] == max(
        int(fixture_report["turns"][0]["start"] * 1000) - 1500, 0)
    window.close()


def test_position_follows_with_a_marker_not_the_selection(qapp, run_dir,
                                                          fixture_report):
    """Fix list #1: playback marks the playing turn but never steals the
    selection, so a click mid-playback is not fought over."""
    from PySide6.QtCore import Qt

    window = ResultsWindow(run_dir, "call")
    window.transcript.setCurrentRow(5)  # the user's own selection
    third = fixture_report["turns"][2]
    middle_ms = int((third["start"] + third["end"]) / 2 * 1000)
    window._follow_position(middle_ms)
    assert window._playing_row == 2
    assert window.transcript.currentRow() == 5  # untouched
    assert window.transcript.item(2).data(Qt.BackgroundRole) is not None
    # Moving on clears the old marker.
    fourth = fixture_report["turns"][3]
    window._follow_position(int((fourth["start"] + fourth["end"]) / 2 * 1000))
    assert window.transcript.item(2).data(Qt.BackgroundRole) is None
    assert window._playing_row == 3
    window.close()


def test_transcript_layout_never_elides(qapp, run_dir):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListView

    window = ResultsWindow(run_dir, "call")
    assert window.transcript.resizeMode() == QListView.Adjust
    assert window.transcript.textElideMode() == Qt.ElideNone
    assert window.transcript.horizontalScrollBarPolicy() == \
        Qt.ScrollBarAlwaysOff
    window.close()


def test_interjections_render_inline(qapp, run_dir):
    """Fix list #4: a run of words diarized to another speaker shows as
    [Name: words] instead of being silently folded into the turn."""
    window = ResultsWindow(run_dir, "call")
    words = window.data.turn_words()[0]
    assert words  # rebuilt from the segments
    words[3] = dict(words[3], speaker="SPEAKER_01")
    window.data.context["speaker_names"] = {"SPEAKER_01": "Brian"}
    window._fill_transcript()
    first = window.transcript.item(0).text()
    assert "[Brian: {0}]".format(words[3]["word"]) in first
    window.close()


def test_reload_context_applies_names_everywhere(qapp, run_dir):
    """Fix list #2: names saved while Results is open reach the transcript
    and the timeline on reload_context()."""
    from revolv.interpret import context as context_module

    window = ResultsWindow(run_dir, "call")
    assert "SPEAKER_00" in window.transcript.item(0).text()
    context = context_module.default_context()
    context["speaker_names"] = {"SPEAKER_00": "Kaden",
                                "SPEAKER_01": "Brian"}
    assert context_module.save(context, run_dir / "call.context.json") == []
    window.reload_context()
    assert "Kaden" in window.transcript.item(0).text()
    assert window.timeline.names.get("SPEAKER_00") == "Kaden"
    window.close()


def test_questions_asked_counts_mid_turn_questions():
    report = {"turns": [
        {"speaker": "A", "text": "How so? Well, we shipped it anyway."},
        {"speaker": "A", "text": "Fine."},
        {"speaker": "B", "text": "Really? And then what? [laughter] Right."},
    ]}
    assert questions_asked(report) == {"A": 1, "B": 2}


def test_subtext_off_hides_the_tab_and_pins(qapp, run_dir, fixture_report):
    window = ResultsWindow(run_dir, "call",
                           settings={"subtext_enabled": True})
    window.import_edit.setPlainText(_valid_response(fixture_report))
    window._import_pasted()
    window.close()

    hidden = ResultsWindow(run_dir, "call",
                           settings={"subtext_enabled": False})
    labels = [hidden.tabs.tabText(i) for i in range(hidden.tabs.count())]
    assert "Under the surface" not in labels
    assert not [m for m in hidden.timeline.marks if m["kind"] == "pin"]
    hidden.close()


def test_results_data_reads_latest_insights(qapp, run_dir, fixture_report):
    window = ResultsWindow(run_dir, "call")
    window.import_edit.setPlainText(_valid_response(fixture_report))
    window._import_pasted()
    window.close()
    data = ResultsData(run_dir, "call")
    assert data.insights is not None
    assert data.insights["insights"][0]["id"] == "ins_001"
