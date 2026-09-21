"""The deterministic verifier: code checks what code can check (PRD 7.4).

Every model response passes through here before anything reaches a screen or
a file, whichever provider produced it. The model proposes; this module
disposes. Quotes must appear in their cited turns, channels must be backed by
the turn index and the moment index, convergence and wording are enforced,
and the caps keep the output short. Everything dropped is recorded with its
reason, because FR-7 says so and because those reasons are the benchmark
harness's raw material.

The order of rules follows PRD 7.4 exactly; each rule is its own function
with a positive and a negative test in tests/test_verify.py.
"""

import hashlib
import json
import re

from .. import analysis
from . import schema as schema_module
from .view import contains, normalise

# -- constants (PRD section 6) ----------------------------------------------
MIN_CHANNELS = 2
REQUIRE_NONACOUSTIC = True
QUOTE_MAX_WORDS = 25
TIMING_MIN_GAP_SECONDS = 2.0
TIMING_MEDIAN_MULTIPLE = 3.0
IN_TURN_PAUSE_SECONDS = 2.0
MIN_TURNS_FOR_READINGS = analysis.MIN_TURNS_FOR_BASELINE
PLAY_LEAD_SECONDS = 1.5
CLIP_PAD_SECONDS = 10
MAX_AUDIO_RANGE_SECONDS = 60.0

NONACOUSTIC_CHANNELS = {"lexical", "interaction"}

# PR-6: wording that never reaches a user, whatever the evidence. Readings
# are dropped, not rewritten; note lines are dropped line by line.
BANNED_WORDS = re.compile(
    r"\b(?:lying|liar|liars|lie|lies|lied|deceptive|deceiving|deceitful|"
    r"dishonest|hiding|concealing|manipulative)\b",
    re.IGNORECASE)
BANNED_PHRASES = re.compile(r"evasive\s+person", re.IGNORECASE)

# PR-7: what a stance/unsaid/relational reading may claim, at most.
SHOWABLE_LIKELIHOODS = set(schema_module.SHOWABLE_LIKELIHOODS)

_CONFIDENCE_RANK = {"high": 2, "moderate": 1, "low": 0}
_LIKELIHOOD_RANK = {"very likely": 2, "likely": 1, "roughly even chance": 0}

# Interaction descriptions that lean on simultaneous speech must have an
# overlap event behind them.
_OVERLAP_WORDS = re.compile(
    r"\b(?:overlap\w*|interrupt\w*|floor|talks? over|talked over|cuts? in|"
    r"cut in)\b", re.IGNORECASE)


def banned_wording(text):
    text = text or ""
    return bool(BANNED_WORDS.search(text) or BANNED_PHRASES.search(text))


