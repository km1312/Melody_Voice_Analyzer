"""Derive a readable, model-facing account of a conversation from raw segments.

This is a pure pass over finished pipeline output. No models, no GPU. It can be
run against transcripts already on disk without re-transcribing, which is what
makes thresholds cheap to re-tune.

Five decisions here are load-bearing, and each was measured rather than guessed.
The figures come from a 28.1-minute two-speaker call.

*Turns, not segments.* Whisper cuts roughly every four seconds regardless of who
is speaking. Merging consecutive same-speaker segments turns 446 fragments into
119 turns and stops sentences breaking mid-thought.

*Baselines per speaker.* In the sample call the two speakers sat 0.004 apart on
mean valence and most of a standard deviation apart on arousal. Any absolute
threshold would systematically mislabel one of them.

*A duration gate on emotion.* The emotion model's spread runs widest on the
shortest input: valence SD of 0.147 under a second against 0.096 over five. Since
outlier selection keys on extremity, an ungated selector finds artifacts first. On
the sample call it flagged 27 turns, 63% of them under three seconds, led by
"Yep." at 0.2 seconds. Gating at four seconds of speech left 15, none of them
short, and the list read like a map of the conversation. Gated turns are excluded
from the baselines too, since they otherwise inflate the deviation everything else
is measured against.

*Observations, not verdicts.* Nothing here emits an emotion label. A label
compresses a noisy estimate into a claim a reader cannot reopen. The output
describes what the voice did and leaves the inference to whoever reads it, who has
the words and the surrounding turns that the acoustic model never saw.

*Robust statistics, and the count that produced them.* Baselines are a median and
a scaled median absolute deviation, not a mean and a standard deviation. Everything
measured here is heavy-tailed -- one laugh, one turn the pitch tracker lost -- and
a single outlier inflates an SD enough to suppress every genuine departure for the
rest of the recording. The number of turns behind each reference travels with it
into the output, because twelve turns is a thin baseline and nothing downstream
should be able to forget that.
"""

import math
import re
import statistics as st

# A gap longer than this ends a turn even when the same person resumes. A long
# silence is a boundary regardless of who fills it next.
TURN_BREAK_SECONDS = 2.0

# Emotion and prosody are reported only above this much *speech* in a turn.
# See the module docstring; this is the single most consequential constant here.
EMOTION_MIN_SPEECH = 4.0

# Isolates roughly the top 1% of word-to-word gaps in the sample call, which is a
# more principled cut than a round number.
PAUSE_MIN_SECONDS = 1.0

# A word flanking a claimed pause must itself look plausible. Forced alignment can
# emit a gap where a word simply failed to align, inventing a hesitation that never
# happened, and a false hesitation is worse than a missed one.
MAX_PLAUSIBLE_WORD_SECONDS = 2.0

# Distance from a speaker's own baseline before a turn is worth pointing at.
NOTABLE_SIGMA = 1.5

# Word-voice mismatch is the most promising signal here and the least validated,
# so it clears a deliberately higher bar than everything else.
MISMATCH_SIGMA = 2.0

# A 1.5-sigma threshold against a spread estimated from four turns is a coin
# flip, not a threshold. Twelve is still small, which is why `n` is recorded
# beside every reference and carried into the evidence for every note.
MIN_TURNS_FOR_BASELINE = 12

# Scales the median absolute deviation so that on normally distributed data it
# reproduces the standard deviation, and every existing sigma threshold keeps
# meaning what it meant.
MAD_TO_SIGMA = 1.4826
# The interquartile range needs its own constant for the same reason.
IQR_TO_SIGMA = 1.349

# Long recordings get a second, local reference: a speaker's most recent scored
# turns. A half-hour call is rarely one behaviour, and a baseline drawn across
# the whole of it measures a turn against an average of several conversations.
BASELINE_WINDOW_TURNS = 30
TRAILING_BASELINE_AFTER_SECONDS = 900.0

# Simultaneous speech shorter than this is a boundary artifact, not an event.
MIN_OVERLAP_SECONDS = 0.1

# NaturalTurn (Sci Rep, 2025) merges a speaker's diarized stretches into one
# utterance across gaps up to this long before deciding who held the floor.
UTTERANCE_GAP_SECONDS = 1.5


# -- lexical channel -------------------------------------------------------
# Deliberately separate from the acoustic channel. The emotion model's valence is
# partly mediated by linguistic content (Wagner et al. 2023), so it cannot serve as
# both sides of a words-against-voice comparison. This lexicon is crude; it exists
# to make that comparison well-defined, not to be a sentiment classifier. If NLTK's
# VADER lexicon happens to be installed it is used instead, being far better.
_POSITIVE = {
    "good": 1.0, "great": 1.5, "awesome": 2.0, "excellent": 2.0, "perfect": 1.8,
    "love": 1.8, "like": 0.4, "nice": 1.2, "cool": 1.2, "happy": 1.5, "glad": 1.3,
    "thanks": 1.0, "thank": 1.0, "agree": 1.2, "agreed": 1.2, "yes": 0.6,
    "yeah": 0.4, "sure": 0.5, "definitely": 1.0, "absolutely": 1.3, "right": 0.4,
    "better": 0.9, "best": 1.4, "strong": 0.9, "smart": 1.2, "helpful": 1.2,
    "interesting": 0.8, "fantastic": 2.0, "wonderful": 1.8, "sweet": 1.0,
    "appreciate": 1.4, "exciting": 1.5, "excited": 1.5, "impressive": 1.5,
}
_NEGATIVE = {
    "bad": -1.3, "wrong": -1.2, "hard": -0.7, "difficult": -1.0, "problem": -1.2,
    "issue": -0.9, "concern": -1.0, "concerned": -1.1, "worry": -1.2,
    "worried": -1.2, "unfortunately": -1.3, "fail": -1.6, "failed": -1.6,
    "weak": -1.1, "worse": -1.3, "worst": -1.8, "confusing": -1.1,
    "confused": -1.1, "unclear": -0.9, "disappointing": -1.6, "sorry": -0.6,
    "no": -0.5, "not": -0.4, "never": -0.7, "cannot": -0.6, "stuck": -1.1,
    "annoying": -1.4, "frustrating": -1.5, "frustrated": -1.5, "risk": -0.7,
}
_NEGATORS = {"not", "no", "never", "cannot", "don't", "doesn't", "didn't",
             "isn't", "wasn't", "won't", "can't", "nothing"}

