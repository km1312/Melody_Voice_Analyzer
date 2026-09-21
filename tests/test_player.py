"""player.Player against a synthetic array and a fake output stream."""

import numpy as np
import pytest

from revolv.player import ClipSource, Cursor, Player


class FakeStream:
    def __init__(self, sample_rate, callback, finished):
        self.sample_rate = sample_rate
        self.callback = callback
        self.finished = finished
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        pass

    def pump(self, frames):
        """Pull one block the way PortAudio would."""
        out = np.zeros((frames, 1), dtype=np.float32)
        try:
            self.callback(out, frames, None, None)
        except Exception as exc:  # sounddevice.CallbackStop ends a stream
            if type(exc).__name__ != "CallbackStop":
                raise
            self.finished()
            return out, True
        return out, False


@pytest.fixture()
def fake_streams():
    streams = []

    def factory(sample_rate, callback, finished):
        stream = FakeStream(sample_rate, callback, finished)
        streams.append(stream)
        return stream

    return streams, factory


def test_cursor_arithmetic():
    samples = np.arange(16000 * 4, dtype=np.float32)
    cursor = Cursor(samples, 16000, start_ms=1000, end_ms=3000)
    assert len(cursor.slice) == 16000 * 2
    assert cursor.position_ms == 1000
    block = cursor.next_block(8000)
    assert len(block) == 8000
    assert block[0] == 16000.0  # slice starts one second in
    assert cursor.position_ms == 1500
    cursor.next_block(16000 * 2)
    assert cursor.exhausted
    assert cursor.position_ms == 3000


def test_cursor_respects_offset():
    samples = np.zeros(16000, dtype=np.float32)
    cursor = Cursor(samples, 16000, start_ms=90_500, end_ms=90_600,
                    offset_ms=90_000)
    assert len(cursor.slice) == 1600


def test_play_and_run_to_end(qapp, fake_streams):
    streams, factory = fake_streams
    samples = np.ones(16000 * 5, dtype=np.float32) * 0.5
    player = Player(samples=samples, sample_rate=16000,
                    stream_factory=factory)
    assert player.state == "ready"

    assert player.play(2000, 2500)
    assert player.state == "playing"
    stream = streams[-1]
    assert stream.started

    out, done = stream.pump(4000)
    assert not done
    assert out[0, 0] == 0.5
    out, done = stream.pump(8000)
    assert done  # 8000 frames = 500 ms exhausted mid-block
    assert out[-1, 0] == 0.0  # padded with silence past the range end


def test_natural_end_returns_to_ready_and_emits_finished(qapp, fake_streams):
    streams, factory = fake_streams
    player = Player(samples=np.ones(16000, dtype=np.float32),
                    sample_rate=16000, stream_factory=factory)
    done = []
    player.finished.connect(lambda: done.append(True))
    player.play(0, 250)
    _out, ended = streams[-1].pump(8000)  # 500 ms pull exhausts the range
    assert ended
    qapp.processEvents()  # deliver the queued cross-thread slot
    assert player.state == "ready"
    assert done == [True]
    # The position timer is no longer running against a stale cursor.
    assert not player._timer.isActive()


def test_jumping_mid_playback_wins_over_the_old_stream(qapp, fake_streams):
    """Fix list #1: play A, jump to B before A ends, and a late finished
    callback from A must not stop B."""
    streams, factory = fake_streams
    player = Player(samples=np.zeros(16000 * 10, dtype=np.float32),
                    sample_rate=16000, stream_factory=factory)
    done = []
    player.finished.connect(lambda: done.append(True))

    assert player.play(1000, 5000)
    stream_a = streams[-1]
    assert player.play(7000, 8000)  # jump while A is still playing
    stream_b = streams[-1]
    assert stream_b is not stream_a
    assert player.state == "playing"
    assert player._cursor.position_ms == 7000

    stream_a.finished()  # A's callback arrives late
    qapp.processEvents()
    assert player.state == "playing"
    assert player._cursor is not None
    assert player._cursor.position_ms >= 7000
    assert done == []

    _out, ended = stream_b.pump(16000 * 2)  # B runs to its natural end
    assert ended
    qapp.processEvents()
    assert player.state == "ready"
    assert done == [True]


def test_stop_returns_to_ready(qapp, fake_streams):
    streams, factory = fake_streams
    player = Player(samples=np.zeros(16000), sample_rate=16000,
                    stream_factory=factory)
    player.play(0, 500)
    player.stop()
    assert player.state == "ready"
    assert streams[-1].stopped


def test_unavailable_on_missing_file(qapp):
    def loader(_path):
        raise OSError("gone")

    player = Player(path="missing.mp4", loader=loader)
    player.load_sync()
    assert player.state == "unavailable"
    assert "gone" in player.unavailable_reason
    assert player.play(0, 1000) is False


def test_play_before_ready_is_a_noop(qapp):
    player = Player(path="whatever.mp4", loader=lambda p: (_ for _ in ()).throw(
        RuntimeError("never called synchronously")))
    assert player.state == "loading"
    assert player.play(0, 1000) is False


def test_clip_source_covering():
    source = ClipSource([
        {"start_ms": 10_000, "end_ms": 40_000, "path": "a.flac"},
        {"start_ms": 60_000, "end_ms": 90_000, "path": "b.flac"},
    ])
    assert source.covering(12_000, 20_000)["path"] == "a.flac"
    assert source.covering(65_000, 66_000)["path"] == "b.flac"
    assert source.covering(45_000, 50_000) is None
    assert source.covering(30_000, 65_000) is None
