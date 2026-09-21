"""The synthetic fixture has the properties every later test leans on."""

import json

from revolv import analysis

CANARY = ["flumberwick", "zonkey", "parade"]


def test_fixture_files_exist(fixture_dir):
    for name in ("call.json", "call.md", "call.analysis.json", "meta.json"):
        assert (fixture_dir / name).exists(), name


def test_main_speakers_have_baselines(fixture_report):
    speakers = fixture_report["speakers"]
    assert speakers["SPEAKER_00"]["baseline_turns"] >= analysis.MIN_TURNS_FOR_BASELINE
    assert speakers["SPEAKER_01"]["baseline_turns"] >= analysis.MIN_TURNS_FOR_BASELINE
    assert speakers["SPEAKER_02"]["baseline_turns"] == 0


def test_moments_cover_at_least_three_features(fixture_report):
    features = {item["feature"] for m in fixture_report["moments"]
                for item in m["evidence"]}
    assert len(features) >= 3, features
    assert "medial_fillers" in features  # the disfluency channel needs one


def test_overlap_has_both_kinds(fixture_report):
    events = fixture_report["overlap_events"]
    kinds = {e["kind"] for e in events}
    assert kinds == {"backchannel", "floor_taking"}


def test_verbatim_word_kinds_present(fixture_segments):
    kinds = {w.get("kind") for s in fixture_segments for w in s["words"]
             if w.get("kind")}
    assert {"filler", "cutoff", "repetition", "vocalisation", "event"} <= kinds


def test_disfluency_is_measured(fixture_report):
    assert any(t["disfluency"] is not None for t in fixture_report["turns"])


def test_cluster_turn_has_converging_timing_evidence(fixture_report):
    """One turn carries a slow reply, a long in-turn pause and a hesitation
    note together, which is what the verifier's channel checks exercise."""
    speakers = fixture_report["speakers"]
    found = False
    for moment in fixture_report["moments"]:
        if not any(e["feature"] == "medial_fillers" for e in moment["evidence"]):
            continue
        turn = fixture_report["turns"][moment["turn"]]
        median = speakers[turn["speaker"]]["median_reply_latency"]
        assert turn["reply_latency"] >= 2.0
        assert turn["reply_latency"] >= 3.0 * median
        assert any(p["seconds"] >= 2.0 for p in turn["pauses"])
        found = True
    assert found


def test_reply_gap_appears_as_silence_line(fixture_dir):
    text = (fixture_dir / "call.md").read_text(encoding="utf-8")
    assert "s silence)" in text


def test_canary_phrase_is_in_the_transcript(fixture_segments):
    text = " ".join(s["text"] for s in fixture_segments)
    for word in CANARY:
        assert word in text


def test_fixture_is_reanalysable(fixture_segments, fixture_meta, fixture_report):
    """analyse() over the committed segments reproduces the committed turn
    structure, which is what view.py depends on."""
    fresh = analysis.analyse(fixture_segments, fixture_meta)
    assert len(fresh["turns"]) == len(fixture_report["turns"])
    for a, b in zip(fresh["turns"], fixture_report["turns"]):
        assert a["speaker"] == b["speaker"]
        assert abs(a["start"] - b["start"]) < 0.001
        assert abs(a["end"] - b["end"]) < 0.001
