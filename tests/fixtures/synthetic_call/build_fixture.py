"""Build the synthetic test fixture: a call that never happened.

Everything the interpretation layer consumes is generated here from word
lists and sine tones, run through the real analysis pass and the real
writers, so the committed `call.json`, `call.md`, `call.analysis.json` and
`meta.json` are exactly what the pipeline would produce for a recording with
these properties. No real speech is involved at any point (PRD M0.3).

The call is engineered so specific things exist to test against:

- two main speakers with proper baselines (16 scored turns each) and one
  minor speaker with none;
- moments on several distinct features: arousal (a low-energy turn), medial
  fillers (a hesitation cluster), articulation (a rushed turn), f0 range (a
  swept-pitch turn), loudness variation (an emphatic turn) and a terminal
  rise, plus long in-turn pauses;
- one turn (the hesitation cluster) that also carries a 6 s reply gap and a
  2.4 s in-turn pause, so timing, disfluency and prosody evidence converge on
  a single turn the way the PRD's worked example M017 does;
- overlap events of both kinds, derived from the diarization rows: one
  backchannel wholly inside a main speaker's turn and one floor-take;
- verbatim word kinds (filler, cutoff, repetition, vocalisation, event);
- a canary phrase, three words that occur nowhere else, which the log-hygiene
  tests grep for: they must never reach melody.log or the window pane.

Run it from the repo root to regenerate (it overwrites its own outputs, which
is the one place that is allowed to):

    .venv\\Scripts\\python.exe tests\\fixtures\\synthetic_call\\build_fixture.py
"""

import json
import math
import random
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))

from revolv import analysis, prosody  # noqa: E402
from revolv.writers import write_all  # noqa: E402

SR = 16000
STEM = "call"

CANARY = ["flumberwick", "zonkey", "parade"]

S0, S1, MINOR = "SPEAKER_00", "SPEAKER_01", "SPEAKER_02"
BASE_HZ = {S0: 120.0, S1: 205.0, MINOR: 160.0}

# Filler words used to pad sentences to length; deliberately bland.
_PAD = ("the synthetic widget pipeline shows steady numbers across the "
        "quarterly report and the team agrees on the plan").split()


class Turn:
    def __init__(self, speaker, words, gap_before=0.6, word_seconds=0.28,
                 pause_after=None, arousal=None, pitch="flat", wobble=0.75,
                 amp="steady"):
        self.speaker = speaker
        self.words = words          # list of (text, kind-or-None)
        self.gap_before = gap_before
        self.word_seconds = word_seconds
        self.pause_after = pause_after or {}  # word index -> silence seconds
        self.arousal = arousal
        self.pitch = pitch          # "flat" | "sweep" | "rise"
        self.wobble = wobble        # semitone wobble amplitude for "flat"
        self.amp = amp              # "steady" | "emphatic"


def _sentence(rng, count, extra=()):
    words = list(extra)
    while len(words) < count:
        words.append((_PAD[(len(words) * 7 + rng.randrange(len(_PAD))) % len(_PAD)], None))
    return words[:count] if not extra else words[: max(count, len(extra))]


def _plain(rng, count):
    start = rng.randrange(len(_PAD))
    return [(_PAD[(start + i) % len(_PAD)], None) for i in range(count)]