_WORD = re.compile(r"[a-z']+")
_vader = None
_vader_tried = False


def _vader_analyzer():
    """Return NLTK's VADER analyser if its lexicon is already present, else None.

    Never downloads. The app promises to run offline after first setup, and a
    silent network call from an analysis pass would break that.
    """
    global _vader, _vader_tried
    if _vader_tried:
        return _vader
    _vader_tried = True
    try:
        from nltk.sentiment.vader import SentimentIntensityAnalyzer

        _vader = SentimentIntensityAnalyzer()
    except Exception:
        _vader = None
    return _vader


def lexical_sentiment(text):
    """Score text from -1 to 1 on what the words say, ignoring how they sounded."""
    analyzer = _vader_analyzer()
    if analyzer is not None:
        try:
            return round(float(analyzer.polarity_scores(text)["compound"]), 3)
        except Exception:
            pass

    words = _WORD.findall((text or "").lower())
    if not words:
        return 0.0
    total = 0.0
    for index, word in enumerate(words):
        score = _POSITIVE.get(word, 0.0) + _NEGATIVE.get(word, 0.0)
        if score and index and words[index - 1] in _NEGATORS:
            score = -0.6 * score
        total += score
    # Normalised the way VADER normalises, so the two sources stay comparable.
    return round(float(total / math.sqrt(total * total + 15.0)), 3)


# -- turns -----------------------------------------------------------------
def _speech_seconds(segments):
    return sum(max(float(s.get("end", 0)) - float(s.get("start", 0)), 0.0)
               for s in segments)


def build_turns(segments):
    """Merge consecutive same-speaker segments, breaking on a long silence."""
    turns = []
    for segment in segments:
        speaker = segment.get("speaker", "UNKNOWN")
        start = float(segment.get("start", 0.0) or 0.0)
        previous = turns[-1] if turns else None
        continues = (
            previous is not None
            and previous["speaker"] == speaker
            and start - previous["end"] <= TURN_BREAK_SECONDS
        )
        if continues:
            previous["segments"].append(segment)
            previous["end"] = float(segment.get("end", previous["end"]))
        else:
            turns.append({
                "speaker": speaker,
                "start": start,
                "end": float(segment.get("end", start)),
                "segments": [segment],
            })

    for index, turn in enumerate(turns):
        turn["index"] = index
        turn["text"] = " ".join(
            (s.get("text") or "").strip() for s in turn["segments"]).strip()
        turn["speech_seconds"] = round(_speech_seconds(turn["segments"]), 2)
        turn["word_count"] = sum(
            len([w for w in (s.get("words") or []) if w.get("kind") != "event"])
            or len((s.get("text") or "").split())
            for s in turn["segments"])
    return turns


# A Whisper segment is cut where a sustained run of its words was diarized to
# someone else. A run has to clear both bounds: fewer words or less time than
# this is a backchannel, and stays with whoever held the floor.
SPLIT_MIN_WORDS = 4
SPLIT_MIN_SECONDS = 1.0


def split_segments_by_speaker(segments, min_words=SPLIT_MIN_WORDS,
                              min_seconds=SPLIT_MIN_SECONDS):
    """Cut segments where a sustained run of their words belongs to another speaker.

    whisperx labels a segment by whichever speaker was diarized for most of its
    span, and without an initial prompt Whisper's segments can run 20-30 s and
    straddle a speaker change. On the 2026-09-17 call the words already carried
    the right speaker from the exclusive diarization and the segment label
    overrode them: one speaker's question sat inside the other's 340-word
    turn, two turns opened with the end of the other speaker's sentence, and
    6% of the shorter speaker's words in his baseline were the other's. Cutting
    at sustained runs took mislabelled words from 142 to 50 of 5,406 on that
    call and created no new turn under 1.5 s. Short runs are absorbed by the
    neighbouring sustained run, so a "yeah, right" dropped into someone else's
    sentence stays where it was said. Segments whose words carry no speaker are
    returned untouched, and the operation is idempotent.
    """
    out = []
    for segment in segments:
        words = segment.get("words") or []
        label = segment.get("speaker", "UNKNOWN")
        if len(words) < 2 or not any("speaker" in w for w in words):
            out.append(segment)
            continue
        runs = []
        for word in words:
            speaker = word.get("speaker", label)
            if runs and runs[-1]["speaker"] == speaker:
                runs[-1]["words"].append(word)
            else:
                runs.append({"speaker": speaker, "words": [word]})

        def sustained(run):
            first, last = run["words"][0], run["words"][-1]
            try:
                seconds = float(last.get("end", 0.0)) - float(first.get("start", 0.0))
            except (TypeError, ValueError):
                seconds = 0.0
            return len(run["words"]) >= min_words and seconds >= min_seconds

        if len({r["speaker"] for r in runs if sustained(r)}) < 2:
            out.append(segment)
            continue
        pieces, pending = [], []
        for run in runs:
            if not sustained(run):
                pending.extend(run["words"])
                continue
            if pieces and pieces[-1]["speaker"] == run["speaker"]:
                pieces[-1]["words"].extend(pending + run["words"])
            else:
                if pieces:
                    pieces[-1]["words"].extend(pending)
                    pending = []
                pieces.append({"speaker": run["speaker"], "words": pending + run["words"]})
            pending = []
        pieces[-1]["words"].extend(pending)
        for piece in pieces:
            piece_words = piece["words"]
            out.append(dict(segment, speaker=piece["speaker"], words=piece_words,
                            start=piece_words[0].get("start", segment.get("start")),
                            end=piece_words[-1].get("end", segment.get("end")),
                            text=" ".join((w.get("word") or "").strip() for w in piece_words)))
    return out


