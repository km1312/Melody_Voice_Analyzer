"""Delivery features for the me-speaker, against their own history (7.6).

Everything here reads the report the pipeline already wrote; only hedges
need the text. The first three directions follow Kirkland et al.
(Interspeech 2022) on what listeners perceive as steadier; the rest are
assumptions with equal weight, which is why the composite ring is labelled
experimental until the self labels say it tracks anything (FR-17).

Nothing in this module scores anyone but the me-speaker, and the history it
compares against holds numbers only (PR-10).
"""

import math
import re
import statistics as st
from pathlib import Path

from .analysis import EMOTION_MIN_SPEECH

HEDGES_PATH = Path(__file__).resolve().parent / "assets" / "hedges.txt"

PITCH_REFERENCE_HZ = 100.0

# Feature -> which direction listeners tend to hear as steadier.
# "lower" and "higher" are scored; "report" rows are shown, never scored.
DIRECTIONS = {
    "medial_fillers_per_100w": "lower",
    "hedges_per_100w": "lower",
    "articulation_wpm": "higher",
    "long_pauses_per_min": "lower",
    "restarts_per_100w": "lower",
    "rising_close_share": "lower",
    "median_pitch_st": "lower",
    "median_reply_s": "report",
}

FEATURE_LABELS = {
    "medial_fillers_per_100w": "Mid-sentence fillers / 100 words",
    "hedges_per_100w": "Hedges / 100 words",
    "articulation_wpm": "Speaking rate (articulation wpm)",
    "long_pauses_per_min": "Long pauses / minute",
    "restarts_per_100w": "Restarts and cut-offs / 100 words",
    "rising_close_share": "Statements ending on a rise",
    "median_pitch_st": "Median pitch (semitones over 100 Hz)",
    "median_reply_s": "Median reply time",
}

# Rows that only exist when the verbatim pass ran.
NEEDS_VERBATIM = {"medial_fillers_per_100w", "restarts_per_100w"}


def _hedge_patterns():
    patterns = []
    try:
        lines = HEDGES_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        phrase = line.strip()
        if phrase:
            patterns.append(re.compile(
                r"\b" + r"\s+".join(re.escape(w) for w in phrase.split())
                + r"\b", re.IGNORECASE))
    return patterns


_HEDGES = _hedge_patterns()


def _me_turns(report, me):
    return [t for t in report.get("turns") or [] if t["speaker"] == me]


def compute_features(report, me):
    """The 7.6 table for one call. None means not measured on this call."""
    turns = _me_turns(report, me)
    scored = [t for t in turns
              if (t.get("speech_seconds") or 0) >= EMOTION_MIN_SPEECH]
    words = sum(t.get("word_count") or 0 for t in turns)
    speech_minutes = sum(t.get("speech_seconds") or 0 for t in turns) / 60.0
    entry = (report.get("speakers") or {}).get(me) or {}

    features = {name: None for name in DIRECTIONS}
    if not turns or not words:
        return features

    with_disfluency = [t for t in turns if t.get("disfluency")]
    if with_disfluency:
        medial = sum(t["disfluency"].get("medial", 0) for t in with_disfluency)
        restarts = sum(t["disfluency"].get("repetitions", 0)
                       + t["disfluency"].get("cutoffs", 0)
                       for t in with_disfluency)
        features["medial_fillers_per_100w"] = round(100.0 * medial / words, 2)
        features["restarts_per_100w"] = round(100.0 * restarts / words, 2)

    hedges = sum(len(pattern.findall(t.get("text") or ""))
                 for t in turns for pattern in _HEDGES)
    features["hedges_per_100w"] = round(100.0 * hedges / words, 2)

    features["articulation_wpm"] = entry.get("articulation_wpm")

    if speech_minutes > 0:
        pauses = sum(len(t.get("pauses") or []) for t in turns)
        features["long_pauses_per_min"] = round(pauses / speech_minutes, 2)

    closes = [t for t in scored
              if t.get("prosody")
              and t["prosody"].get("f0_terminal_rise") is not None
              and not (t.get("text") or "").strip().endswith("?")]
    if closes:
        rising = sum(1 for t in closes
                     if t["prosody"]["f0_terminal_rise"] > 0)
        features["rising_close_share"] = round(rising / len(closes), 3)

    pitches = [t["prosody"]["f0_median_hz"] for t in scored
               if t.get("prosody") and t["prosody"].get("f0_median_hz")]
    if pitches:
        median_hz = st.median(pitches)
        features["median_pitch_st"] = round(
            12.0 * math.log2(median_hz / PITCH_REFERENCE_HZ), 2)

    features["median_reply_s"] = entry.get("median_reply_latency")
    return features


def usual_features(history_rows):
    """Per feature, the median of the stored history (or None)."""
    usual = {}
    for name in DIRECTIONS:
        values = [row["features"].get(name) for row in history_rows
                  if row["features"].get(name) is not None]
        usual[name] = round(st.median(values), 2) if values else None
    return usual


def steadier(name, current, past):
    """Is `current` steadier than `past` for this feature?"""
    direction = DIRECTIONS.get(name)
    if direction == "lower":
        return current < past
    if direction == "higher":
        return current > past
    return False