def build_turns():
    rng = random.Random(20260921)
    turns = []

    def scored(speaker, tag=None, gap=None, **kw):
        jitter = rng.uniform(0.94, 1.06)
        words = kw.pop("words", None) or _plain(rng, 14)
        turns.append(Turn(
            speaker, words,
            gap_before=gap if gap is not None else rng.uniform(0.45, 0.85),
            word_seconds=kw.pop("word_seconds", 0.30 * jitter),
            arousal=kw.pop("arousal", round(rng.uniform(0.435, 0.465), 3)),
            **kw))
        return turns[-1]

    # Opening: alternate the two mains. Turn indexes are deterministic, so
    # the tests refer to specific behaviours, not hard-coded ids.
    scored(S0, words=[("welcome", None), ("to", None), ("the", None),
                      ("synthetic", None), ("review", None), ("of", None),
                      ("the", None), ("widget", None), ("pipeline", None),
                      ("for", None), ("the", None), ("quarter", None),
                      ("ahead", None), ("today", None)])
    scored(S1)
    # A rushed turn for SPEAKER_00: articulation departure.
    scored(S0, words=_plain(random.Random(7), 22), word_seconds=0.165)
    scored(S1, words=_plain(random.Random(8), 14) + [("we", "repetition"), ("we", None), ("said", None), ("s-", "cutoff"), ("so", None)])
    # Canary turn: the three words that may never appear in a log.
    scored(S0, words=[("the", None), (CANARY[0], None), (CANARY[1], None),
                      (CANARY[2], None), ("figure", None), ("is", None),
                      ("confidential", None), ("and", None), ("stays", None),
                      ("inside", None), ("this", None), ("fixture", None),
                      ("forever", None), ("understood", None)])
    scored(S1)
    # Wide pitch sweep for SPEAKER_00: f0_range departure.
    scored(S0, pitch="sweep")
    scored(S1)
    # A long S0 turn with a bystander backchannel inside it (diarization only).
    long_turn = scored(S0, words=_plain(random.Random(9), 26), word_seconds=0.34)
    scored(S1)
    # Emphatic loudness for SPEAKER_00.
    scored(S0, amp="emphatic")
    # Low-arousal turn for SPEAKER_01: energy departure.
    scored(S1, arousal=0.18)
    scored(S0)
    scored(S1, words=_plain(random.Random(10), 13) + [("[laughter]", "event")])
    scored(S0)
    # Terminal rise for SPEAKER_01.
    scored(S1, pitch="rise")

    # Two minor-speaker turns, short, unscored.
    turns.append(Turn(MINOR, [("hi", None), ("everyone", None)], gap_before=2.5,
                      word_seconds=0.3))
    turns.append(Turn(S0, _plain(rng, 14), gap_before=0.7,
                      word_seconds=0.30 * rng.uniform(0.94, 1.06)))

    # Middle stretch: keep alternating so both mains clear 16 scored turns.
    # SPEAKER_01's medial-filler pattern: an occasional single "um", then one
    # turn with a cluster of four plus the 6 s reply gap and a 2.4 s pause.
    def s1_with_medial(medial, gap=None, pause=None):
        base = _plain(rng, 12)
        words = []
        for i, item in enumerate(base):
            words.append(item)
            if i in (2, 5, 7, 9)[:medial]:
                words.append(("um", "filler"))
        return scored(S1, words=words, gap=gap, pause_after=pause or {})

    for _round in range(5):
        scored(S0)
        s1_with_medial(1)
    scored(S0)
    # The M017-alike: slow reply, hesitation cluster, long mid-turn pause.
    cluster = s1_with_medial(4, gap=6.0, pause={6: 2.4})
    scored(S0)
    s1_with_medial(1)
    turns.append(Turn(MINOR, [("mhm", "vocalisation"), ("right", None)],
                      gap_before=2.2, word_seconds=0.3))
    scored(S0, gap=1.2)
    s1_with_medial(1)
    # A short unscored backchannel turn for each main.
    turns.append(Turn(S1, [("right", None)], gap_before=2.4, word_seconds=0.3))
    scored(S0, gap=0.9)
    s1_with_medial(1)
    turns.append(Turn(S0, [("okay", None)], gap_before=2.2, word_seconds=0.3))
    s1_with_medial(1, gap=0.8)
    scored(S0)
    s1_with_medial(1)

    return turns, long_turn, cluster


def lay_out(turns):
    """Assign word timings, build segments and diarization rows."""
    cursor = 4.0
    segments = []
    rows = []
    spans = {}
    for turn in turns:
        start = cursor + turn.gap_before
        t = start
        words = []
        for index, (text, kind) in enumerate(turn.words):
            begin = t
            end = begin + turn.word_seconds
            item = {"word": text, "start": round(begin, 2), "end": round(end, 2)}
            if kind:
                item["kind"] = kind
            words.append(item)
            t = end + (0.06 if turn.word_seconds > 0.2 else 0.03)
            t += turn.pause_after.get(index, 0.0)
        seg_start, seg_end = words[0]["start"], words[-1]["end"]
        duration = max(seg_end - seg_start, 0.01)
        spoken = [w for w in words if w.get("kind") != "event"]
        segments.append({
            "start": seg_start,
            "end": seg_end,
            "speaker": turn.speaker,
            "text": " ".join(w["word"] for w in words),
            "words": words,
            "pacing": {
                "word_count": len(spoken),
                "duration_seconds": round(duration, 2),
                "wpm": round(len(spoken) / (duration / 60.0), 1),
            },
        })
        rows.append({"start": round(seg_start, 3), "end": round(seg_end, 3),
                     "speaker": turn.speaker})
        spans[id(turn)] = (seg_start, seg_end)
        cursor = seg_end
    return segments, rows, spans, cursor + 3.0


