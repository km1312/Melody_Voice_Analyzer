"""The verbatim pass, and the merge that makes it safe to use by default.

Whisper transcribes what a speaker meant. It deletes filled pauses, restarts,
repetitions and cut-off words, and those deletions are the most direct evidence
of hesitation in speech: a medial filled pause is the strongest single cue to low
confidence in the listener literature (Kirkland et al. 2022), ahead of pitch and
rate. On the sample call Whisper kept 32 filled pauses in 4,388 tokens, 0.73%,
against roughly 2% in ordinary conversation.

CrisperWhisper transcribes what was actually said, but it is the wrong source for
proper nouns. Version 1.0 produced "Chachi" for ChatGPT, "Rubik" for rubric and
"Zoo" for Zoom, and lost ESG, OpenRouter and neobanks entirely; a hotword list
sent it into a loop. So neither recognizer is right alone, and this module runs
both and merges them word by word:

* content words come from Whisper wherever the two disagree on a non-filler token;
* fillers, cut-offs, repetitions and vocal events come from CrisperWhisper;
* timings come from CrisperWhisper's own cross-attention alignment (~30-40 ms mean
  boundary error) wherever it heard the same word, and from Whisper's wav2vec2
  alignment where only Whisper did.

CrisperWhisper 2.0 runs on the PyTorch/transformers backend with stock
transformers. Its CTranslate2 backend needs a forked ctranslate2 with Linux-only
wheels, so on Windows it cannot run through whisperx, and does not try to.

Licence: the standard 2.0 weights are under the Nyra Health Non-Commercial
Research License. Hotword boosting is Pro-only, which is the other reason the
vocabulary list stays on the Whisper side.
"""

import difflib
import re

VERBATIM_MODEL_ID = "nyralabs/CrisperWhisper2.0_large"
VERBATIM_LICENCE = "Nyra Health Non-Commercial Research License"

# Hesitation fillers. These are what the filled-pause features count.
FILLERS = {"um", "uh", "uhm", "umm", "uhh", "erm", "er", "ehm", "em"}
# Non-lexical vocalisations that are not hesitations: mostly backchannels. Kept in
# the transcript, never counted as filled pauses.
VOCALISATIONS = {"hmm", "hm", "mm", "mhm", "mmm", "mm-hmm", "uh-huh", "mhmm"}

# A verbatim-only word the merge could not place within this distance of its
# Whisper neighbours is treated as misplaced rather than inserted.
PLACEMENT_SLACK_SECONDS = 0.5
# A "match" between the two passes further apart in time than this is taken to be
# two different occurrences of a common word. It was 1.0 s, which was wrong: on
# the sample call the gap between matched words decays smoothly (4.8% over 0.5 s,
# 1.4% over 1 s, 0.2% over 2 s, none over 3.2 s) with no second cluster, so every
# match was the same word and the disagreement was the aligners'. Rejecting those
# kept Whisper's timing for "Because" at the moment CrisperWhisper heard "that's",
# a word Whisper had dropped, and invented a two-second pause.
MATCH_SLACK_SECONDS = 5.0
# More consecutive copies of one word than this is a decoder loop, not a stutter.
MAX_REPEATS = 4
# A verbatim-only run up to this long is kept as a restart when it contains the
# words Whisper resumes with (or has just said). Longer runs are something else.
MAX_RESTART_WORDS = 12
# A restart match on nothing but these words is coincidence, not a restart.
_COMMON = {"you", "know", "like", "i", "the", "a", "and", "it", "its", "that", "to",
           "of", "so", "yeah", "um", "uh", "is", "in", "we", "just", "or", "but"}
# A filler Whisper wrote this close to one CrisperWhisper wrote is the same sound.
FILLER_MATCH_SECONDS = 0.8

_EDGE = re.compile(r"^[^\w\[\]-]+|[^\w\[\]-]+$")