def _words(turn):
    out = []
    for segment in turn["segments"]:
        for word in segment.get("words") or []:
            if word.get("start") is None or word.get("end") is None:
                continue
            out.append(word)
    return out


# Token kinds the verbatim merge writes. Fillers and vocalisations are sounds a
# speaker made; events are not speech; neither belongs in a measure of how words
# were stressed or what they said.
_NON_LEXICAL = {"filler", "vocalisation", "event"}
_EVENT_TEXT = re.compile(r"\[[^\]]*\]")
_FILLER_TEXT = re.compile(r"\b(?:um|uh|uhm|umm|uhh|erm|er|ehm)\b[,.]?", re.IGNORECASE)


def _lexical_words(turn):
    return [w for w in _words(turn) if w.get("kind") not in _NON_LEXICAL]


def _is_verbatim(turns):
    return any(w.get("kind") for t in turns for s in t["segments"]
               for w in (s.get("words") or []))


def _disfluency(turn):
    """Filled pauses, and where in the sentence they fell.

    Position is the point. Kirkland et al. (Interspeech 2022) found a *medial*
    filled pause -- one with words on both sides of it, inside the same sentence --
    the strongest single cue listeners use to judge low confidence, ahead of high
    pitch and slow speech. A filler before the first word of a sentence is
    ordinary planning and reads very differently.

    Sentences here are Whisper's segments, which whisperx splits at sentence
    punctuation. Vocalisations such as "mhm" are counted separately: they are
    mostly backchannels, not hesitation.
    """
    counts = {"filled_pauses": 0, "initial": 0, "medial": 0, "final": 0,
              "repetitions": 0, "cutoffs": 0, "vocalisations": 0}
    events = {}
    for segment in turn["segments"]:
        words = segment.get("words") or []
        lexical = [i for i, w in enumerate(words) if w.get("kind") not in _NON_LEXICAL]
        for i, word in enumerate(words):
            kind = word.get("kind")
            if kind == "filler":
                counts["filled_pauses"] += 1
                before = any(j < i for j in lexical)
                after = any(j > i for j in lexical)
                counts["medial" if before and after else
                       "initial" if after else "final"] += 1
            elif kind == "repetition":
                counts["repetitions"] += 1
            elif kind == "cutoff":
                counts["cutoffs"] += 1
            elif kind == "vocalisation":
                counts["vocalisations"] += 1
            elif kind == "event":
                name = (word.get("word") or "").strip("[] ").lower() or "event"
                events[name] = events.get(name, 0) + 1
    words = max(turn["word_count"], 1)
    counts["per_100_words"] = round(100.0 * counts["filled_pauses"] / words, 2)
    counts["medial_per_100_words"] = round(100.0 * counts["medial"] / words, 2)
    if events:
        counts["events"] = events
    return counts


def _turn_stance(turn):
    """The learned stance reading the pipeline stamped on this turn, if any."""
    if turn["speech_seconds"] < EMOTION_MIN_SPEECH:
        return None
    for segment in turn["segments"]:
        reading = segment.get("stance")
        if reading and reading.get("certainty") is not None:
            return {"certainty": reading["certainty"],
                    "probabilities": reading.get("probabilities")}
    return None


def _segment_spans(turn):
    return [(float(s.get("start", 0.0)), float(s.get("end", 0.0)))
            for s in turn["segments"]]


def extract_pauses(turn):
    """Silences inside a turn, with alignment artifacts filtered out.

    29% of the long gaps in the sample call fell mid-sentence, invisible at segment
    boundaries, which is the whole reason word timings are kept.

    Each pause records whether it sits inside a single segment. Only those count
    against articulation rate: a gap that spans two segments is already absent from
    the summed segment durations, and subtracting it again would invent speed.
    """
    words = _words(turn)
    spans = _segment_spans(turn)
    pauses = []
    for before, after in zip(words, words[1:]):
        gap = float(after["start"]) - float(before["end"])
        if gap < PAUSE_MIN_SECONDS:
            continue
        # Guard: a word that itself spans an implausible stretch is a sign the
        # aligner lost its place, and the "pause" beside it is not real.
        before_len = float(before["end"]) - float(before["start"])
        after_len = float(after["end"]) - float(after["start"])
        if before_len > MAX_PLAUSIBLE_WORD_SECONDS or after_len > MAX_PLAUSIBLE_WORD_SECONDS:
            continue
        if before_len <= 0 or after_len <= 0:
            continue
        start, end = float(before["end"]), float(after["start"])
        inside = any(lo <= start and end <= hi for lo, hi in spans)
        pauses.append({
            "at": round(start, 2),
            "seconds": round(gap, 2),
            "within_segment": inside,
            "after_word": (before.get("word") or "").strip(),
            "before_word": (after.get("word") or "").strip(),
        })
    return pauses


