"""Write a finished transcript out in the formats the user asked for."""

import csv
import json
import re
from pathlib import Path

FORMAT_LABELS = {
    "json": "JSON (full data)",
    "md": "Analysis (.md, for a language model)",
    "txt": "Text transcript",
    "srt": "Subtitles (.srt)",
    "csv": "Spreadsheet (.csv)",
}
FORMAT_ORDER = ["json", "md", "txt", "srt", "csv"]


def _timestamp(seconds, comma=False):
    seconds = max(float(seconds), 0.0)
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:  # rounding can tip a whole second
        millis = 999
    sep = "," if comma else "."
    return "{0:02d}:{1:02d}:{2:02d}{3}{4:03d}".format(hours, minutes, secs, sep, millis)


def unique_path(path: Path) -> Path:
    """Never clobber an existing output; append (2), (3)... instead."""
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    counter = 2
    while True:
        candidate = parent / "{0} ({1}){2}".format(stem, counter, suffix)
        if not candidate.exists():
            return candidate
        counter += 1


def write_json(segments, meta, path: Path) -> Path:
    """A bare list of segments, matching what VoiceModel.py produced."""
    path = unique_path(path.with_suffix(".json"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(segments, f, indent=2, ensure_ascii=False)
    return path


def write_txt(segments, meta, path: Path) -> Path:
    path = unique_path(path.with_suffix(".txt"))
    with open(path, "w", encoding="utf-8") as f:
        f.write("Transcript of {0}\n".format(Path(meta.get("source", "")).name))
        f.write("Model {0} on {1} ({2})\n".format(
            meta.get("model", "?"), meta.get("device_name", "?"),
            meta.get("compute_type", "?")))
        f.write("{0} segments".format(meta.get("segments", 0)))
        if meta.get("speakers"):
            f.write(", {0} speakers".format(meta["speakers"]))
        f.write("\n" + "=" * 70 + "\n\n")

        last_speaker = None
        for seg in segments:
            speaker = seg.get("speaker", "UNKNOWN")
            if speaker != last_speaker:
                f.write("\n[{0}] {1}\n".format(_timestamp(seg["start"]), speaker))
                last_speaker = speaker
            f.write(seg.get("text", "") + "\n")
    return path


def write_srt(segments, meta, path: Path) -> Path:
    path = unique_path(path.with_suffix(".srt"))
    with open(path, "w", encoding="utf-8") as f:
        index = 1
        for seg in segments:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            speaker = seg.get("speaker", "")
            if speaker and speaker != "UNKNOWN":
                text = "[{0}] {1}".format(speaker, text)
            f.write("{0}\n{1} --> {2}\n{3}\n\n".format(
                index,
                _timestamp(seg["start"], comma=True),
                _timestamp(seg["end"], comma=True),
                text,
            ))
            index += 1
    return path


def write_csv(segments, meta, path: Path) -> Path:
    path = unique_path(path.with_suffix(".csv"))
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "start", "end", "duration_seconds", "speaker", "text",
            "word_count", "wpm", "valence", "arousal", "dominance",
        ])
        for seg in segments:
            pacing = seg.get("pacing", {})
            emotion = seg.get("emotion", {})
            writer.writerow([
                seg.get("start", ""),
                seg.get("end", ""),
                pacing.get("duration_seconds", ""),
                seg.get("speaker", ""),
                seg.get("text", ""),
                pacing.get("word_count", ""),
                pacing.get("wpm", ""),
                emotion.get("valence", ""),
                emotion.get("arousal", ""),
                emotion.get("dominance", ""),
            ])
    return path



# -- the model-facing view -------------------------------------------------
# Markdown rather than JSON, deliberately. It costs fewer tokens than JSON or XML
# and is read more accurately, and the raw `.json` still holds everything for any
# consumer that wants numbers.
LEGEND = """## How to read this

Times are mm:ss from the start of the recording. Speaker labels come from
automatic diarization and are sometimes wrong, so treat a surprising attribution
as a possible error rather than a fact. `(...2.4s)` marks a silence of that length
inside a turn.

Parenthetical notes after a speaker name are acoustic measurements, expressed as
distance from that speaker's own baseline for this recording. They describe how
the voice sounded. They are not claims about what the speaker felt, and the
inference is yours to make. Turns shorter than {gate:.0f} seconds of speech carry
no note at all, because the measurement is unreliable below that length. Their
absence means nothing was measured, not that nothing happened.

That baseline is a median and a median absolute deviation over the turns in the
Baseline column below, so it is only as trustworthy as that count is large. A
note fires at {sigma:.1f} deviations, and each entry in the Moments index carries
the z-score that fired it and the number of turns behind the comparison.{window}

A line such as `(...5.7s silence)` between two turns is the gap before the
next turn began. Valence, dominance and the stance model's class probabilities
are measured per turn and deliberately not presented here as evidence; {numbers}
"""

NUMBERS_BESIDE = ("the numbers behind every note, and those signals, are in the "
                  "`.analysis.json` beside this file.")
