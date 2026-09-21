"""Retention (FR-24 to FR-26): clips, the Recycle Bin, and delete-derived.

Three modes. `keep_source` changes nothing. `clips` writes a FLAC per kept
reading — `CLIP_PAD_SECONDS` each side of its audio range — into
`<name>.clips/`, so playback survives the source being removed. `none`
keeps no audio beyond the source the user already has.

The app never deletes a recording by itself: `remove_source` exists only
behind an explicit button and a confirm, and it sends to the Recycle Bin,
never past it (FR-25). `delete_derived` removes exactly what the
interpretation layer created — context, packs, insights, notes, coaching,
clips, and this call's rows in the store — and leaves the recording and the
pipeline's own outputs alone (FR-26).
"""

import json
from pathlib import Path

import numpy as np

from .audio import TARGET_SR
from .interpret.verify import CLIP_PAD_SECONDS
from .player import ClipSource, Player
from .writers import unique_path

INDEX_NAME = "clips.json"


def write_flac(path, samples, sample_rate=TARGET_SR):
    """Encode a mono float32 array as FLAC through PyAV."""
    import av

    pcm = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    data = (pcm * 32767.0).astype(np.int16)[None, :]
    with av.open(str(path), "w") as container:
        stream = container.add_stream("flac", rate=int(sample_rate))
        stream.layout = "mono"
        frame = av.AudioFrame.from_ndarray(data, format="s16", layout="mono")
        frame.sample_rate = int(sample_rate)
        frame.pts = 0
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return path


def export_clips(insights_document, out_dir, stem, samples=None,
                 sample_rate=TARGET_SR, media_path=None):
    """Write `<stem>.clips/` for every kept reading. Returns the clips dir,
    or None when there is nothing to clip.

    `samples` may be passed directly (tests, or a caller that already
    decoded); otherwise `media_path` is decoded once.
    """
    ranges = []
    for insight in insights_document.get("insights") or []:
        audio_range = insight.get("audio_range") or {}
        if audio_range.get("end_ms", 0) > audio_range.get("start_ms", 0):
            ranges.append((audio_range["start_ms"], audio_range["end_ms"]))
    if not ranges:
        return None

    if samples is None:
        from .audio import load_audio

        samples = load_audio(media_path)
        sample_rate = TARGET_SR

    pad = int(CLIP_PAD_SECONDS * 1000)
    total_ms = int(len(samples) * 1000 / sample_rate)
    clips_dir = unique_path(Path(out_dir) / (stem + ".clips"))
    clips_dir.mkdir(parents=True)
    index = []
    for number, (start_ms, end_ms) in enumerate(sorted(set(ranges)), 1):
        begin = max(start_ms - pad, 0)
        end = min(end_ms + pad, total_ms)
        lo = int(begin * sample_rate / 1000)
        hi = int(end * sample_rate / 1000)
        if hi <= lo:
            continue
        name = "clip_{0:03d}.flac".format(number)
        write_flac(clips_dir / name, samples[lo:hi], sample_rate)
        index.append({"start_ms": begin, "end_ms": end, "file": name})
    with open(clips_dir / INDEX_NAME, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)
    return clips_dir


def load_clip_index(clips_dir):
    clips_dir = Path(clips_dir)
    try:
        with open(clips_dir / INDEX_NAME, encoding="utf-8") as f:
            index = json.load(f)
    except (OSError, ValueError):
        return []
    return [{"start_ms": c["start_ms"], "end_ms": c["end_ms"],
             "path": clips_dir / c["file"]} for c in index]


class ClipPlayer(Player):
    """A Player that serves ranges from the clips folder (FR-24)."""

    def __init__(self, clips_dir, parent=None, loader=None,
                 stream_factory=None):
        super().__init__(parent=parent, samples=np.zeros(0, dtype=np.float32),
                         sample_rate=TARGET_SR, stream_factory=stream_factory)
        if loader is not None:
            self.loader = loader
        self.source = ClipSource(load_clip_index(clips_dir))
        self._cache = {}
        if not self.source.clips:
            self._unavailable("Only flagged clips were kept, and none cover "
                              "this recording.")

    def play(self, start_ms, end_ms):
        clip = self.source.covering(start_ms, end_ms) \
            or self.source.covering(start_ms, start_ms + 1)
        if clip is None:
            return False
        path = clip["path"]
        if path not in self._cache:
            try:
                samples, sample_rate = self.loader(path)
            except Exception:
                return False
            self._cache[path] = (samples, sample_rate)
        self.samples, self.sample_rate = self._cache[path]
        self.offset_ms = clip["start_ms"]
        return super().play(start_ms, min(end_ms, clip["end_ms"]))


def newest_clips_dir(out_dir, stem):
    candidates = [p for p in Path(out_dir).glob(stem + "*.clips")
                  if p.is_dir()]
    return max(candidates, key=lambda p: p.stat().st_mtime) \
        if candidates else None


def player_for(out_dir, stem, media_path=None, parent=None):
    """A Player over the source when it exists, else over the clips."""
    if media_path is not None and Path(media_path).exists():
        player = Player(str(media_path), parent=parent)
        player.load()
        return player
    clips_dir = newest_clips_dir(out_dir, stem)
    if clips_dir is not None:
        return ClipPlayer(clips_dir, parent=parent)
    player = Player(parent=parent)
    player._unavailable("The recording is not here any more, and no clips "
                        "were kept.")
    return player


def remove_source(media_path):
    """Send the recording to the Recycle Bin. The caller confirms first;
    there is no other deletion path for a source recording (FR-25)."""
    from send2trash import send2trash

    send2trash(str(media_path))


def derived_paths(out_dir, stem):
    """Everything the interpretation layer wrote for this recording."""
    out_dir = Path(out_dir)
    found = []
    patterns = [
        stem + ".context.json", stem + ".context.json.bak",
        stem + ".insights.json", stem + ".insights (*).json",
        stem + ".notes.md", stem + ".notes (*).md",
        stem + ".coaching.json", stem + ".coaching (*).json",
        stem + ".prompt", stem + " (*).prompt",
        stem + ".clips", stem + " (*).clips",
    ]
    for pattern in patterns:
        found.extend(out_dir.glob(pattern))
    return sorted(set(found))


def delete_derived(out_dir, stem, store=None, call_id=None):
    """One action, everything the layer made (FR-26). Returns what went."""
    import shutil

    removed = []
    for path in derived_paths(out_dir, stem):
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(path)
        except OSError:
            pass
    if store is not None and call_id:
        store.delete_call(call_id)
    return removed
