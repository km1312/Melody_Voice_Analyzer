"""Input variants for the ablations (PRD section 10).

Each transform acts on the report and the segments before the view renders,
never by editing rendered text. `no_timing` and `clean` also suppress the
silence lines through a renderer override rather than by shifting
timestamps, because shifted turns would no longer match their segments and
the view's own consistency check would (rightly) refuse them.
"""

import copy
import re

VARIANTS = ("full", "no_notes", "no_timing", "clean")

_TAGGED = {"filler", "cutoff", "repetition", "vocalisation", "event"}
_SPACES = re.compile(r"\s+")


def apply(name, segments, report):
    """(segments, report, render_overrides) for one variant."""
    if name not in VARIANTS:
        raise ValueError("unknown variant {0!r}".format(name))
    if name == "full":
        return segments, report, {}

    segments = copy.deepcopy(segments)
    report = copy.deepcopy(report)
    overrides = {}

    # no_notes and everything above it: no moments, no bracketed notes.
    report["moments"] = []

    if name in ("no_timing", "clean"):
        for turn in report.get("turns") or []:
            turn["pauses"] = []
        # Silence lines off: the override reaches writers.render_md.
        overrides["TURN_GAP_MARK_SECONDS"] = float("inf")

    if name == "clean":
        for segment in segments:
            words = [w for w in segment.get("words") or []
                     if w.get("kind") not in _TAGGED]
            segment["words"] = words
            segment["text"] = _SPACES.sub(
                " ", " ".join((w.get("word") or "").strip()
                              for w in words)).strip()
        _rebuild_turn_texts(report, segments)
        for turn in report.get("turns") or []:
            turn["disfluency"] = None
    return segments, report, overrides


def _rebuild_turn_texts(report, segments):
    """Turn text = the join of its segments' cleaned text, matched the way
    build_turns builds them (consecutive same-speaker within the break)."""
    from revolv import analysis

    rebuilt = analysis.build_turns(
        analysis.split_segments_by_speaker(segments))
    for turn, fresh in zip(report.get("turns") or [], rebuilt):
        turn["text"] = fresh["text"]
        turn["word_count"] = fresh["word_count"]


class render_overrides:
    """Temporarily apply renderer constants (the silence-line threshold)."""

    def __init__(self, overrides):
        self.overrides = overrides or {}
        self.saved = {}

    def __enter__(self):
        from revolv import writers

        for key, value in self.overrides.items():
            self.saved[key] = getattr(writers, key)
            setattr(writers, key, value)
        return self

    def __exit__(self, *exc):
        from revolv import writers

        for key, value in self.saved.items():
            setattr(writers, key, value)
        return False
