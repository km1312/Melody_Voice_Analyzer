"""Decode any container PyAV can open into mono 16 kHz float32 samples.

The original pipeline downmixed by averaging raw frame arrays, which only works
for planar formats; packed formats arrive as a single interleaved row and would
be misread. Routing every frame through an AudioResampler makes the format,
channel layout and sample-rate conversion the decoder's problem.
"""

import numpy as np

TARGET_SR = 16000


class AudioError(RuntimeError):
    pass


def probe_duration(path) -> float:
    """Return the media duration in seconds, or 0.0 if it cannot be determined."""
    import av

    try:
        with av.open(str(path)) as container:
            if container.duration is not None:
                return float(container.duration) / av.time_base
            for stream in container.streams:
                if stream.type == "audio" and stream.duration and stream.time_base:
                    return float(stream.duration * stream.time_base)
    except Exception:
        pass
    return 0.0


def load_audio(path, target_sr: int = TARGET_SR, progress=None, cancel=None) -> np.ndarray:
    """Decode `path` to a mono float32 array in [-1, 1] at `target_sr`.

    `progress` is called with a 0..1 fraction as decoding advances.
    `cancel` is a threading.Event; decoding stops early when it is set.
    """
    import av
    from av.audio.resampler import AudioResampler

    try:
        container = av.open(str(path))
    except Exception as exc:
        raise AudioError(f"Could not open the file: {exc}") from exc

    try:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise AudioError("This file has no audio track.")
        stream.thread_type = "AUTO"

        duration = 0.0
        if container.duration is not None:
            duration = float(container.duration) / av.time_base
        elif stream.duration and stream.time_base:
            duration = float(stream.duration * stream.time_base)

        resampler = AudioResampler(format="flt", layout="mono", rate=target_sr)
        chunks = []
        time_base = stream.time_base

        for frame in container.decode(stream):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
            if progress and duration > 0 and frame.pts is not None and time_base:
                elapsed = float(frame.pts * time_base)
                progress(min(elapsed / duration, 1.0))

        for out in resampler.resample(None):  # flush the resampler's tail
            chunks.append(out.to_ndarray().reshape(-1))
    finally:
        container.close()

    if not chunks:
        raise AudioError("No audio frames could be decoded from this file.")

    audio = np.concatenate(chunks).astype(np.float32, copy=False)
    if progress:
        progress(1.0)

    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak == 0.0:
        raise AudioError("The audio track is completely silent.")
    return audio


class Cancelled(Exception):
    """Raised when the user stops a job mid-flight."""