def pace(turn, pauses):
    """Overall rate and articulation rate.

    One figure conflates "spoke slowly" with "stopped to think". The 4.7-second
    hesitation in the sample call would drag a turn's rate down and misreport it
    as slow speech.

    Overall rate runs against wall-clock duration, so every silence counts against
    it. Articulation runs against time the speaker was audibly producing words.
    """
    words = turn["word_count"]
    wall = max(turn["end"] - turn["start"], 0.01)
    voiced = max(turn["speech_seconds"], 0.01)
    held = sum(p["seconds"] for p in pauses if p["within_segment"])
    speaking = max(voiced - held, 0.01)
    return {
        "word_count": words,
        "speech_seconds": round(voiced, 2),
        "wpm": round(words / (wall / 60.0), 1),
        "articulation_wpm": round(words / (speaking / 60.0), 1),
    }


def _turn_emotion(turn):
    """The turn's emotion, gated on length.

    Dominance is dropped: it correlated 0.931 with arousal in the sample call, so
    it is not an independent dimension. Valence is carried but is not treated as
    acoustic evidence downstream, being partly mediated by word content.

    The pipeline now scores each turn in one forward pass and stamps the span it
    used onto every segment of that turn, so the usual case is to read the number
    it already measured. The duration-weighted path below is what a transcript
    produced before that change still needs, and is kept so old `.json` files can
    be re-analysed without re-transcribing.
    """
    if turn["speech_seconds"] < EMOTION_MIN_SPEECH:
        return None

    scoped = [s["emotion"] for s in turn["segments"]
              if s.get("emotion") and s["emotion"].get("measured_over")]
    if scoped:
        source = scoped[0]
        result = {"arousal": source.get("arousal")}
        if "valence" in source:
            result["valence"] = source["valence"]
        return result if result["arousal"] is not None else None

    usable = [s for s in turn["segments"]
              if s.get("emotion")
              and (float(s.get("end", 0)) - float(s.get("start", 0))) >= 1.0]
    if not usable:
        return None
    weight = sum(float(s["end"]) - float(s["start"]) for s in usable)
    if weight <= 0:
        return None

    def weighted(key):
        total = sum((float(s["end"]) - float(s["start"])) * s["emotion"][key]
                    for s in usable if key in s["emotion"])
        return round(total / weight, 3)

    result = {"arousal": weighted("arousal")}
    if any("valence" in s["emotion"] for s in usable):
        result["valence"] = weighted("valence")
    return result


def track_covers(turns, track):
    """How much of the transcript the supplied audio actually reaches.

    Nothing else here checks that a transcript and an audio file belong together,
    and a mismatch is silent: prosody would simply be measured at the wrong
    offsets. This caught a real case where a transcript ran six minutes past the
    recording it was paired with, so the coverage is recorded in the output rather
    than left for someone to notice.
    """
    if track is None or not len(track) or not turns:
        return None
    # Both ends matter once trimming is in play: the track can start partway into
    # the media as well as stop short of it.
    begins = getattr(track, "start_seconds", 0.0)
    ends = getattr(track, "end_seconds", len(track) * track.hop_seconds)
    first = min(float(t["start"]) for t in turns)
    last = max(float(t["end"]) for t in turns)
    inside = sum(1 for t in turns
                 if float(t["start"]) >= begins - 1.0 and float(t["end"]) <= ends + 1.0)
    coverage = {
        "audio_seconds": round(ends - begins, 1),
        "transcript_seconds": round(last - first, 1),
        "turns_within_audio": inside,
        "turns_total": len(turns),
        "complete": inside == len(turns),
    }
    if begins:
        coverage["audio_starts_at"] = round(begins, 1)
    return coverage


def annotate(turns, track=None):
    """Attach pauses, pace, emotion, prosody, stance, disfluency and lexical
    sentiment to each turn."""
    from . import prosody as prosody_module

    # Only a transcript that went through the verbatim pass can say how many
    # fillers a turn had. On a Whisper-only transcript "0" would be a claim the
    # recognizer never earned, so the field is absent instead.
    verbatim = _is_verbatim(turns)
    for turn in turns:
        pauses = extract_pauses(turn)
        turn["pauses"] = pauses
        turn["pace"] = pace(turn, pauses)
        turn["emotion"] = _turn_emotion(turn)
        turn["stance"] = _turn_stance(turn)
        # Sentiment reads the words, not the "um"s or the "[laughter]".
        turn["lexical"] = lexical_sentiment(
            _FILLER_TEXT.sub("", _EVENT_TEXT.sub("", turn["text"])))
        turn["disfluency"] = _disfluency(turn) if verbatim else None
        turn["prosody"] = None
        if track is not None and turn["speech_seconds"] >= EMOTION_MIN_SPEECH:
            # Word timings buy the word-internal intensity figures; without them
            # the rest of the prosody is unchanged. Fillers are left out: the
            # stress pattern of "um" says nothing about how words were delivered.
            turn["prosody"] = prosody_module.turn_features(
                track, turn["start"], turn["end"], words=_lexical_words(turn))
    return turns