def _norm(word):
    """Lower-case, strip surrounding punctuation, keep brackets and hyphens."""
    return _EDGE.sub("", (word or "").strip().lower())


def classify(word):
    """What kind of token a verbatim word is: filler, vocalisation, event,
    cutoff or content."""
    token = _norm(word)
    bare = token.strip("[]")
    if bare in FILLERS:
        return "filler"
    if bare in VOCALISATIONS:
        return "vocalisation"
    if token.startswith("[") and token.endswith("]"):
        return "event"
    if len(token) > 1 and token.endswith("-"):
        return "cutoff"
    return "content"


def render(word, kind):
    """How a verbatim-only token is written into the merged transcript.

    Fillers and vocalisations are written as plain words, the way a transcriber
    would; events keep their brackets so they cannot be mistaken for speech.
    """
    token = _norm(word)
    if kind in ("filler", "vocalisation"):
        return token.strip("[]")
    if kind == "event":
        return "[" + token.strip("[]") + "]"
    return (word or "").strip()


class VerbatimPass:
    """CrisperWhisper 2.0, loaded once and reused across files."""

    def __init__(self, device="cuda", compute_type="float16", log=None,
                 model_id=VERBATIM_MODEL_ID, token=None):
        from crisperwhisper import CrisperWhisperModel
        from huggingface_hub import snapshot_download

        self.log = log or (lambda message: None)
        self.model_id = model_id
        dtype = "float32" if device == "cpu" else (
            "float16" if "float16" in (compute_type or "") else compute_type)

        # Fetch the whole snapshot first, with the token. Loading by repo id lets
        # transformers download file by file, and when one of those requests was
        # rate-limited it went on without generation_config.json: the model still
        # transcribed, with default decoding settings and no alignment heads, and
        # only word timestamps failed to say so.
        local = snapshot_download(model_id, token=token or None)
        self.model = CrisperWhisperModel(
            local, backend="transformers", compute_type=dtype, device=device)
        heads = getattr(getattr(self.model, "_engine", None), "default_alignment_heads", None)
        if not heads:
            raise RuntimeError("{0} loaded without alignment heads, so it cannot "
                               "produce word timings".format(model_id))

        self.device = device
        self._park()

    def _network(self):
        return getattr(getattr(self.model, "_engine", None), "model", None)

    def _park(self):
        """Move the weights off the GPU and hand back everything the pass cached.

        CrisperWhisper peaks at about 7 GB on a half-hour call: 3 GB of weights
        and the rest attention activations kept for word timing, which PyTorch's
        allocator holds on to after the pass. Left there, it pushed a 16 GB card
        to 15.9 GB, and the diarization that followed -- 42 seconds on its own --
        was still running six minutes later with Windows paging GPU memory to
        system RAM. The verbatim pass is one stage of many, so it only holds the
        GPU while it runs.
        """
        network = self._network()
        if network is None or self.device == "cpu":
            return
        import torch

        network.to("cpu")
        torch.cuda.empty_cache()

    def _unpark(self):
        network = self._network()
        if network is not None and self.device != "cpu":
            import torch

            # Whatever the previous file's later stages left in PyTorch's cache
            # goes back first: on the sample batch the second file began with
            # 10.5 GB in use, and 7 GB more does not fit on a 16 GB card.
            torch.cuda.empty_cache()
            network.to(self.device)

    def words(self, audio, sr, language="en"):
        """Verbatim words with CrisperWhisper's own timestamps, in array time."""
        self._unpark()
        try:
            result = self.model.transcribe(
                audio, sr=sr, language=language or "en", mode="verbatim",
                word_timestamps=True)
        finally:
            self._park()
        out = []
        for item in result.words or []:
            if item.start is None or item.end is None:
                continue
            text = (item.word or "").strip()
            if not text:
                continue
            out.append({"word": text, "start": float(item.start),
                        "end": float(item.end), "kind": classify(text)})
        return out

    def close(self):
        self.model = None


