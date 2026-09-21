"""Retention (FR-24 to FR-26), in a temporary directory throughout."""

import json

import numpy as np
import pytest

from revolv import retention
from revolv.audio import load_audio
from revolv.player import Player
from revolv.store import Store

SR = 16000


def _document(ranges):
    return {"insights": [
        {"id": "i{0}".format(n), "audio_range": {"start_ms": a, "end_ms": b}}
        for n, (a, b) in enumerate(ranges)]}


@pytest.fixture()
def samples():
    t = np.arange(SR * 120) / SR
    return (0.4 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def test_export_clips_pads_and_indexes(tmp_path, samples):
    clips_dir = retention.export_clips(
        _document([(30_000, 35_000)]), tmp_path, "call",
        samples=samples, sample_rate=SR)
    assert clips_dir.name == "call.clips"
    index = retention.load_clip_index(clips_dir)
    assert len(index) == 1
    clip = index[0]
    assert clip["start_ms"] == 20_000       # ten seconds of pad each side
    assert clip["end_ms"] == 45_000
    decoded = load_audio(clip["path"])
    assert abs(len(decoded) - (45_000 - 20_000) / 1000 * SR) < SR * 0.1


def test_export_clips_clamps_to_the_media(tmp_path, samples):
    clips_dir = retention.export_clips(
        _document([(2_000, 4_000), (115_000, 119_000)]), tmp_path, "call",
        samples=samples, sample_rate=SR)
    index = retention.load_clip_index(clips_dir)
    assert index[0]["start_ms"] == 0
    assert index[1]["end_ms"] == 120_000


def test_no_readings_no_clips(tmp_path, samples):
    assert retention.export_clips(_document([]), tmp_path, "call",
                                  samples=samples) is None


def test_clip_player_serves_ranges_after_the_source_is_gone(qapp, tmp_path,
                                                            samples):
    retention.export_clips(_document([(30_000, 35_000)]), tmp_path, "call",
                           samples=samples, sample_rate=SR)

    streams = []

    def factory(sample_rate, callback, finished):
        class S:
            def start(self):
                pass

            def stop(self):
                pass

            def close(self):
                pass
        streams.append((sample_rate, callback))
        return S()

    player = retention.player_for(tmp_path, "call", tmp_path / "gone.mp4")
    assert isinstance(player, retention.ClipPlayer)
    player.stream_factory = factory
    assert player.play(31_000, 33_000) is True
    assert player.state == "playing"
    # The cursor is positioned in original-media time.
    assert player._cursor.position_ms == 31_000
    player.stop()
    assert player.play(90_000, 95_000) is False  # nothing covers that
    player.close()


def test_player_for_prefers_the_source(qapp, tmp_path, samples):
    media = tmp_path / "call.wav"
    retention.write_flac(media, samples[:SR], SR)  # any decodable file
    player = retention.player_for(tmp_path, "call", media)
    assert isinstance(player, Player)
    assert not isinstance(player, retention.ClipPlayer)
    player.close()


def test_player_for_reports_when_nothing_is_left(qapp, tmp_path):
    player = retention.player_for(tmp_path, "call", tmp_path / "gone.mp4")
    assert player.state == "unavailable"
    assert "not here any more" in player.unavailable_reason


def test_remove_source_goes_through_the_recycle_bin(tmp_path, monkeypatch):
    sent = []
    import send2trash as s2t
    monkeypatch.setattr(s2t, "send2trash", lambda p: sent.append(p))
    media = tmp_path / "call.wav"
    media.write_bytes(b"x")
    retention.remove_source(media)
    assert sent == [str(media)]


def test_delete_derived_removes_the_layer_and_the_rows(tmp_path):
    store = Store(tmp_path / "m.db")
    store.record_call("c1")
    store.add_feedback("k1", "c1", "r1", "useful")

    keep = [tmp_path / "call.json", tmp_path / "call.analysis.json",
            tmp_path / "call.wav", tmp_path / "call.md"]
    for path in keep:
        path.write_text("keep", encoding="utf-8")
    gone_files = [tmp_path / "call.context.json",
                  tmp_path / "call.context.json.bak",
                  tmp_path / "call.insights.json",
                  tmp_path / "call.insights (2).json",
                  tmp_path / "call.notes.md",
                  tmp_path / "call.coaching.json"]
    for path in gone_files:
        path.write_text("gone", encoding="utf-8")
    for name in ("call.prompt", "call (2).prompt", "call.clips"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "x.txt").write_text("gone", encoding="utf-8")

    removed = retention.delete_derived(tmp_path, "call", store=store,
                                       call_id="c1")
    assert len(removed) == len(gone_files) + 3
    for path in keep:
        assert path.exists()
    for path in gone_files:
        assert not path.exists()
    assert not (tmp_path / "call.prompt").exists()
    assert store.feedback_for("c1") == {}
    store.close()