def strip_response(text):
    """Code fences off, outermost JSON object out."""
    text = (text or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    begin = text.find("{")
    end = text.rfind("}")
    if begin == -1 or end <= begin:
        return text
    return text[begin:end + 1]


def parse_response(text):
    """(draft, problems): fence-stripped JSON against the draft schema."""
    stripped = strip_response(text)
    try:
        draft = json.loads(stripped)
    except json.JSONDecodeError as exc:
        return None, ["The response is not valid JSON: {0}. Paste the "
                      "model's whole JSON reply, nothing else.".format(exc)]
    problems = schema_module.problems(draft, schema_module.INSIGHTS_DRAFT)
    if problems:
        return draft, ["The response does not match the expected shape. "
                       + p for p in problems]
    return draft, []


class VerifyResult:
    def __init__(self):
        self.kept = []
        self.dropped = []            # [{"claim": ..., "reason": ...}]
        self.notes = {}
        self.topics = []
        self.speakers = []
        self.so_what = []
        self.proposed = 0
        self.evidence_proposed = 0
        self.evidence_quote_rejected = 0
        self.dropped_by_reason = {}

    def drop(self, insight, reason):
        self.dropped.append({"claim": insight.get("claim", ""),
                             "reason": reason})
        self.dropped_by_reason[reason] = \
            self.dropped_by_reason.get(reason, 0) + 1

    def summary(self):
        return {"proposed": self.proposed, "kept": len(self.kept),
                "dropped_by_reason": dict(self.dropped_by_reason),
                "evidence_proposed": self.evidence_proposed,
                "evidence_quote_rejected": self.evidence_quote_rejected}


# -- evidence-level checks (rules 3 and 4) ----------------------------------

def check_quote(item, turn):
    """Rule 3 for one item. Returns (ok, matched, reason)."""
    quote = (item.get("quote") or "").strip()
    if not quote:
        return True, False, None
    if len(quote.split()) > QUOTE_MAX_WORDS:
        return False, False, "quote_too_long"
    if not contains(turn["norm_text"], normalise(quote)):
        return False, False, "quote_mismatch"
    return True, True, None


def _cited_moments(item, view, turn):
    """The cited moment entries that actually sit on this turn."""
    found = []
    for mid in item.get("moment_ids") or []:
        moment = view.moments.get(mid)
        if moment is not None and moment["turn_id"] == turn["id"]:
            found.append(moment)
    return found


def _quote_span_kinds(item, turn):
    """Word kinds inside the matched quote span, from the word list."""
    quote_tokens = normalise(item.get("quote") or "").split()
    if not quote_tokens:
        return []
    words = turn["words"]
    normal = [normalise(w.get("word") or "") for w in words]
    token_of = [(i, n) for i, n in enumerate(normal) if n]
    sequence = [n for _, n in token_of]
    for begin in range(len(sequence) - len(quote_tokens) + 1):
        if sequence[begin:begin + len(quote_tokens)] == quote_tokens:
            indices = [token_of[j][0]
                       for j in range(begin, begin + len(quote_tokens))]
            return [words[i].get("kind") for i in indices]
    return []


def check_channel(item, view, turn, speaker_entry):
    """Rule 4 for one surviving item. Returns (ok, reason)."""
    channel = item.get("channel")
    if channel == "prosody":
        for moment in _cited_moments(item, view, turn):
            if any(e.get("feature") not in (None, "medial_fillers")
                   for e in moment["evidence"]):
                return True, None
        return False, "prosody_unsupported"
    if channel == "disfluency":
        for moment in _cited_moments(item, view, turn):
            if any(e.get("feature") == "medial_fillers"
                   for e in moment["evidence"]):
                return True, None
        kinds = [k for k in _quote_span_kinds(item, turn)
                 if k in ("filler", "cutoff", "repetition")]
        if len(kinds) >= 2:
            return True, None
        return False, "disfluency_unsupported"
    if channel == "timing":
        latency = turn.get("reply_latency_s")
        median = (speaker_entry or {}).get("median_reply_latency")
        if (latency is not None and median
                and latency >= TIMING_MIN_GAP_SECONDS
                and latency >= TIMING_MEDIAN_MULTIPLE * median):
            return True, None
        if any(p.get("seconds", 0) >= IN_TURN_PAUSE_SECONDS
               for p in turn.get("pauses") or []):
            return True, None
        return False, "timing_unsupported"
    if channel == "lexical":
        return (True, None) if item.get("_quote_matched") else \
            (False, "lexical_needs_quote")
    if channel == "interaction":
        if _OVERLAP_WORDS.search(item.get("description") or ""):
            begin, end = turn["start_ms"] / 1000.0, turn["end_ms"] / 1000.0
            for event in view_overlap_events(view):
                if event["start"] < end and begin < event["end"]:
                    return True, None
            return False, "interaction_unsupported"
        return True, None
    return False, "unknown_channel"


def view_overlap_events(view):
    return getattr(view, "overlap_events", None) or []


# -- the verifier -----------------------------------------------------------

def _reader_label(context):
    return (context or {}).get("me")


def _speaker_ok(label, report, context):
    """Rule 2. Returns None when fine, else the drop reason."""
    if label == _reader_label(context):
        return "about_reader"
    entry = (report.get("speakers") or {}).get(label)
    if entry is None:
        return "unknown_speaker"
    if (entry.get("baseline_turns") or 0) <= 0:
        return "no_baseline"
    return None


def _verify_insight(insight, view, report, context, result):
    reason = _speaker_ok(insight.get("speaker"), report, context)
    if reason:
        return None, reason

    speaker_entry = report["speakers"].get(insight["speaker"], {})
    surviving = []
    evidence_dropped = []
    saw_quote_reject = False
    for item in insight.get("evidence") or []:
        result.evidence_proposed += 1
        item = dict(item)
        turn = view.turns.get(item.get("turn_id"))
        if turn is None:
            evidence_dropped.append({"turn_id": item.get("turn_id"),
                                     "reason": "turn_missing"})
            continue
        if turn["speaker"] != insight["speaker"]:
            evidence_dropped.append({"turn_id": item["turn_id"],
                                     "reason": "wrong_speaker"})
            continue
        ok, matched, why = check_quote(item, turn)
        if not ok:
            result.evidence_quote_rejected += 1
            saw_quote_reject = True
            evidence_dropped.append({"turn_id": item["turn_id"],
                                     "reason": why})
            continue
        item["_quote_matched"] = matched
        ok, why = check_channel(item, view, turn, speaker_entry)
        if not ok:
            evidence_dropped.append({"turn_id": item["turn_id"],
                                     "reason": why})
            continue
        surviving.append(item)

    channels = sorted({item["channel"] for item in surviving})
    if (len(channels) < MIN_CHANNELS
            or (REQUIRE_NONACOUSTIC
                and not (set(channels) & NONACOUSTIC_CHANNELS))):
        return None, ("quote_mismatch" if saw_quote_reject else "convergence")

    if insight.get("likelihood") not in SHOWABLE_LIKELIHOODS:
        return None, "not_likely_enough"

    alternatives = [a for a in insight.get("alternatives") or []
                    if (a or "").strip()]
    if not alternatives:
        return None, "no_alternative"

    texts = [insight.get("claim", ""), insight.get("follow_up", "")]
    texts.extend(alternatives)
    if any(banned_wording(text) for text in texts):
        return None, "wording"

    verified = _verified_block(surviving, view, report, insight)
    turns_cited = [view.turns[item["turn_id"]] for item in surviving]
    first = min(turns_cited, key=lambda t: t["start_ms"])
    last = max(turns_cited, key=lambda t: t["end_ms"])
    begin_ms = max(first["start_ms"] - int(PLAY_LEAD_SECONDS * 1000), 0)
    end_ms = min(last["end_ms"],
                 begin_ms + int(MAX_AUDIO_RANGE_SECONDS * 1000))

    kept = {k: v for k, v in insight.items() if not k.startswith("_")}
    kept["evidence"] = [
        {k: v for k, v in item.items() if not k.startswith("_")}
        for item in surviving]
    if evidence_dropped:
        kept["evidence_dropped"] = evidence_dropped
    kept["alternatives"] = alternatives
    kept["channels"] = channels
    kept["audio_range"] = {"start_ms": begin_ms, "end_ms": end_ms}
    kept["verified"] = verified
    kept["key"] = _key(insight, surviving)
    return kept, None


def _verified_block(surviving, view, report, insight):
    moments = []
    seen = set()
    for item in surviving:
        for mid in item.get("moment_ids") or []:
            moment = view.moments.get(mid)
            if moment is None or mid in seen:
                continue
            if moment["turn_id"] != item.get("turn_id"):
                continue
            seen.add(mid)
            moments.append({
                "id": mid,
                "turn_id": moment["turn_id"],
                "baseline": moment["baseline"],
                "notes": [{"feature": e.get("feature"), "z": e.get("z"),
                           "n": e.get("n")} for e in moment["evidence"]],
            })
    block = {"moments": moments}
    for item in surviving:
        if item.get("channel") != "timing":
            continue
        turn = view.turns[item["turn_id"]]
        if turn.get("reply_latency_s") is not None:
            block["reply_latency_s"] = turn["reply_latency_s"]
            median = (report["speakers"].get(insight["speaker"]) or {}) \
                .get("median_reply_latency")
            if median is not None:
                block["median_reply_s"] = median
            break
    return block


def _key(insight, surviving):
    first_turn = min((item["turn_id"] for item in surviving), default="")
    raw = "|".join([insight.get("speaker", ""), insight.get("layer", ""),
                    insight.get("topic_id") or "", first_turn])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _rank(insight):
    return (_CONFIDENCE_RANK.get(insight.get("evidence_confidence"), 0),
            len(insight.get("channels") or []),
            _LIKELIHOOD_RANK.get(insight.get("likelihood"), 0))


def _clean_turn_ids(turn_ids, view):
    return [tid for tid in turn_ids or [] if tid in view.turns]


def _clean_lines(lines, view, result, text_key="text"):
    """Rule 11 plus rule 8 for note lines."""
    out = []
    for line in lines or []:
        text = line.get(text_key) or line.get("task") or ""
        if banned_wording(text):
            result.dropped_by_reason["wording_note_line"] = \
                result.dropped_by_reason.get("wording_note_line", 0) + 1
            continue
        cited = line.get("turn_ids")
        cleaned = _clean_turn_ids(cited, view)
        if cited and not cleaned:
            result.dropped_by_reason["unverified_note_line"] = \
                result.dropped_by_reason.get("unverified_note_line", 0) + 1
            continue
        out.append(dict(line, turn_ids=cleaned))
    return out


def verify(draft, view, report, context=None, max_per_call=8,
           max_per_speaker=3):
    """Rules 2 to 11 over a schema-valid draft. Returns a VerifyResult."""
    result = VerifyResult()

    insights = draft.get("insights") or []
    result.proposed = len(insights)
    verified = []
    for insight in insights:
        kept, reason = _verify_insight(insight, view, report, context, result)
        if kept is None:
            result.drop(insight, reason)
        else:
            verified.append(kept)

    # Rule 3 of `working`: what the model itself rejected is recorded too.
    for rejected in (draft.get("working") or {}).get("rejected") or []:
        if isinstance(rejected, dict) and rejected.get("claim"):
            result.dropped.append({"claim": rejected["claim"],
                                   "reason": "model_rejected"})

    # Rule 9: caps, best evidenced first.
    verified.sort(key=_rank, reverse=True)
    per_speaker = {}
    capped = []
    for insight in verified:
        speaker = insight["speaker"]
        if (per_speaker.get(speaker, 0) >= max_per_speaker
                or len(capped) >= max_per_call):
            result.drop(insight, "cap")
            continue
        per_speaker[speaker] = per_speaker.get(speaker, 0) + 1
        capped.append(insight)
    result.kept = capped

    # Rule 11 over notes, topics, speakers and so_what.
    notes = draft.get("notes") or {}
    result.notes = {
        "summary": "" if banned_wording(notes.get("summary", ""))
        else notes.get("summary", ""),
        "decisions": _clean_lines(notes.get("decisions"), view, result),
        "action_items": _clean_lines(notes.get("action_items"), view, result,
                                     text_key="task"),
        "open_questions": _clean_lines(notes.get("open_questions"), view,
                                       result),
        "key_numbers": _clean_lines(notes.get("key_numbers"), view, result),
    }

    reader = _reader_label(context)
    topics = []
    for topic in draft.get("topics") or []:
        spans = [[a, b] for a, b in (topic.get("spans") or [])
                 if a in view.turns and b in view.turns]
        if spans:
            topics.append(dict(topic, spans=spans))
    result.topics = topics

    speakers = []
    for entry in draft.get("speakers") or []:
        if entry.get("label") == reader:
            continue
        cares = []
        for care in entry.get("cares_about") or []:
            cleaned = _clean_turn_ids(care.get("turn_ids"), view)
            if cleaned and not banned_wording(care.get("why", "")):
                cares.append(dict(care, turn_ids=cleaned))
        speakers.append(dict(entry, cares_about=cares))
    result.speakers = speakers

    kept_ids = {i.get("id") for i in result.kept if i.get("id")}
    so_what = []
    for step in draft.get("so_what") or []:
        if banned_wording(step.get("text", "")):
            continue
        refs = [r for r in step.get("refs") or [] if r in kept_ids]
        so_what.append(dict(step, refs=refs))
    result.so_what = so_what

    return result