def composite(features, history_rows, min_calls=8):
    """The ring: mean per-feature percentile against the user's own calls.

    Returns {"percentile", "features_used", "n"} once `min_calls` stored
    calls exist, else {"n": count} so the UI can say "building".
    """
    n = len(history_rows)
    if n < min_calls:
        return {"n": n, "percentile": None, "features_used": 0}
    shares = []
    for name, direction in DIRECTIONS.items():
        if direction == "report":
            continue
        current = features.get(name)
        if current is None:
            continue
        past = [row["features"].get(name) for row in history_rows
                if row["features"].get(name) is not None]
        if len(past) < min_calls:
            continue
        shares.append(sum(1 for value in past
                          if steadier(name, current, value)) / len(past))
    if not shares:
        return {"n": n, "percentile": None, "features_used": 0}
    return {"n": n, "percentile": round(100.0 * sum(shares) / len(shares)),
            "features_used": len(shares)}


def baseline_row(features):
    """What goes into the store: the numeric features, nothing else."""
    return {name: value for name, value in features.items()
            if isinstance(value, (int, float))}


# -- topic contrast (FR-18) --------------------------------------------------

def _turn_range(span):
    return int(span[0][1:]) - 1, int(span[1][1:]) - 1


def topic_contrast(report, me, topics):
    """Most and least assured topics, from own-baseline departures grouped
    by topic span. Departure weight is the count of evidence notes plus long
    pauses on the me-speaker's moments inside the span, per scored turn."""
    turns = report.get("turns") or []
    moments = report.get("moments") or []
    ranked = []
    for topic in topics or []:
        indexes = set()
        for span in topic.get("spans") or []:
            try:
                begin, end = _turn_range(span)
            except (ValueError, IndexError):
                continue
            indexes.update(range(begin, end + 1))
        me_scored = [i for i in indexes if 0 <= i < len(turns)
                     and turns[i]["speaker"] == me
                     and (turns[i].get("speech_seconds") or 0)
                     >= EMOTION_MIN_SPEECH]
        if not me_scored:
            continue
        weight = 0
        example = None
        for moment in moments:
            if moment["turn"] not in me_scored:
                continue
            weight += len(moment.get("observations") or [])
            example = moment["turn"]
        ranked.append({
            "topic_id": topic.get("id"),
            "label": topic.get("label") or topic.get("id"),
            "departures_per_turn": round(weight / len(me_scored), 2),
            "turn_index": example if example is not None else me_scored[0],
        })
    if len(ranked) < 2:
        return None
    ranked.sort(key=lambda item: item["departures_per_turn"])
    return {"most_assured": ranked[0], "least_assured": ranked[-1]}


# -- the P6 prompt slots -----------------------------------------------------

def _mmss(seconds):
    seconds = max(int(seconds), 0)
    return "{0:02d}:{1:02d}".format(seconds // 60, seconds % 60)


def feature_table_text(features, usual):
    lines = ["feature | this call | usual | steadier direction"]
    for name, direction in DIRECTIONS.items():
        value = features.get(name)
        past = (usual or {}).get(name)
        lines.append("{0} | {1} | {2} | {3}".format(
            FEATURE_LABELS[name],
            "not measured" if value is None else value,
            "-" if past is None else past,
            direction if direction != "report" else "reported only"))
    return "\n".join(lines)


def topic_contrast_text(contrast):
    if not contrast:
        return "Not enough topics with your turns to compare."
    return ("Most assured on: {0} ({1} departures per turn)\n"
            "Least assured on: {2} ({3} departures per turn)").format(
        contrast["most_assured"]["label"],
        contrast["most_assured"]["departures_per_turn"],
        contrast["least_assured"]["label"],
        contrast["least_assured"]["departures_per_turn"])


def candidate_turns_text(report, me, limit=8):
    lines = []
    for moment in report.get("moments") or []:
        if moment["speaker"] != me:
            continue
        turn = report["turns"][moment["turn"]]
        lines.append("T{0:03d} {1} - {2}".format(
            moment["turn"] + 1, _mmss(float(turn["start"])),
            "; ".join(moment.get("observations") or [])))
        if len(lines) >= limit:
            break
    return "\n".join(lines) or "none"


def build_slots(report, me, history_rows=None, topics=None):
    """The three P6 slots for pack.build_pack(coaching_slots=...)."""
    features = compute_features(report, me)
    usual = usual_features(history_rows or [])
    contrast = topic_contrast(report, me, topics or [])
    return {
        "FEATURE_TABLE": feature_table_text(features, usual),
        "TOPIC_CONTRAST": topic_contrast_text(contrast),
        "CANDIDATE_TURNS": candidate_turns_text(report, me),
    }


def slots_for(report, context, source_path=None):
    """`build_slots` with the stored history, or None without a me-speaker.
    Opens its own Store connection, so it is safe from any thread."""
    me = (context or {}).get("me")
    if not me or not report:
        return None
    try:
        from .store import Store, call_id_for

        store = Store()
        try:
            history = store.me_baseline_rows(
                exclude_call=call_id_for(source_path) if source_path
                else None)
        finally:
            store.close()
        return build_slots(report, me, history_rows=history)
    except Exception:
        return build_slots(report, me)
