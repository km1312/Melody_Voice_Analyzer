"""Write a finished transcript out in the formats the user asked for."""

import csv
import json
from pathlib import Path

FORMAT_LABELS = {
    "json": "JSON (full data)",
    "txt": "Text transcript",
    "srt": "Subtitles (.srt)",
    "csv": "Spreadsheet (.csv)",
}
FORMAT_ORDER = ["json", "txt", "srt", "csv"]


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


WRITERS = {
    "json": write_json,
    "txt": write_txt,
    "srt": write_srt,
    "csv": write_csv,
}


def write_all(segments, meta, output_dir: Path, stem: str, formats):
    """Write every requested format. Returns the list of paths created."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for fmt in FORMAT_ORDER:
        if fmt in formats:
            written.append(WRITERS[fmt](segments, meta, output_dir / stem))
    return written
