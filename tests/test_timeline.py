"""Timeline arithmetic and hit-testing, offscreen (FR-12, M5.4)."""

from revolv import theme
from revolv.widgets.timeline import (FAMILIES, TimelineWidget, build_marks,
                                     moment_family, time_to_x, x_to_time)


def test_lanes_are_baselined_speakers_by_talk_share(fixture_report):
    lanes, _ = build_marks(fixture_report)
    assert lanes == ["SPEAKER_00", "SPEAKER_01"]  # minor speaker: no lane


def test_every_moment_becomes_a_tick_with_a_family(fixture_report):
    _, marks = build_marks(fixture_report)
    ticks = [m for m in marks if m["kind"] == "tick"]
    assert len(ticks) == len(fixture_report["moments"])
    for tick in ticks:
        assert tick["family"] in FAMILIES
        assert tick["end_ms"] > tick["start_ms"]


def test_silence_marks_cover_long_gaps(fixture_report):
    _, marks = build_marks(fixture_report)
    silences = [m for m in marks if m["kind"] == "silence"]
    assert silences
    for mark in silences:
        assert mark["end_ms"] - mark["start_ms"] >= 2000


def test_pins_follow_kept_readings_and_subtext(fixture_report):
    insights = [{"id": "ins_1", "speaker": "SPEAKER_01",
                 "evidence": [{"turn_id": "T029"}],
                 "audio_range": {"start_ms": 170_000, "end_ms": 180_000},
                 "key": "k"}]
    _, marks = build_marks(fixture_report, insights)
    pins = [m for m in marks if m["kind"] == "pin"]
    assert len(pins) == 1 and pins[0]["lane"] == 1
    _, marks = build_marks(fixture_report, insights, subtext=False)
    assert not [m for m in marks if m["kind"] == "pin"]


def test_moment_family_map():
    def of(feature):
        return moment_family({"evidence": [{"feature": feature}]})

    assert of("articulation") == "pace"
    assert of("f0_range") == "pitch"
    assert of("terminal_rise") == "pitch"
    assert of("arousal") == "energy"
    assert of("loudness_sd") == "energy"
    assert of("mismatch") == "energy"
    assert of("medial_fillers") == "hesitation"
    assert of("certainty") == "hesitation"
    assert moment_family({"evidence": []}) == "silence"  # pause-only moment


def test_time_pixel_round_trip():
    total = 600_000
    for ms in (0, 1234, 300_000, 599_999):
        x = time_to_x(ms, total, 800)
        assert abs(x_to_time(x, total, 800) - ms) <= total / 800 + 1


def test_families_have_their_own_colours():
    """Fix list #3: categorical family colours in both palettes, distinct
    from the accent (reserved for pins) and from the ok/bad pair."""
    from revolv.widgets.timeline import FAMILY_COLOR_KEYS

    for palette in (theme.get("light"), theme.get("dark")):
        used = set()
        for family in ("pace", "pitch", "energy", "hesitation"):
            key = FAMILY_COLOR_KEYS[family]
            assert key in palette, key
            colour = palette[key]
            assert colour not in (palette["accent"], palette["ok_text"],
                                  palette["bad_text"])
            used.add(colour)
        assert len(used) == 4  # all four distinct


def test_ticks_carry_their_notes_for_the_tooltip(qapp, fixture_report):
    widget = TimelineWidget(theme.get("light"))
    widget.set_data(fixture_report)
    ticks = [m for m in widget.marks if m["kind"] == "tick"]
    assert all(m["notes"] for m in ticks)
    tip = widget.tooltip_for(ticks[0])
    assert tip == "; ".join(ticks[0]["notes"])
    assert "usual" in tip or "pauses" in tip  # the .md's own phrasing
    silence = next(m for m in widget.marks if m["kind"] == "silence")
    assert "silence" in widget.tooltip_for(silence)
    assert widget.tooltip_for(None) == ""


def test_hit_test_finds_marks(qapp, fixture_report):
    widget = TimelineWidget(theme.get("light"))
    widget.resize(900, 200)
    widget.set_data(fixture_report)
    tick = next(m for m in widget.marks if m["kind"] == "tick")
    rect = widget.mark_rect(tick)
    found = widget.hit_test(rect.center().x(), rect.center().y())
    assert found is not None
    assert found["kind"] in ("tick", "silence")
    assert widget.hit_test(2, 2) is None  # inside the label gutter


def test_click_plays_with_lead(qapp, fixture_report):
    widget = TimelineWidget(theme.get("light"))
    widget.resize(900, 200)
    widget.set_data(fixture_report)
    seen = []
    widget.rangeClicked.connect(lambda b, e, m: seen.append((b, e, m)))
    tick = next(m for m in widget.marks if m["kind"] == "tick")
    rect = widget.mark_rect(tick)

    class FakeEvent:
        def position(self):
            return rect.center()

    widget.mouseReleaseEvent(FakeEvent())
    assert seen
    begin, end, mark = seen[0]
    if mark["kind"] == "tick":
        assert begin == max(mark["start_ms"] - 1500, 0)
        assert end == mark["end_ms"]