# -- baselines -------------------------------------------------------------
# Every comparable feature in one place, so a reference, an observation and a
# baseline cannot drift apart as features are added.
_FEATURES = {
    "arousal": lambda t: (t["emotion"] or {}).get("arousal"),
    "valence": lambda t: (t["emotion"] or {}).get("valence"),
    "articulation": lambda t: t["pace"]["articulation_wpm"],
    "f0_range": lambda t: (t["prosody"] or {}).get("f0_range_semitones"),
    "loudness_sd": lambda t: (t["prosody"] or {}).get("loudness_db_sd"),
    "terminal_rise": lambda t: (t["prosody"] or {}).get("f0_terminal_rise"),
    "intensity_onset": lambda t: (t["prosody"] or {}).get("intensity_onset_db"),
    "intensity_mid": lambda t: (t["prosody"] or {}).get("intensity_mid_db"),
    "certainty": lambda t: (t.get("stance") or {}).get("certainty"),
    "medial_fillers": lambda t: (t.get("disfluency") or {}).get("medial_per_100_words"),
    "lexical": lambda t: t["lexical"],
}


def _spread(values):
    """A centre and a scale for one feature, estimated robustly.

    This used the mean and the population standard deviation, which are the wrong
    estimators for this data. One laugh, or one turn on which the pitch tracker
    lost its place, inflates the SD enough to suppress every genuine departure for
    the rest of the recording -- the most plausible reason the word-voice mismatch
    check has never fired on a real call. The median and the median absolute
    deviation have a breakdown point of 50%: half the turns would have to be
    outliers before they move at all.

    The MAD is scaled so that on normally distributed data it reproduces the SD,
    which leaves NOTABLE_SIGMA and MISMATCH_SIGMA meaning what they meant.
    """
    if len(values) < 2:
        return None
    centre = st.median(values)
    mad = st.median([abs(value - centre) for value in values])
    scale = MAD_TO_SIGMA * mad
    if scale <= 0:
        # More than half the turns share one value -- lexical sentiment is exactly
        # zero on most short turns -- so the MAD is zero and every turn would look
        # infinitely unusual. The interquartile range survives that; when it does
        # not either, there is no spread here and no note should fire.
        scale = _iqr_scale(values)
    return {
        "median": round(centre, 3),
        "scale": round(scale, 4),
        "mad": round(mad, 4),
        "n": len(values),
    }


def _iqr_scale(values):
    try:
        quartiles = st.quantiles(values, n=4)
    except (st.StatisticsError, ValueError):
        return 0.0
    return max((quartiles[2] - quartiles[0]) / IQR_TO_SIGMA, 0.0)


def _collect(turns, getter):
    out = []
    for turn in turns:
        value = getter(turn)
        if value is not None and isinstance(value, (int, float)) and math.isfinite(value):
            out.append(float(value))
    return out


def _reference(scored):
    """The comparable half of a baseline: one centre and scale per feature."""
    return {name: _spread(_collect(scored, getter))
            for name, getter in _FEATURES.items()}


def baselines(turns, total_speech):
    """Per-speaker reference points, computed only over turns clearing the gate."""
    by_speaker = {}
    for turn in turns:
        by_speaker.setdefault(turn["speaker"], []).append(turn)

    result = {}
    for speaker, speaker_turns in by_speaker.items():
        scored = [t for t in speaker_turns if t["speech_seconds"] >= EMOTION_MIN_SPEECH]
        speech = sum(t["speech_seconds"] for t in speaker_turns)
        latencies = [t["reply_latency"] for t in speaker_turns
                     if t.get("reply_latency") is not None]

        entry = {
            "turns": len(speaker_turns),
            "scored_turns": len(scored),
            "speech_seconds": round(speech, 1),
            "talk_share": round(speech / total_speech, 3) if total_speech else None,
            "median_turn_seconds": round(
                st.median([t["speech_seconds"] for t in speaker_turns]), 2),
            "median_reply_latency": round(st.median(latencies), 2) if latencies else None,
            "articulation_wpm": round(
                st.median([t["pace"]["articulation_wpm"] for t in speaker_turns]), 1),
            "baseline_turns": len(scored) if len(scored) >= MIN_TURNS_FOR_BASELINE else 0,
        }
        if len(scored) >= MIN_TURNS_FOR_BASELINE:
            entry.update(_reference(scored))
        result[speaker] = entry
    return result


def trailing_references(turns, media_seconds):
    """A local reference per turn, from that speaker's most recent scored turns.

    People warm up, calls change subject, and a recording long enough for that to
    happen is not one behaviour to be averaged. Above
    TRAILING_BASELINE_AFTER_SECONDS each scored turn is compared against the
    preceding BASELINE_WINDOW_TURNS of the same speaker instead of against the
    whole call; below it, or before enough turns have accumulated, the global
    baseline is used and says so.

    The current turn is deliberately not in its own window. A reference that
    contains the sample being tested pulls itself toward that sample, which is
    exactly backwards for a measure of how unusual the sample is.
    """
    if (media_seconds or 0) < TRAILING_BASELINE_AFTER_SECONDS:
        return {}

    history = {}
    out = {}
    for turn in turns:
        if turn["speech_seconds"] < EMOTION_MIN_SPEECH:
            continue
        previous = history.setdefault(turn["speaker"], [])
        if len(previous) >= MIN_TURNS_FOR_BASELINE:
            out[turn["index"]] = _reference(previous[-BASELINE_WINDOW_TURNS:])
        previous.append(turn)
    return out