# -- merge ---------------------------------------------------------------------
def _clean_words(segments):
    """Whisper's words, flattened, each remembering its segment."""
    flat = []
    for index, segment in enumerate(segments):
        for word in segment.get("words") or []:
            text = (word.get("word") or "").strip()
            if not text:
                continue
            flat.append({
                "word": text,
                "start": word.get("start"),
                "end": word.get("end"),
                "score": word.get("score"),
                "segment": index,
            })
    return flat


def _is_repetition(tokens, before, after):
    """Whether a run of verbatim-only content words repeats its neighbours.

    "we we need" against Whisper's "we need" leaves one "we" unmatched; it is a
    repetition because the same word follows it. A repeated phrase ("I think I
    think") is tested the same way against the equal-length run on either side.

    Longer runs are tested as restarts: a speaker who says "as a VC fund, it
    would be okay to write... or like, as a VC fund" gets one "as a VC fund"
    from Whisper, and difflib matches it to the second, leaving a run with a
    lead-in that no equal-length test can see. The run is a restart when two or
    three consecutive words of it are the words Whisper resumes with, or the
    ones it has just said, and those words are not all function words.
    """
    if not tokens:
        return False
    run = [_norm(t) for t in tokens]
    size = len(run)
    if size <= 3:
        follow = [_norm(w) for w in after[:size]]
        precede = [_norm(w) for w in before[-size:]] if len(before) >= size else []
        if run == follow or run == precede:
            return True
    if size < 2 or size > MAX_RESTART_WORDS:
        return False
    follow = [_norm(w) for w in after[:3]]
    precede = [_norm(w) for w in before[-3:]]
    for width in (3, 2):
        anchors = [follow[:width]]
        if len(precede) >= width:
            anchors.append(precede[-width:])
        for anchor in anchors:
            if len(anchor) < width or all(w in _COMMON for w in anchor):
                continue
            if any(run[i:i + width] == anchor for i in range(size - width + 1)):
                return True
    return False


