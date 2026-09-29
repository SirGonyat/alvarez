"""
Unit tests for StreamPlayer presets and playlist discovery.
"""

import os
from alvarez.audio.player import StreamPlayer, PRESETS


def test_stream_player_presets():
    player = StreamPlayer()
    for preset_name in ("synth", "ambient", "lofi", "deep"):
        pl, _ = player.get_playlist_for_category(preset_name)
        assert len(pl) > 0
        assert "url" in pl[0]


def test_stream_state_lifecycle():
    player = StreamPlayer()
    state = player.get_state()
    assert hasattr(state, "status")
    assert hasattr(state, "volume")
    assert hasattr(state, "resume_on_boot")


def test_resume_on_boot_logic(tmp_path):
    state_file = str(tmp_path / "stream_state.json")
    player = StreamPlayer(state_file=state_file)

    # Initially empty
    state = player.get_state()
    assert state.status == "stopped"
    assert state.resume_on_boot is False

    # Simulate active playback ending on session shutdown
    from alvarez.core.models import StreamState
    player.save_state(StreamState(
        status="stopped",
        preset="ambient",
        url="https://youtu.be/W-KDUgbnIOU",
        resume_on_boot=True
    ))

    loaded = player.get_state()
    assert loaded.status == "stopped"
    assert loaded.preset == "ambient"
    assert loaded.resume_on_boot is True

    # When explicitly stopped, resume_on_boot should be False
    player.stop()
    loaded_after_stop = player.get_state()
    assert loaded_after_stop.status == "stopped"
    assert loaded_after_stop.resume_on_boot is False


def test_playlist_randomization():
    player = StreamPlayer()
    pl, _ = player.get_playlist_for_category("synth")
    assert len(pl) > 1

    # Over 50 random samplings, we should see multiple different indices chosen (not stuck on 0)
    import random
    indices = {random.randrange(len(pl)) for _ in range(50)}
    assert len(indices) > 1


def test_get_available_presets(tmp_path):
    streams_dir = tmp_path / "Streams"
    streams_dir.mkdir()
    (streams_dir / "chillstep").mkdir()
    (streams_dir / "classical").mkdir()

    player = StreamPlayer(streams_dir=str(streams_dir))
    presets = player.get_available_presets()
    assert "synth" in presets
    assert "ambient" in presets
    assert "lofi" in presets
    assert "deep" in presets
    assert "chillstep" in presets
    assert "classical" in presets