def _z(value, reference):
    if value is None or not reference:
        return None
    scale = reference.get("scale")
    if not scale:
        return None
    return round((value - reference["median"]) / scale, 2)


def _departure(value, reference):
    """`_z`, but only where the reference behind it is thick enough to mean much.

    MIN_TURNS_FOR_BASELINE counts a speaker's scored turns, and that is not the
    same as the number of turns that produced a value for any given feature.
    Terminal pitch is the case that matters: it needs two separate stretches of
    voiced speech and returns nothing on the turns where it cannot find them, so
    a speaker with 29 scored turns had a terminal-rise reference resting on 8.
    A note fired off that reference looks exactly like a note fired off 29.
    """
    if not reference or (reference.get("n") or 0) < MIN_TURNS_FOR_BASELINE:
        return None
    return _z(value, reference)


def _latencies(turns):
    """Silence before a turn begins, when the floor changed hands."""
    for previous, turn in zip(turns, turns[1:]):
        turn["reply_latency"] = (round(turn["start"] - previous["end"], 2)
                                 if previous["speaker"] != turn["speaker"] else None)
    if turns:
        turns[0]["reply_latency"] = None


# -- selection -------------------------------------------------------------
# One row per note: the feature it reads, and the wording for a high and a low
# departure. Wording describes the measurement, never an emotional state.
# "Louder and faster than usual" is something a reader can weigh; "animated" is a
# verdict they cannot reopen.
#
# Terminal contour is judged against the speaker's own habit, like everything
# else here. A fixed threshold flags whoever happens to end sentences on a rise
# as a matter of style, which says nothing about any single turn.
#
# There is deliberately no F0 standard deviation note. Choi et al. (2025) found
# F0 SD uncorrelated between openSMILE, Praat and librosa on the same recordings
# (r = -0.54 to 0.14), where F0 percentiles agree at 0.96 and above, so it would
# be a note about which library was installed.
_NOTES = (
    ("articulation", "faster than usual", "slower than usual"),
    ("arousal", "more energy than usual", "less energy than usual"),
    ("f0_range", "pitch unusually varied", "pitch unusually flat"),
    ("loudness_sd", "more emphasis than usual", "unusually even delivery"),
    ("terminal_rise", "ends higher than usual", "ends lower than usual"),
    # Learned, not measured: see stance.py. One-sided because the head detects
    # nervousness well and confidence barely at all. "Sounds" because it was
    # trained on what listeners heard, not on what speakers felt.
    ("certainty", None, "sounds less certain than usual"),
    # One-sided. A turn with fewer mid-sentence fillers than a speaker who rarely
    # uses any is not an event.
    ("medial_fillers", "more mid-sentence hesitation than usual", None),
)

# How far the head must lean towards "nervous" before its reading can be a note at
# all. On the SpeechSense test set nervous clips average -0.74 on this axis and
# every other stance sits near zero, so -0.25 is well clear of both.
CERTAINTY_FLOOR = -0.25

# Effects too small to mean anything, whatever the z-score says.
#
# Medial fillers: half the scored turns on the sample call had none, and one
# speaker's median was zero, so against that speaker a single "um" scored well
# past the threshold. Two is the least that can be called a pattern in one turn.
#
# Certainty: on the sample call the stance head, trained on synthesised speech,
# read 52 of 58 real turns as "warm", and the axis never left -0.08 to 0.000.
# Against a speaker spread that narrow (scale 0.001), z-scoring produced eleven
# "sounds less certain" notes at z from -2.5 to -44. Read back, about half were
# genuinely hesitant turns ("What's the word I'm looking for? It's like s- s-
# standard") and half were ordinary questions or narration, and the most extreme
# z was a plain question. The ordering carries something; values that small do
# not carry enough to annotate, and across all turns the axis did not correlate
# with mid-sentence hesitation (r = 0.015). So a note also needs the head to lean
# nervous in absolute terms.
_NOTE_GUARDS = {
    "medial_fillers": lambda turn: ((turn.get("disfluency") or {}).get("medial") or 0) >= 2,
    "certainty": lambda turn: ((turn.get("stance") or {}).get("certainty") or 0.0)
    <= CERTAINTY_FLOOR,
}

# Word-internal intensity is measured, baselined and written to the
# `.analysis.json`, but it does not yet produce a note. Goupil et al. put it
# among the cues listeners read as certainty, and it behaves like the features
# that do annotate -- on the sample call it would have fired on 14 of 57 scored
# turns (25%), against arousal's 13 (23%). The reason it is held back is not its
# rate but that nothing has yet read those fourteen turns to see whether they
# sound like leaning in, and this is the newest measure here. Add either row to
# `_NOTES` once someone has:
#
#     ("intensity_mid", "leans into words more than usual",
#      "flatter word stress than usual"),
#     ("intensity_onset", "hits words harder at the start than usual",
#      "eases into words more than usual"),
#
# Onset and mid are not the same signal -- they correlate -0.41 on the sample
# call -- so turning one on says nothing about the other.


def _observations(turn, reference):
    """How this turn departed from the speaker, with the arithmetic that says so.

    Returns one entry per note, each carrying the z-score that fired it and the
    number of turns the reference was estimated from. `n` travels with the note
    because twelve turns is a thin baseline and a reader deserves to know how
    thin: the same 1.6 sigma means something different against 12 turns and 40.
    """
    found = []
    for feature, high, low in _NOTES:
        value = _FEATURES[feature](turn)
        spread = reference.get(feature)
        score = _departure(value, spread)
        if score is None or abs(score) < NOTABLE_SIGMA:
            continue
        if (score > 0 and high is None) or (score < 0 and low is None):
            continue
        guard = _NOTE_GUARDS.get(feature)
        if guard is not None and not guard(turn):
            continue
        found.append({
            "feature": feature,
            "note": high if score > 0 else low,
            "z": score,
            "n": spread.get("n"),
        })
    return found