def merge(segments, verbatim, stats=None):
    """Merge Whisper's aligned segments with CrisperWhisper's verbatim words.

    `segments` is whisperx's aligned output and is returned in the same shape, so
    everything downstream -- diarization, emotion, analysis, writers -- is
    unchanged. Verbatim-only tokens carry a `kind`: filler, vocalisation, event,
    cutoff or repetition. Whisper's words carry none.

    Three steps. The two streams are matched on content words only: fillers and
    events have no counterpart on the Whisper side by construction, so letting
    them into the match would only give difflib more ways to go wrong. The match
    is then walked in order, taking Whisper's word wherever the two disagree and
    slotting every filler, cut-off, repetition and event back in where
    CrisperWhisper put it. Finally everything is put on one clock.

    That last step exists because of a real failure. Whisper's wav2vec2 timings
    run about 0.12 s later than CrisperWhisper's on the sample call, so mixing the
    two and sorting by time turned "I got to look at some stuff" into "I look got
    to at some stuff". Order now comes from the walk, never from timestamps, and
    any word without a CrisperWhisper timing is fitted between the neighbours
    that have one.
    """
    stats = stats if stats is not None else {}
    for key in ("matched", "whisper_only", "replaced", "kept_filler",
                "kept_vocalisation", "kept_event", "kept_cutoff",
                "kept_repetition", "dropped_content", "dropped_misplaced",
                "dropped_loop", "far_matches", "whisper_fillers_merged",
                "whisper_fillers_kept"):
        stats.setdefault(key, 0)

    everything = _clean_words(segments)
    if not everything or not verbatim:
        return segments
    # Whisper keeps a few fillers of its own ("Um, so..."), and CrisperWhisper
    # hears the same sound. Matched as content, each became two words: 31 of
    # Whisper's 32 fillers on the sample call sat within a fraction of a second of
    # one of CrisperWhisper's, and the transcript read "Um, um correct". They are
    # set aside here and only come back where CrisperWhisper heard no filler.
    clean = [w for w in everything if classify(w["word"]) != "filler"]
    whisper_fillers = [w for w in everything if classify(w["word"]) == "filler"]
    if not clean:
        return segments

    content_index = [i for i, w in enumerate(verbatim) if w["kind"] == "content"]
    clean_keys = [_norm(w["word"]) for w in clean]
    verbatim_keys = [_norm(verbatim[i]["word"]) for i in content_index]
    matcher = difflib.SequenceMatcher(None, clean_keys, verbatim_keys, autojunk=False)

    walk = []             # ordered tokens: dicts with word, start, end, native, ...
    cursor = [0]          # next verbatim index not yet considered for slotting

    def slot_up_to(stop):
        """Emit non-content verbatim tokens with index in [cursor, stop)."""
        for v in range(cursor[0], stop):
            token = verbatim[v]
            if token["kind"] == "content":
                continue
            walk.append({
                "word": render(token["word"], token["kind"]),
                "start": token["start"], "end": token["end"],
                "kind": token["kind"], "native": True,
            })
            stats["kept_" + token["kind"]] += 1
        cursor[0] = max(cursor[0], stop)

    def whisper_word(index, native=None):
        word = dict(clean[index])
        word["hint"] = (word.pop("start"), word.pop("end"))
        word["native"] = False
        if native is not None:
            word["start"], word["end"], word["native"] = native["start"], native["end"], True
        return word

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                v = content_index[j1 + offset]
                slot_up_to(v)
                cursor[0] = v + 1
                hint = clean[i1 + offset].get("start")
                native = verbatim[v]
                if hint is None or abs(native["start"] - float(hint)) <= MATCH_SLACK_SECONDS:
                    walk.append(whisper_word(i1 + offset, native))
                    stats["matched"] += 1
                else:
                    # The same word, but not the same occurrence of it.
                    walk.append(whisper_word(i1 + offset))
                    stats["far_matches"] += 1

        elif tag == "replace":
            first, last = content_index[j1], content_index[j2 - 1]
            if i2 - i1 == j2 - j1:
                # Word for word: "challenges" for "challenge", "13" for
                # "thirteen". Each Whisper word stands where its counterpart was
                # heard, with any filler between them kept in place.
                for offset in range(i2 - i1):
                    v = content_index[j1 + offset]
                    slot_up_to(v)
                    cursor[0] = v + 1
                    walk.append(whisper_word(i1 + offset, verbatim[v]))
            else:
                slot_up_to(first)
                # Fillers inside an uneven replaced stretch go before Whisper's
                # words: their place among words that do not correspond is
                # unknowable.
                slot_up_to(last + 1)
                for i in range(i1, i2):
                    walk.append(whisper_word(i))
            stats["replaced"] += i2 - i1

        elif tag == "delete":
            for i in range(i1, i2):
                walk.append(whisper_word(i))
                stats["whisper_only"] += 1

        elif tag == "insert":
            tokens = [verbatim[content_index[j]]["word"] for j in range(j1, j2)]
            before = [w["word"] for w in walk if not w.get("kind")]
            after = [c["word"] for c in clean[i1:]]
            if _is_repetition(tokens, before, after):
                for j in range(j1, j2):
                    v = content_index[j]
                    slot_up_to(v)
                    token = verbatim[v]
                    walk.append({"word": token["word"], "start": token["start"],
                                 "end": token["end"], "kind": "repetition",
                                 "native": True})
                    cursor[0] = v + 1
                    stats["kept_repetition"] += 1
            else:
                slot_up_to(content_index[j2 - 1] + 1)
                stats["dropped_content"] += j2 - j1

    slot_up_to(len(verbatim))
    _one_clock(walk)
    _restore_whisper_fillers(walk, whisper_fillers, stats)
    return _rebuild(segments, walk, stats)


