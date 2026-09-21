"""coaching.py: features, composite, contrast, and the P6 slots (7.6)."""

import copy

from revolv import coaching
from revolv.interpret import pack as pack_module


def test_features_for_the_me_speaker(fixture_report):
    features = coaching.compute_features(fixture_report, "SPEAKER_01")
    assert features["medial_fillers_per_100w"] > 0
    assert features["restarts_per_100w"] > 0
    assert features["hedges_per_100w"] == 0.0
    assert 150 < features["articulation_wpm"] < 200
    assert features["long_pauses_per_min"] >= 0
    assert 0.0 <= features["rising_close_share"] <= 1.0
    assert 10 < features["median_pitch_st"] < 15  # ~205 Hz over 100 Hz
    assert features["median_reply_s"] > 0


def test_whisper_only_rows_read_not_measured(fixture_report):
    report = copy.deepcopy(fixture_report)
    for turn in report["turns"]:
        turn["disfluency"] = None
    features = coaching.compute_features(report, "SPEAKER_01")
    assert features["medial_fillers_per_100w"] is None
    assert features["restarts_per_100w"] is None
    table = coaching.feature_table_text(features, {})
    assert "not measured" in table


def _history(values, name="hedges_per_100w"):
    return [{"call_id": "c{0}".format(i), "call_date": "2026-01-0{0}".format(
        (i % 9) + 1), "features": {name: v}, "minutes_spoken": 10}
        for i, v in enumerate(values)]


def test_composite_needs_eight_calls():
    features = {"hedges_per_100w": 1.0}
    result = coaching.composite(features, _history([2, 3, 4, 5, 6, 7, 8]),
                                min_calls=8)
    assert result["percentile"] is None
    assert result["n"] == 7
    result = coaching.composite(features,
                                _history([2, 3, 4, 5, 6, 7, 8, 9]),
                                min_calls=8)
    assert result["percentile"] == 100  # lower hedges than every past call
    assert result["n"] == 8


def test_composite_sign_alignment():
    # articulation: higher is steadier.
    features = {"articulation_wpm": 100.0}
    history = _history([150, 160, 170, 180, 190, 200, 210, 220],
                       name="articulation_wpm")
    result = coaching.composite(features, history, min_calls=8)
    assert result["percentile"] == 0


def test_steadier_directions():
    assert coaching.steadier("hedges_per_100w", 1.0, 2.0)
    assert not coaching.steadier("hedges_per_100w", 3.0, 2.0)
    assert coaching.steadier("articulation_wpm", 180, 160)
    assert not coaching.steadier("median_reply_s", 0.1, 5.0)  # report only


def test_baseline_row_is_numbers_only(fixture_report):
    features = coaching.compute_features(fixture_report, "SPEAKER_01")
    features["rising_close_share"] = None
    row = coaching.baseline_row(features)
    assert "rising_close_share" not in row
    assert all(isinstance(v, (int, float)) for v in row.values())


def test_topic_contrast_finds_the_hesitant_topic(fixture_report):
    cluster = next(m for m in fixture_report["moments"]
                   if any(e["feature"] == "medial_fillers"
                          for e in m["evidence"]))
    cluster_tid = "T{0:03d}".format(cluster["turn"] + 1)
    topics = [
        {"id": "tpA", "label": "Hesitant patch",
         "spans": [[cluster_tid, cluster_tid]]},
        {"id": "tpB", "label": "Calm patch", "spans": [["T024", "T026"]]},
    ]
    contrast = coaching.topic_contrast(fixture_report, "SPEAKER_01", topics)
    assert contrast is not None
    assert contrast["least_assured"]["topic_id"] == "tpA"
    assert contrast["least_assured"]["turn_index"] == cluster["turn"]


def test_slots_fill_the_coaching_prompt(tmp_path, fixture_segments,
                                        fixture_meta, fixture_report):
    meta = dict(fixture_meta, analysis=fixture_report, numbers_file=True)
    slots = coaching.build_slots(fixture_report, "SPEAKER_01")
    pack_dir = pack_module.build_pack(fixture_segments, meta, tmp_path,
                                      "call", coaching_slots=slots)
    text = (pack_dir / "coaching.txt").read_text(encoding="utf-8")
    assert "{{" not in text
    assert "Mid-sentence fillers" in text
    assert "T0" in text  # candidate turns cite ids