def _pause_notes(turn):
    """Pause wording for the index only; the transcript body marks them exactly."""
    long_pauses = [p for p in turn["pauses"] if p["seconds"] >= 2.0]
    if len(long_pauses) >= 2:
        return ["{0} long pauses".format(len(long_pauses))]
    if long_pauses:
        return ["pauses for {0:.1f}s".format(long_pauses[0]["seconds"])]
    return []


def _mismatch(turn, reference):
    """Words and voice disagreeing, expressed as an observation.

    Held to a higher bar than everything else because it is the least validated
    signal in this module. Requires both channels to be present and both to be
    genuinely far from the speaker's own baseline.
    """
    lexical_z = _departure(turn["lexical"], reference.get("lexical"))
    arousal_z = _departure((turn["emotion"] or {}).get("arousal"),
                           reference.get("arousal"))
    if lexical_z is None or arousal_z is None:
        return None
    if abs(lexical_z) < MISMATCH_SIGMA or abs(arousal_z) < MISMATCH_SIGMA:
        return None
    if (lexical_z > 0) == (arousal_z > 0):
        return None
    return {
        "feature": "mismatch",
        "note": ("positive words, subdued delivery" if lexical_z > 0
                 else "negative words, energetic delivery"),
        "z": lexical_z,
        "arousal_z": arousal_z,
        "n": (reference.get("lexical") or {}).get("n"),
    }


def select_moments(turns, speaker_baselines, local=None):
    """Turns worth pointing a reader at, with the evidence that flagged them.

    `local` supplies a trailing-window reference per turn where one could be
    built. It is preferred over the whole-call baseline when present, because on
    a long recording the whole-call figure is an average over several different
    stretches of conversation; the scope actually used is recorded on the moment
    so the two can be told apart afterwards.
    """
    local = local or {}
    moments = []
    for turn in turns:
        if turn["speech_seconds"] < EMOTION_MIN_SPEECH:
            continue
        trailing = local.get(turn["index"])
        reference = trailing or speaker_baselines.get(turn["speaker"]) or {}
        evidence = _observations(turn, reference)
        mismatch = _mismatch(turn, reference)
        if mismatch:
            evidence.append(mismatch)
        pauses = _pause_notes(turn)
        if not evidence and not pauses:
            continue
        voice = [item["note"] for item in evidence]
        moments.append({
            "turn": turn["index"],
            "start": turn["start"],
            "speaker": turn["speaker"],
            "observations": voice + pauses,
            "voice_observations": voice,
            "evidence": evidence,
            "baseline": "trailing" if trailing else "call",
            "mismatch": any(item["feature"] == "mismatch" for item in evidence),
            "preview": turn["text"][:80],
        })
    return moments


# -- overlap ---------------------------------------------------------------
def utterances(rows, gap=UTTERANCE_GAP_SECONDS):
    """Diarized stretches merged, per speaker, into utterances.

    pyannote emits a speaker's turn in pieces wherever they drew breath. The
    question a backchannel test asks -- did this person's contribution fall
    wholly inside someone else's -- is about the whole contribution, so the
    pieces have to be put back together first. The gap is NaturalTurn's pause
    parameter.
    """
    grouped = {}
    for row in sorted(rows or [], key=lambda r: (str(r["speaker"]), float(r["start"]))):
        speaker = str(row["speaker"])
        start, end = float(row["start"]), float(row["end"])
        bucket = grouped.setdefault(speaker, [])
        if bucket and start - bucket[-1]["end"] <= gap:
            bucket[-1]["end"] = max(bucket[-1]["end"], end)
        else:
            bucket.append({"speaker": speaker, "start": start, "end": end})
    merged = [u for bucket in grouped.values() for u in bucket]
    merged.sort(key=lambda u: (u["start"], u["end"]))
    return merged


def overlap_events(rows):
    """Simultaneous speech, each stretch classified as backchannel or floor-taking.

    This is the NaturalTurn rule (Scientific Reports, 2025), which operates on
    exactly what this pipeline already has -- diarized timestamps -- and needs no
    further model: a listener utterance that falls wholly inside another
    speaker's utterance is a backchannel, and anything else that overlaps is
    someone taking the floor. The distinction is the whole point of measuring
    overlap at all. "Right, yeah" dropped into a pause is not the same event as
    cutting in over the end of a sentence, and a reply-latency figure conflates
    them: an invited turn and an intrusive one both show up as a small number.

    Overlap is computed here rather than from whisperx's segments because those
    come from voice-activity chunks and cannot overlap by construction, so
    simultaneous speech is not merely unmeasured there, it is unmeasurable.

    Telling an invited turn from an intrusive one needs more than this rule.
    Voice Activity Projection was tested for it and did not deliver: its
    projection for the incoming speaker was lower before a floor-take than before
    a backchannel on both test calls (AUC 0.42 and 0.33). README.md, "Speakers
    and overlap", has the figures.
    """
    merged = utterances(rows)
    events = []
    for index, first in enumerate(merged):
        for second in merged[index + 1:]:
            if second["start"] >= first["end"]:
                break
            if second["speaker"] == first["speaker"]:
                continue
            begin = max(first["start"], second["start"])
            finish = min(first["end"], second["end"])
            if finish - begin <= MIN_OVERLAP_SECONDS:
                continue
            # `second` starts no earlier than `first`, so it is the one arriving
            # into speech that was already under way.
            inside = second["end"] <= first["end"]
            events.append({
                "start": round(begin, 2),
                "end": round(finish, 2),
                "seconds": round(finish - begin, 2),
                "speakers": sorted([first["speaker"], second["speaker"]]),
                "by": second["speaker"],
                "over": first["speaker"],
                "kind": "backchannel" if inside else "floor_taking",
            })
    events.sort(key=lambda e: e["start"])
    return events