def _restore_whisper_fillers(walk, fillers, stats, window=FILLER_MATCH_SECONDS):
    """Put back the fillers only Whisper heard, tagged as fillers; drop the rest."""
    heard = sorted(float(w["start"]) for w in walk if w.get("kind") == "filler")
    for filler in fillers:
        at = filler.get("start")
        if at is None:
            continue
        at = float(at)
        if any(abs(t - at) <= window for t in heard):
            stats["whisper_fillers_merged"] += 1
            continue
        position = next((i for i, w in enumerate(walk) if float(w["start"]) > at), len(walk))
        low = float(walk[position - 1]["end"]) if position > 0 else at
        high = float(walk[position]["start"]) if position < len(walk) else float(filler["end"])
        start = min(max(at, low), max(high, low))
        end = min(max(float(filler.get("end") or at), start), max(high, start))
        walk.insert(position, {"word": render(filler["word"], "filler"), "start": start,
                               "end": end, "kind": "filler", "native": False,
                               "segment": filler["segment"]})
        stats["whisper_fillers_kept"] += 1


def _one_clock(walk):
    """Fit every word without a CrisperWhisper timing between neighbours that have one.

    A Whisper word keeps its own wav2vec2 timing, clamped into the gap between
    the nearest CrisperWhisper-timed words on either side, whenever the gap has
    room for it. It is never spread across a long gap: the first version did that
    whenever a timing overhung its neighbour by a few milliseconds, and moved a
    sentence 15 seconds early across a silence. Nor is a run packed together,
    which erases the silences inside it.

    When the gap is too small -- a word Whisper heard squeezed between two words
    CrisperWhisper put back to back -- it borrows up to half of each neighbour.
    Without that, 133 of Whisper's words on the sample call came out zero seconds
    long, and the pause detector, which rightly distrusts zero-length words,
    stopped reporting the silences beside them.

    Starts are then made non-decreasing and each end is cut at the next start, so
    time order and word order cannot disagree.
    """
    count = len(walk)
    position = 0
    while position < count:
        if walk[position]["native"]:
            position += 1
            continue
        run_end = position
        while run_end < count and not walk[run_end]["native"]:
            run_end += 1
        run = walk[position:run_end]
        before = walk[position - 1] if position > 0 else None
        after = walk[run_end] if run_end < count else None

        wanted = []
        for word in run:
            hint = word.get("hint") or (None, None)
            if hint[0] is not None and hint[1] is not None and float(hint[1]) > float(hint[0]):
                wanted.append(float(hint[1]) - float(hint[0]))
            else:
                wanted.append(max(0.06 * len(word["word"]), 0.04))
        needed = sum(wanted)

        hints = [w.get("hint") or (None, None) for w in run]
        known = [h for h in hints if h[0] is not None and h[1] is not None]
        low = float(before["end"]) if before else (float(known[0][0]) if known else 0.0)
        high = float(after["start"]) if after else (
            float(known[-1][1]) if known else low + needed)
        high = max(high, low)

        placed = None
        if high - low >= 0.5 * needed:
            # Every word keeps its own aligner timing, clamped into the window
            # one at a time, so silences inside the run survive. A word the
            # aligner never timed follows the previous word at its nominal
            # length. Packing the run instead moved "13" 3.9 s early and left a
            # four-second pause that never happened.
            placed = []
            clock = low
            for hint, length in zip(hints, wanted):
                if hint[0] is not None and hint[1] is not None:
                    begin, finish = float(hint[0]), float(hint[1])
                else:
                    begin, finish = clock, clock + length
                start = min(max(begin, low), high)
                end = min(max(finish, start), high)
                placed.append((start, end))
                clock = end
            # A timing that fell outside the window collapses onto its edge.
            # That word was not where the aligner said, so the run is packed.
            if any(end - start < 0.2 * length
                   for (start, end), length in zip(placed, wanted)):
                placed = None

        if placed is None:
            if high - low < 0.5 * needed:
                short = 0.5 * needed - (high - low)
                if before:
                    give = min(short / 2.0, 0.5 * (float(before["end"]) - float(before["start"])))
                    before["end"] = float(before["end"]) - give
                    low -= give
                if after:
                    give = min(short / 2.0, 0.5 * (float(after["end"]) - float(after["start"])))
                    after["start"] = float(after["start"]) + give
                    high += give
            scale = min((high - low) / needed, 1.0) if needed else 0.0
            # Packed words sit where the aligner centred them, inside the window.
            centre = (sum((float(h[0]) + float(h[1])) / 2.0 for h in known) / len(known)
                      if known else (low + high) / 2.0)
            span = needed * scale
            clock = min(max(centre - span / 2.0, low), high - span)
            placed = []
            for length in wanted:
                placed.append((clock, clock + length * scale))
                clock += length * scale

        for word, (start, end) in zip(run, placed):
            word["start"], word["end"] = start, end
        position = run_end

    # Starts never go backwards, and a word never runs into the next one. Clamping
    # each start to the previous *end* instead would let one over-long word push
    # every later word late.
    for previous, current in zip(walk, walk[1:]):
        current["start"] = max(float(current["start"]), float(previous["start"]))
        previous["end"] = min(float(previous["end"]), current["start"])
        previous["end"] = max(previous["end"], float(previous["start"]))
        current["end"] = max(float(current["end"]), current["start"])


