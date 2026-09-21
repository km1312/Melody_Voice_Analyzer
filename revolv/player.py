"""Audio playback for the results and context windows (PRD D9, option A).

The stack is what the app already ships: PyAV decodes (through
`audio.load_audio`, the same decoder the pipeline uses) and `sounddevice`
plays, so no Qt multimedia module is added to the bundle. One decode per
window, on a worker thread; `play(start_ms, end_ms)` then plays slices of the
in-memory array, and a 50 ms timer reports the position in original-media
milliseconds so the transcript can follow.

A missing or undecodable file is a state, not a crash: the player reports
`unavailable` with a one-line reason and the windows disable their controls
(FR-15). When retention has reduced a recording to flagged clips, `ClipSource`
serves the ranges that survive and the same interface keeps working (FR-24).

Everything hardware-touching is injectable — the loader and the output-stream
factory — which is how the unit tests run against a synthetic array with no
audio device at all.
"""

import threading

import numpy as np
from PySide6 import QtCore
from PySide6.QtCore import Signal

from .audio import TARGET_SR

TICK_MS = 50


def _default_loader(path):
    from .audio import load_audio

    return load_audio(path), TARGET_SR


def _default_stream_factory(sample_rate, callback, finished):
    import sounddevice

    return sounddevice.OutputStream(
        samplerate=sample_rate, channels=1, dtype="float32",
        callback=callback, finished_callback=finished)


class Cursor:
    """The buffer arithmetic, pure and testable: hands out blocks of a slice
    and knows where playback stands in original-media milliseconds."""

    def __init__(self, samples, sample_rate, start_ms, end_ms, offset_ms=0):
        self.sample_rate = sample_rate
        self.offset_ms = offset_ms  # where samples[0] sits in the media
        lo = max(int((start_ms - offset_ms) * sample_rate / 1000), 0)
        hi = min(int((end_ms - offset_ms) * sample_rate / 1000), len(samples))
        self.slice = samples[lo:hi]
        self.start_ms = start_ms
        self.frames_done = 0

    def next_block(self, frames):
        begin = self.frames_done
        block = self.slice[begin:begin + frames]
        self.frames_done = begin + len(block)
        return block

    @property
    def exhausted(self):
        return self.frames_done >= len(self.slice)

    @property
    def position_ms(self):
        return self.start_ms + int(self.frames_done * 1000 / self.sample_rate)


class _DecodeThread(QtCore.QThread):
    done = Signal(object, int)
    failed = Signal(str)

    def __init__(self, path, loader, parent=None):
        super().__init__(parent)
        self.path = path
        self.loader = loader

    def run(self):
        try:
            samples, sample_rate = self.loader(self.path)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.done.emit(samples, sample_rate)


class Player(QtCore.QObject):
    """States: `loading` -> `ready` | `unavailable`; `playing` while a range
    runs, back to `ready` when it ends or `stop()` is called."""

    stateChanged = Signal(str)
    positionChanged = Signal(int)   # original-media milliseconds
    finished = Signal()

    def __init__(self, path=None, parent=None, samples=None,
                 sample_rate=TARGET_SR, offset_ms=0, loader=None,
                 stream_factory=None):
        super().__init__(parent)
        self.path = path
        self.loader = loader or _default_loader
        self.stream_factory = stream_factory or _default_stream_factory
        self.offset_ms = offset_ms
        self.samples = None
        self.sample_rate = sample_rate
        self.state = "loading"
        self.unavailable_reason = ""
        self._stream = None
        self._ended_stream = None
        self._cursor = None
        self._lock = threading.Lock()
        self._decode = None
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

        if samples is not None:
            self._ready(np.asarray(samples, dtype=np.float32), sample_rate)
        elif path is None:
            self._unavailable("No recording to play.")

    def load(self):
        """Start the background decode. Call once from the GUI thread."""
        if self.samples is not None or self.state == "unavailable":
            return
        self._decode = _DecodeThread(self.path, self.loader, self)
        self._decode.done.connect(self._ready)
        self._decode.failed.connect(
            lambda reason: self._unavailable(
                "Could not read the recording: {0}".format(reason)))
        self._decode.start()

    def load_sync(self):
        """Decode on this thread; for tests and the CLI."""
        try:
            samples, sample_rate = self.loader(self.path)
        except Exception as exc:
            self._unavailable("Could not read the recording: {0}".format(exc))
            return
        self._ready(samples, sample_rate)

    def _ready(self, samples, sample_rate):
        self.samples = samples
        self.sample_rate = int(sample_rate)
        self._set_state("ready")

    def _unavailable(self, reason):
        self.unavailable_reason = reason
        self._set_state("unavailable")

    def _set_state(self, state):
        self.state = state
        self.stateChanged.emit(state)

    @property
    def available(self):
        return self.state in ("ready", "playing")

    def play(self, start_ms, end_ms):
        """Play [start_ms, end_ms) of the media. A no-op until ready."""
        if not self.available:
            return False
        self.stop()
        cursor = Cursor(self.samples, self.sample_rate, int(start_ms),
                        int(end_ms), self.offset_ms)
        if not len(cursor.slice):
            return False
        with self._lock:
            self._cursor = cursor
        # The finished callback must know which stream it belongs to: a
        # stale stream's callback (its own stop, or a late natural end)
        # must never stop the range that replaced it (fix list #1).
        holder = {}

        def on_end():
            self._ended_stream = holder.get("stream")
            QtCore.QMetaObject.invokeMethod(self, "_stream_ended",
                                            QtCore.Qt.QueuedConnection)

        self._stream = self.stream_factory(self.sample_rate, self._fill,
                                           on_end)
        holder["stream"] = self._stream
        self._set_state("playing")
        self._stream.start()
        self._timer.start()
        return True

    def _fill(self, outdata, frames, _time=None, _status=None):
        """The output callback; runs on the audio thread."""
        with self._lock:
            cursor = self._cursor
            block = cursor.next_block(frames) if cursor is not None else []
        n = len(block)
        outdata[:n, 0] = block
        if n < frames:
            outdata[n:, 0] = 0.0
            if cursor is not None and cursor.exhausted:
                import sounddevice

                raise sounddevice.CallbackStop()

    @QtCore.Slot()
    def _stream_ended(self):
        # Queued from a stream's finished callback (audio thread). Only the
        # stream that still owns the player may end playback.
        if self._ended_stream is None or \
                self._ended_stream is not self._stream:
            return
        self.stop()
        self.finished.emit()

    def _tick(self):
        with self._lock:
            cursor = self._cursor
        if cursor is not None:
            self.positionChanged.emit(cursor.position_ms)

    def stop(self):
        if self._stream is not None:
            stream, self._stream = self._stream, None
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        self._timer.stop()
        with self._lock:
            self._cursor = None
        if self.state == "playing":
            self._set_state("ready")

    def close(self):
        self.stop()
        if self._decode is not None and self._decode.isRunning():
            self._decode.wait(2000)
        self.samples = None


class ClipSource:
    """A loader over a `<name>.clips/` folder for `Player`.

    Serves whichever clip covers the requested range; used when the source
    recording is gone (FR-24). Constructed by `retention.clip_loader`.
    """

    def __init__(self, clips):
        # clips: list of {"start_ms", "end_ms", "path"}
        self.clips = list(clips)

    def covering(self, start_ms, end_ms):
        for clip in self.clips:
            if clip["start_ms"] <= start_ms and end_ms <= clip["end_ms"]:
                return clip
        return None