def _overlap_summary(meta, turns):
    """Fold the classified overlaps into something reportable."""
    overlaps = (meta or {}).get("overlaps") or []
    if not overlaps:
        return None
    per_speaker = {}
    for item in overlaps:
        for name in item.get("speakers", []):
            per_speaker[name] = round(per_speaker.get(name, 0.0) + item["seconds"], 2)
    total = round(sum(o["seconds"] for o in overlaps), 2)
    speech = sum(t["speech_seconds"] for t in turns) or 1.0

    summary = {
        "count": len(overlaps),
        "seconds": total,
        "share_of_speech": round(total / speech, 4),
        "seconds_per_speaker": per_speaker,
        "longest": max(overlaps, key=lambda o: o["seconds"]),
    }

    kinds = [o.get("kind") for o in overlaps if o.get("kind")]
    if kinds:
        backchannels = [o for o in overlaps if o.get("kind") == "backchannel"]
        taking = [o for o in overlaps if o.get("kind") == "floor_taking"]
        summary["backchannels"] = len(backchannels)
        summary["floor_taking"] = len(taking)
        by_speaker = {}
        for item in taking:
            name = item.get("by")
            if name:
                by_speaker[name] = by_speaker.get(name, 0) + 1
        summary["floor_taking_by_speaker"] = by_speaker
        summary["rule"] = "naturalturn"
    return summary


def summarise(turns, speaker_baselines, meta):
    total_speech = sum(t["speech_seconds"] for t in turns)
    changes = sum(1 for a, b in zip(turns, turns[1:]) if a["speaker"] != b["speaker"])
    longest = max(turns, key=lambda t: t["speech_seconds"], default=None)
    return {
        "media_seconds": meta.get("media_seconds"),
        "turns": len(turns),
        "speakers": len(speaker_baselines),
        "speech_seconds": round(total_speech, 1),
        "speaker_changes": changes,
        "seconds_between_changes": (round(total_speech / changes, 1)
                                    if changes else None),
        "longest_turn": ({"speaker": longest["speaker"], "start": longest["start"],
                          "seconds": longest["speech_seconds"]} if longest else None),
        "scored_turns": sum(1 for t in turns
                            if t["speech_seconds"] >= EMOTION_MIN_SPEECH),
        "emotion_gate_seconds": EMOTION_MIN_SPEECH,
        "emotion_scope": (meta or {}).get("emotion_scope", "segment"),
    }


def _public(turn):
    """A turn without its source segments.

    The raw segments carry every word timing, which is 72% of the original file.
    They belong in the `.json`, not repeated in a derived one; everything the
    analysis concluded from them is already recorded above.
    """
    return {k: v for k, v in turn.items() if k != "segments"}


def analyse(segments, meta=None, track=None):
    """Turn raw pipeline segments into the derived account. Pure and fast."""
    meta = dict(meta or {})
    # A transcript re-analysed from disk can carry the diarization without the
    # overlaps derived from it, so derive them here rather than losing them.
    if meta.get("diarization") and not meta.get("overlaps"):
        meta["overlaps"] = overlap_events(meta["diarization"])

    turns = build_turns(split_segments_by_speaker(segments or []))
    _latencies(turns)
    annotate(turns, track=track)
    total_speech = sum(t["speech_seconds"] for t in turns)
    speaker_baselines = baselines(turns, total_speech)
    local = trailing_references(turns, meta.get("media_seconds"))
    moments = select_moments(turns, speaker_baselines, local=local)
    result = {
        "summary": summarise(turns, speaker_baselines, meta),
        "speakers": speaker_baselines,
        "moments": moments,
        "turns": [_public(t) for t in turns],
        "settings": {
            "turn_break_seconds": TURN_BREAK_SECONDS,
            "emotion_min_speech": EMOTION_MIN_SPEECH,
            "pause_min_seconds": PAUSE_MIN_SECONDS,
            "notable_sigma": NOTABLE_SIGMA,
            "mismatch_sigma": MISMATCH_SIGMA,
            "min_turns_for_baseline": MIN_TURNS_FOR_BASELINE,
            "split_min_words": SPLIT_MIN_WORDS,
            "split_min_seconds": SPLIT_MIN_SECONDS,
            "baseline_estimator": "median+mad",
            "trailing_baseline_turns": (BASELINE_WINDOW_TURNS if local else None),
            "lexical_source": "vader" if _vader_analyzer() else "builtin",
            # Baselines from one tracker are not comparable with turns measured
            # by another, so the output says which instrument produced them.
            "pitch_tracker": getattr(track, "estimator", None),
        },
    }
    coverage = track_covers(turns, track)
    if coverage is not None:
        result["audio_coverage"] = coverage
    overlap = _overlap_summary(meta, turns)
    if overlap is not None:
        result["overlap"] = overlap
        result["overlap_events"] = meta.get("overlaps") or []
    return result
