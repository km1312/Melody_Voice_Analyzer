"""Response import end to end: files written, run recorded, log clean."""

import json

import pytest

from revolv.interpret import view as view_module
from revolv.interpret.manual_import import import_response, render_notes_md

CANARY = ["flumberwick", "zonkey", "parade"]


def _meta(fixture_meta, fixture_report):
    return dict(fixture_meta, analysis=fixture_report, numbers_file=True)


@pytest.fixture()
def valid_response(fixture_report):
    """A minimal valid single-pass reply citing real turns."""
    return json.dumps({
        "working": {"observations": [],
                    "rejected": [{"claim": "Voice-only hunch",
                                  "reason": "prosody alone"}]},
        "topics": [{"id": "tp1", "label": "The widget plan",
                    "spans": [["T001", "T010"]], "raised_by": "SPEAKER_00"}],
        "notes": {
            "summary": "A synthetic review of the widget pipeline.",
            "decisions": [{"text": "Keep the plan", "turn_ids": ["T001"]}],
            "action_items": [{"owner": "SPEAKER_00", "task": "Send numbers",
                              "due": "Friday", "turn_ids": ["T003"]}],
            "open_questions": [],
            "key_numbers": [],
        },
        "speakers": [{"label": "SPEAKER_01", "nothing_notable": True,
                      "cares_about": []}],
        "insights": [],
        "so_what": [{"text": "Nothing urgent.", "refs": []}],
    })


def test_import_writes_both_files(tmp_path, fixture_segments, fixture_meta,
                                  fixture_report, valid_response):
    result = import_response(fixture_segments,
                             _meta(fixture_meta, fixture_report),
                             tmp_path, "call", valid_response)
    assert result.problems == []
    assert result.insights_path.name == "call.insights.json"
    assert result.notes_path.name == "call.notes.md"

    document = json.loads(result.insights_path.read_text(encoding="utf-8"))
    assert document["schema_version"] == "1.0"
    assert document["run"]["provider"] == "manual"
    assert document["run"]["prompt_version"] == "p1.0.0"
    assert document["verifier"]["proposed"] == 0
    assert {"claim": "Voice-only hunch", "reason": "model_rejected"} \
        in document["dropped"]
    assert document["source"]["prosody"] is True

    notes = result.notes_path.read_text(encoding="utf-8")
    assert "Keep the plan" in notes
    assert "- [ ] SPEAKER_00: Send numbers - due Friday" in notes


def test_two_imports_sit_side_by_side(tmp_path, fixture_segments,
                                      fixture_meta, fixture_report,
                                      valid_response):
    meta = _meta(fixture_meta, fixture_report)
    first = import_response(fixture_segments, meta, tmp_path, "call",
                            valid_response)
    second = import_response(fixture_segments, meta, tmp_path, "call",
                             valid_response)
    assert first.insights_path.exists() and second.insights_path.exists()
    assert first.insights_path != second.insights_path
    a = json.loads(first.insights_path.read_text(encoding="utf-8"))
    b = json.loads(second.insights_path.read_text(encoding="utf-8"))
    assert a["run"]["run_id"] != b["run"]["run_id"]


def test_schema_problems_come_back_in_plain_words(tmp_path, fixture_segments,
                                                  fixture_meta,
                                                  fixture_report):
    result = import_response(fixture_segments,
                             _meta(fixture_meta, fixture_report),
                             tmp_path, "call", '{"insights": []}')
    assert result.problems
    assert result.insights_path is None
    assert not list(tmp_path.iterdir())


def test_import_log_carries_no_transcript_text(tmp_path, fixture_segments,
                                               fixture_meta, fixture_report,
                                               valid_response, capsys):
    lines = []
    import_response(fixture_segments, _meta(fixture_meta, fixture_report),
                    tmp_path, "call", valid_response, log=lines.append)
    logged = "\n".join(lines) + capsys.readouterr().out
    for word in CANARY:
        assert word not in logged
    assert "insights_written" in logged


def test_speaker_names_reach_the_notes(tmp_path, fixture_segments,
                                       fixture_meta, fixture_report,
                                       valid_response):
    context = {"me": None, "speaker_names": {"SPEAKER_00": "Kaden"},
               "meeting_type": "other"}
    result = import_response(fixture_segments,
                             _meta(fixture_meta, fixture_report),
                             tmp_path, "call", valid_response,
                             context=context)
    notes = result.notes_path.read_text(encoding="utf-8")
    assert "- [ ] Kaden: Send numbers" in notes


def test_notes_render_timestamps(fixture_segments, fixture_meta,
                                 fixture_report, valid_response):
    meta = _meta(fixture_meta, fixture_report)
    view = view_module.build(fixture_report, fixture_segments, meta)
    document = {"source": {"media": "call.wav"},
                "notes": {"summary": "s",
                          "decisions": [{"text": "x", "turn_ids": ["T001"]}],
                          "action_items": [], "open_questions": [],
                          "key_numbers": []}}
    text = render_notes_md(document, view)
    assert "- x (00:04)" in text