def _rebuild(segments, walk, stats):
    """Put the walk back into Whisper's segments, in walk order."""
    owners = [w.get("segment") for w in walk]
    last_seen = None
    previous_owner = [None] * len(walk)
    for i, owner in enumerate(owners):
        previous_owner[i] = last_seen
        if owner is not None:
            last_seen = i
    next_seen = None
    next_owner = [None] * len(walk)
    for i in range(len(walk) - 1, -1, -1):
        next_owner[i] = next_seen
        if owners[i] is not None:
            next_seen = i

    rebuilt = [dict(segment, words=[]) for segment in segments]
    for i, word in enumerate(walk):
        owner = owners[i]
        if owner is None:
            before, after = previous_owner[i], next_owner[i]
            if before is not None and after is not None and owners[before] == owners[after]:
                owner = owners[before]
            else:
                gap_before = (word["start"] - walk[before]["end"]) if before is not None else float("inf")
                gap_after = (walk[after]["start"] - word["end"]) if after is not None else float("inf")
                if min(gap_before, gap_after) > PLACEMENT_SLACK_SECONDS + 4.5:
                    stats["dropped_misplaced"] += 1
                    continue
                # A filler between two sentences is usually the speaker planning
                # the next one, so a tie goes forward.
                owner = owners[before] if gap_before < gap_after else owners[after]
        out = {"word": word["word"], "start": round(word["start"], 3),
               "end": round(word["end"], 3)}
        if word.get("score") is not None:
            out["score"] = word["score"]
        if word.get("kind"):
            out["kind"] = word["kind"]
        rebuilt[owner]["words"].append(out)

    for segment in rebuilt:
        words = _drop_loops(segment["words"], stats)
        segment["words"] = words
        if words:
            segment["start"] = words[0]["start"]
            segment["end"] = words[-1]["end"]
            segment["text"] = " ".join(w["word"] for w in words)
    return rebuilt


def _drop_loops(words, stats):
    """Remove runs of one inserted token long enough to be a decoder loop."""
    out = []
    run = 0
    for word in words:
        same = out and word.get("kind") and _norm(word["word"]) == _norm(out[-1]["word"])
        run = run + 1 if same else 0
        if run >= MAX_REPEATS:
            stats["dropped_loop"] += 1
            continue
        out.append(word)
    return out


def summary(segments):
    """Counts of what the verbatim pass contributed, for the metadata."""
    kinds = {}
    for segment in segments:
        for word in segment.get("words") or []:
            kind = word.get("kind")
            if kind:
                kinds[kind] = kinds.get(kind, 0) + 1
    return kinds
