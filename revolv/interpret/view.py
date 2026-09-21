"""The numbered model view, and the indexes the verifier reads.

The text half is `writers.render_md(report, meta, numbered=True)`: the same
renderer as the `.md` on disk, so the two can never drift. The index half is
built from the report and the segments together, because the report's turns
carry no words (`analysis._public` strips them): the segments are rebuilt
into turns with `analysis.build_turns(analysis.split_segments_by_speaker(...))`,
which is deterministic and reproduces the report's turns exactly — and this
module checks that it did, turn by turn, rather than trusting it. A mismatch
means the segments and the report are not from the same run, and everything
downstream would silently cite the wrong words, so it raises.

Nothing in the indexes is ever sent to a model; they exist so code can check
what the model claims.
"""

import re

from .. import analysis
from ..writers import moment_id, render_md, turn_id

_PAUSE_MARK = re.compile(r"\(\.\.\.\d+(?:\.\d+)?s(?: silence)?\)")
_KEEP = re.compile(r"[^a-z0-9']+")


class ViewError(RuntimeError):
    """The segments and the report disagree; they are not from one run."""


def normalise(text):
    """The quote-matching normal form (PRD 7.4 rule 3).

    Lowercase; pause marks removed; punctuation removed except a trailing
    hyphen on a token, so a cut-off like `s-` survives; event brackets
    removed but the word inside kept; whitespace collapsed to single spaces.
    """
    text = (text or "").lower()
    text = _PAUSE_MARK.sub(" ", text)
    text = text.replace("[", " ").replace("]", " ")
    tokens = []
    for token in text.split():
        trailing_hyphen = token.rstrip(".,!?;:\"'").endswith("-")
        cleaned = _KEEP.sub("", token).strip("'")
        if trailing_hyphen and cleaned:
            cleaned += "-"
        if cleaned:
            tokens.append(cleaned)
    return " ".join(tokens)


def contains(haystack_norm, needle_norm):
    """Whole-token substring: is the normalised quote inside the turn?"""
    if not needle_norm:
        return False
    return " {0} ".format(needle_norm) in " {0} ".format(haystack_norm)


class View:
    """The numbered text plus a turn index and a moment index."""

    def __init__(self, text, turns, moments, token_estimate):
        self.text = text
        self.turns = turns          # {turn_id: entry}
        self.moments = moments      # {moment_id: entry}
        self.token_estimate = token_estimate

    @property
    def turn_order(self):
        return sorted(self.turns, key=lambda t: self.turns[t]["index"])


def build(report, segments, meta) -> View:
    """Assemble the View for one recording. Raises ViewError on a mismatch."""
    rebuilt = analysis.build_turns(
        analysis.split_segments_by_speaker(segments or []))
    public = report.get("turns") or []
    if len(rebuilt) != len(public):
        raise ViewError(
            "Rebuilt {0} turns from the segments but the report has {1}; the "
            "two files are not from the same run.".format(
                len(rebuilt), len(public)))
    for built, turn in zip(rebuilt, public):
        if (built["speaker"] != turn["speaker"]
                or abs(built["start"] - float(turn["start"])) > 0.001
                or abs(built["end"] - float(turn["end"])) > 0.001):
            raise ViewError(
                "Turn {0} differs between the segments ({1} {2:.2f}-{3:.2f}) "
                "and the report ({4} {5:.2f}-{6:.2f}).".format(
                    turn.get("index"), built["speaker"], built["start"],
                    built["end"], turn["speaker"], float(turn["start"]),
                    float(turn["end"])))

    moment_by_turn = {}
    moments = {}
    for position, moment in enumerate(report.get("moments") or [], start=1):
        mid = moment_id(position)
        tid = turn_id(moment["turn"])
        moment_by_turn[moment["turn"]] = mid
        moments[mid] = {
            "id": mid,
            "turn_id": tid,
            "baseline": moment.get("baseline"),
            "evidence": [dict(item) for item in moment.get("evidence") or []],
        }

    turns = {}
    previous_end = None
    for built, turn in zip(rebuilt, public):
        tid = turn_id(turn["index"])
        words = [dict(word) for segment in built["segments"]
                 for word in (segment.get("words") or [])]
        start = float(turn["start"])
        end = float(turn["end"])
        turns[tid] = {
            "id": tid,
            "index": turn["index"],
            "speaker": turn["speaker"],
            "start_ms": round(start * 1000),
            "end_ms": round(end * 1000),
            "text": turn.get("text", ""),
            "norm_text": normalise(turn.get("text", "")),
            "words": words,
            "gap_before_s": (round(start - previous_end, 2)
                             if previous_end is not None else 0.0),
            "reply_latency_s": turn.get("reply_latency"),
            "pauses": turn.get("pauses") or [],
            "disfluency": turn.get("disfluency"),
            "moment_id": moment_by_turn.get(turn["index"]),
        }
        previous_end = end

    text = render_md(report, meta, numbered=True)
    return View(text, turns, moments, token_estimate=len(text) // 4)
