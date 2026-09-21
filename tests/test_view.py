"""interpret.view: the numbered view's indexes, offsets and guard rails."""

import pytest

from revolv.interpret import view as view_module
from revolv.interpret.view import ViewError, build, contains, normalise


@pytest.fixture(scope="module")
def built(request):
    fixture_report = request.getfixturevalue("fixture_report")
    fixture_segments = request.getfixturevalue("fixture_segments")
    fixture_meta = request.getfixturevalue("fixture_meta")
    meta = dict(fixture_meta, analysis=fixture_report, numbers_file=True)
    return build(fixture_report, fixture_segments, meta)


def test_offsets_match_the_report_within_1ms(built, fixture_report):
    for turn in fixture_report["turns"]:
        entry = built.turns["T{0:03d}".format(turn["index"] + 1)]
        assert abs(entry["start_ms"] - turn["start"] * 1000) <= 1
        assert abs(entry["end_ms"] - turn["end"] * 1000) <= 1
        assert entry["speaker"] == turn["speaker"]


def test_words_carry_kinds_and_timings(built):
    kinds = {w.get("kind") for entry in built.turns.values()
             for w in entry["words"] if w.get("kind")}
    assert "filler" in kinds
    for entry in built.turns.values():
        for word in entry["words"]:
            assert "start" in word and "end" in word


def test_moment_index_links_to_turns(built, fixture_report):
    assert len(built.moments) == len(fixture_report["moments"])
    for mid, entry in built.moments.items():
        assert entry["turn_id"] in built.turns
        assert built.turns[entry["turn_id"]]["moment_id"] == mid
        assert entry["evidence"] or entry["baseline"] in ("call", "trailing")


def test_gap_before_matches_silence_arithmetic(built, fixture_report):
    order = built.turn_order
    for previous_id, this_id in zip(order, order[1:]):
        previous, this = built.turns[previous_id], built.turns[this_id]
        gap = (this["start_ms"] - previous["end_ms"]) / 1000.0
        assert abs(this["gap_before_s"] - gap) < 0.011


def test_ids_are_deterministic(built, fixture_report, fixture_segments,
                               fixture_meta):
    meta = dict(fixture_meta, analysis=fixture_report, numbers_file=True)
    again = build(fixture_report, fixture_segments, meta)
    assert built.turn_order == again.turn_order
    assert sorted(built.moments) == sorted(again.moments)
    assert built.text == again.text


def test_mismatched_segments_raise(fixture_report, fixture_segments,
                                   fixture_meta):
    meta = dict(fixture_meta, analysis=fixture_report)
    with pytest.raises(ViewError):
        build(fixture_report, fixture_segments[:-2], meta)
    tampered = [dict(s) for s in fixture_segments]
    tampered[0] = dict(tampered[0], speaker="SPEAKER_09")
    with pytest.raises(ViewError):
        build(fixture_report, tampered, meta)


def test_token_estimate_is_plausible(built):
    assert built.token_estimate == len(built.text) // 4
    assert built.token_estimate > 500


# -- the normal form --------------------------------------------------------

def test_normalise_lowercases_and_strips_punctuation():
    assert normalise("That makes a TON of sense.") == "that makes a ton of sense"


def test_normalise_keeps_cutoff_hyphens():
    assert normalise("It's like s- s- standard.") == "it's like s- s- standard"


def test_normalise_drops_pause_marks():
    assert normalise("What was the um (...2.4s) uh word") == \
        "what was the um uh word"


def test_normalise_unwraps_events():
    assert normalise("great [laughter] exactly") == "great laughter exactly"


def test_contains_is_whole_token():
    turn = normalise("we shipped the standard error rate")
    assert contains(turn, normalise("standard error"))
    assert not contains(turn, normalise("standard errors"))
    assert not contains(turn, normalise("tandard error"))
    assert not contains(turn, "")