NUMBERS_ABSENT = ("the numbers behind every note, and those signals, are written "
                  "to a `.analysis.json` when the JSON format is on.")

# A gap between turns at least this long is written into the transcript.
TURN_GAP_MARK_SECONDS = 2.0


def _mmss(seconds):
    seconds = max(int(float(seconds)), 0)
    return "{0:02d}:{1:02d}".format(seconds // 60, seconds % 60)


def _speaker_table(speakers):
    """One row per speaker, including how many turns their baseline rests on.

    The Baseline column is the honest half of every note in this file: a
    departure measured against twelve turns is a weaker claim than the same
    departure measured against forty, and a zero there means no note could fire
    for that speaker at all.
    """
    rows = ["| | Talk time | Turns | Baseline | Articulation | Median reply |",
            "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name in sorted(speakers, key=lambda n: -(speakers[n].get("talk_share") or 0)):
        entry = speakers[name]
        share = entry.get("talk_share")
        latency = entry.get("median_reply_latency")
        baseline = entry.get("baseline_turns", 0)
        rows.append("| {0} | {1} | {2} | {3} | {4:.0f} wpm | {5} |".format(
            name,
            "{0:.0f}%".format(100 * share) if share is not None else "-",
            entry.get("turns", 0),
            "{0} turns".format(baseline) if baseline else "none",
            entry.get("articulation_wpm") or 0,
            "{0:.2f}s".format(latency) if latency is not None else "-",
        ))
    return rows


def _turn_body(turn):
    """Turn text with long silences marked where they actually fell.

    Markers are placed by matching the word each pause followed, scanning forward
    so that a word occurring several times resolves in time order. The match is
    anchored on word boundaries: without that, a pause after "the" lands inside
    the next "together" and splits it.
    """
    pauses = sorted(turn.get("pauses") or [], key=lambda p: p["at"])
    text = turn.get("text", "")
    if not pauses:
        return text

    pieces = []
    cursor = 0
    for pause in pauses:
        anchor = (pause.get("after_word") or "").strip()
        if not anchor:
            continue
        lead = r"\b" if anchor[:1].isalnum() else ""
        match = re.search(lead + re.escape(anchor) + r"(?!\w)", text[cursor:])
        if not match:
            continue
        at = cursor + match.end()
        pieces.append(text[cursor:at])
        pieces.append(" (...{0:.1f}s)".format(pause["seconds"]))
        cursor = at
    pieces.append(text[cursor:])
    return "".join(pieces)


def write_md(segments, meta, path: Path) -> Path:
    """The analysis view: a header a model can trust and a body it can read."""
    from .analysis import EMOTION_MIN_SPEECH, NOTABLE_SIGMA

    report = meta.get("analysis") or _analysis_for(segments, meta)
    summary = report["summary"]
    path = unique_path(path.with_suffix(".md"))

    # The body marks every pause inline and exactly, so repeating pause notes in
    # the turn header would be duplication a model has to reconcile. The Moments
    # index keeps them, where they earn their place as something to scan for.
    notes = {m["turn"]: m.get("voice_observations") or []
             for m in report["moments"]}

    with open(path, "w", encoding="utf-8") as f:
        title = Path(meta.get("source", "")).stem or "Recording"
        minutes = (summary.get("media_seconds") or 0) / 60.0
        f.write("# {0} - {1:.1f} min - {2} speakers - {3} turns\n\n".format(
            title, minutes, summary.get("speakers", 0), summary.get("turns", 0)))

        window = report.get("settings", {}).get("trailing_baseline_turns")
        f.write(LEGEND.format(
            gate=EMOTION_MIN_SPEECH, sigma=NOTABLE_SIGMA,
            window=("" if not window else
                    " This recording is long enough that later turns are\n"
                    "compared against the speaker's most recent {0} scored turns rather than\n"
                    "against the whole call.".format(window)),
            numbers=(NUMBERS_BESIDE if meta.get("numbers_file", True) else NUMBERS_ABSENT)))
        extras = _legend_extras(report)
        if extras:
            f.write("\n" + extras + "\n")
        f.write("\n## Participants\n\n")
        f.write("\n".join(_speaker_table(report["speakers"])))
        f.write("\n")

        overlap = report.get("overlap")
        if overlap:
            f.write("\nSpeakers held the floor at once {0} times, {1:.0f}s in "
                    "total, {2:.1f}% of all speech. The longest ran {3:.1f}s "
                    "at {4}.".format(
                        overlap["count"], overlap["seconds"],
                        100 * overlap["share_of_speech"],
                        overlap["longest"]["seconds"],
                        _mmss(overlap["longest"]["start"])))
            f.write(_overlap_kinds(overlap) + "\n")

        if report["moments"]:
            f.write("\n## Moments\n\n")
            for moment in report["moments"]:
                f.write("- {0} {1} - {2}\n".format(
                    _mmss(moment["start"]), moment["speaker"], _moment_line(moment)))

        f.write("\n## Transcript\n\n")
        previous_end = None
        for turn in report["turns"]:
            note = notes.get(turn["index"])
            gap = (float(turn["start"]) - previous_end) if previous_end is not None else 0.0
            if gap >= TURN_GAP_MARK_SECONDS:
                f.write("(...{0:.1f}s silence)\n\n".format(gap))
            f.write("[{0}] {1}{2}: {3}\n\n".format(
                _mmss(turn["start"]),
                turn["speaker"],
                " ({0})".format("; ".join(note)) if note else "",
                _turn_body(turn),
            ))
            previous_end = float(turn.get("end", turn["start"]))
    return path


def _moment_line(moment):
    """The index entry: each note with the arithmetic behind it, then pauses.

    The transcript body keeps the note bare so it reads as prose; the index is
    where a reader decides what to trust, so it says how far the turn sat from
    the baseline and how many turns that baseline rests on.
    """
    parts = []
    for item in moment.get("evidence") or []:
        detail = "z {0:+.1f}".format(item["z"]) if item.get("z") is not None else ""
        if item.get("n"):
            detail += (", " if detail else "") + "n {0}".format(item["n"])
        parts.append("{0} ({1})".format(item["note"], detail) if detail else item["note"])
    voice = set(moment.get("voice_observations") or [])
    parts.extend(o for o in moment.get("observations") or [] if o not in voice)
    return "; ".join(parts)


VERBATIM_NOTE = """The transcript is verbatim. "um" and "uh" are filled pauses the
speaker actually made, repeated words and cut-off words ending in "-" are kept as
spoken, and bracketed terms such as [laughter] or [breath] are sounds, not words.
A filled pause in the middle of a sentence is a stronger sign of hesitation than
one before the sentence starts."""

STANCE_NOTE = """"Sounds less certain than usual" comes from a learned model rather
than a measurement. It was trained on synthesised speech, mostly registers a
nervous-sounding delivery, and is compared against this speaker's own turns.
Weigh it as one listener's impression, not as a finding."""


def _legend_extras(report):
    """Legend paragraphs that apply only when their evidence is in the file."""
    turns = report.get("turns") or []
    parts = []
    if any(t.get("disfluency") is not None for t in turns):
        parts.append(VERBATIM_NOTE)
    # Only when the note actually appears: the head rarely clears its floor on
    # real speech, and a paragraph explaining an absent note is tokens spent on
    # nothing.
    if any(item.get("feature") == "certainty"
           for moment in report.get("moments") or []
           for item in moment.get("evidence") or []):
        parts.append(STANCE_NOTE)
    return "\n\n".join(parts)


def _overlap_kinds(overlap):
    """The backchannel / floor-taking split, when the rule could be applied.

    Two people speaking at once is one measurement covering two different events.
    A listener dropping "right, yeah" into someone else's turn and a listener
    cutting across the end of it look identical in a total, and only the second
    is worth a reader's attention.
    """
    if "backchannels" not in overlap:
        return ""
    taking = overlap.get("floor_taking", 0)
    parts = [" Of those, {0} were backchannels inside another speaker's turn "
             "and {1} were someone taking the floor".format(
                 overlap.get("backchannels", 0), taking)]
    by_speaker = overlap.get("floor_taking_by_speaker") or {}
    if taking and by_speaker:
        parts.append(" ({0})".format(", ".join(
            "{0} {1}".format(name, count) for name, count
            in sorted(by_speaker.items(), key=lambda kv: -kv[1]))))
    parts.append(".")
    return "".join(parts)


def _analysis_for(segments, meta):
    from .analysis import analyse

    return analyse(segments, meta)


def write_analysis(segments, meta, path: Path) -> Path:
    """The structured sibling. Everything the `.md` glosses, as numbers."""
    report = meta.get("analysis") or _analysis_for(segments, meta)
    path = unique_path(path.with_suffix(".analysis.json"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return path


WRITERS = {
    "json": write_json,
    "md": write_md,
    "txt": write_txt,
    "srt": write_srt,
    "csv": write_csv,
}


def write_all(segments, meta, output_dir: Path, stem: str, formats):
    """Write every requested format. Returns the list of paths created."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # The analysis is shared by the `.md` and its structured sibling, and is not
    # free, so compute it once. The pipeline usually supplies it already, having
    # had the audio in hand for the prosody pass.
    if "md" in formats and not meta.get("analysis"):
        meta = dict(meta)
        meta["analysis"] = _analysis_for(segments, meta)

    # The `.analysis.json` is data, not a reader's file, so it travels with the
    # JSON format: Analysis on its own writes exactly one file, and the `.md`
    # says whether the numbers are beside it.
    numbers = "md" in formats and "json" in formats
    meta = dict(meta, numbers_file=numbers)

    written = []
    for fmt in FORMAT_ORDER:
        if fmt in formats:
            written.append(WRITERS[fmt](segments, meta, output_dir / stem))
    if numbers:
        written.append(write_analysis(segments, meta, output_dir / stem))
    return written