def stamp_emotion(segments, turns):
    for turn, segment in zip(turns, segments):
        speech = segment["end"] - segment["start"]
        if turn.arousal is None or speech < analysis.EMOTION_MIN_SPEECH:
            continue
        segment["emotion"] = {
            "arousal": turn.arousal,
            "valence": round(0.5 + (turn.arousal - 0.45) * 0.3, 3),
            "dominance": 0.5,
            "measured_over": [round(segment["start"], 2),
                              round(segment["end"], 2)],
        }


def synthesise(turns, segments, total_seconds):
    """Sine tones under every word, shaped per turn's pitch and amplitude."""
    audio = np.zeros(int(total_seconds * SR) + SR, dtype=np.float32)
    for turn, segment in zip(turns, segments):
        base = BASE_HZ[turn.speaker]
        seg_start, seg_end = segment["start"], segment["end"]
        length = max(seg_end - seg_start, 0.01)
        for w_index, word in enumerate(segment["words"]):
            begin, end = word["start"], word["end"]
            n = int((end - begin) * SR)
            if n <= 0:
                continue
            t = np.arange(n) / SR
            mid = (begin + end) / 2.0
            position = (mid - seg_start) / length  # 0..1 through the turn
            if turn.pitch == "sweep":
                semis = -8.0 + 18.0 * position
            elif turn.pitch == "rise" and seg_end - mid < 0.45:
                semis = 5.0
            else:
                semis = turn.wobble * math.sin(2.0 * math.pi * (position * 3.1 + w_index * 0.37))
            hz = base * (2.0 ** (semis / 12.0))
            if turn.amp == "emphatic":
                amp = 0.5 if w_index % 2 == 0 else 0.1
            else:
                amp = 0.3 + 0.02 * math.sin(w_index)
            tone = (amp * np.sin(2.0 * np.pi * hz * t)).astype(np.float32)
            fade = min(int(0.008 * SR), n // 2)
            if fade:
                ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
                tone[:fade] *= ramp
                tone[-fade:] *= ramp[::-1]
            lo = int(begin * SR)
            audio[lo:lo + n] += tone
    return audio


def main():
    turns, long_turn, cluster = build_turns()
    segments, rows, spans, total = lay_out(turns)
    stamp_emotion(segments, turns)

    # Overlap events, in the diarization only: a bystander backchannel wholly
    # inside the long SPEAKER_00 turn, and SPEAKER_01 taking the floor over
    # the end of the turn after the cluster.
    lo, hi = spans[id(long_turn)]
    rows.append({"start": round(lo + 2.0, 3), "end": round(lo + 2.8, 3),
                 "speaker": MINOR})
    c_lo, c_hi = spans[id(cluster)]
    rows.append({"start": round(c_hi - 0.7, 3), "end": round(c_hi + 0.4, 3),
                 "speaker": S0})
    rows.sort(key=lambda r: r["start"])

    audio = synthesise(turns, segments, total)
    track = prosody.track(audio, SR, tracker="yin")

    meta = {
        "source": str(HERE / "call.wav"),
        "media_seconds": round(total, 2),
        "language": "en",
        "segments": len(segments),
        "speakers": 3,
        "backend": "whisper",
        "verbatim": True,
        "model": "synthetic-fixture",
        "device": "cpu",
        "device_name": "Fixture",
        "compute_type": "int8",
        "emotion_scope": "turn",
        "diarization": rows,
    }
    meta["analysis"] = analysis.analyse(segments, meta, track=track)

    # Regenerating the fixture replaces it; unique_path must not fork copies.
    for name in ("call.json", "call.md", "call.analysis.json"):
        (HERE / name).unlink(missing_ok=True)
    written = write_all(segments, meta, HERE, STEM, ["json", "md"])

    public_meta = {k: v for k, v in meta.items() if k != "analysis"}
    with open(HERE / "meta.json", "w", encoding="utf-8") as f:
        json.dump(public_meta, f, indent=2)

    report = meta["analysis"]
    features = sorted({item["feature"] for m in report["moments"]
                       for item in m["evidence"]})
    print("turns:", report["summary"]["turns"],
          "scored:", report["summary"]["scored_turns"])
    for name, entry in report["speakers"].items():
        print(name, "scored", entry["scored_turns"], "baseline",
              entry["baseline_turns"])
    print("moments:", len(report["moments"]), "features:", features)
    print("overlaps:", report.get("overlap", {}).get("backchannels"),
          "backchannel /", report.get("overlap", {}).get("floor_taking"),
          "floor-taking")
    print("written:", [p.name for p in written])


if __name__ == "__main__":
    main()
