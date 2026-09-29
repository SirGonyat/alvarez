"""
Unit tests for boot autostart and session restore logic.
"""

import json
from unittest.mock import patch, MagicMock
from alvarez.cli.hud import check_and_autostart_stream


def test_autostart_does_not_start_when_nothing_was_streaming(tmp_path, monkeypatch):
    state_file = tmp_path / "stream_state.json"
    tracker_file = tmp_path / "stream_boot_tracker.json"
    state_file.write_text(json.dumps({"status": "stopped", "resume_on_boot": False, "preset": ""}))

    monkeypatch.setattr("alvarez.cli.hud.STREAM_STATE", str(state_file))
    monkeypatch.setattr("alvarez.cli.hud.STREAM_BOOT_TRACKER", str(tracker_file))
    monkeypatch.setattr("alvarez.cli.hud.is_agy_active", lambda pid: True)

    with patch("subprocess.Popen") as mock_popen:
        check_and_autostart_stream(99999, "test-session")
        mock_popen.assert_not_called()


def test_autostart_resumes_when_was_streaming(tmp_path, monkeypatch):
    state_file = tmp_path / "stream_state.json"
    tracker_file = tmp_path / "stream_boot_tracker.json"
    state_file.write_text(json.dumps({
        "status": "stopped",
        "resume_on_boot": True,
        "preset": "ambient",
        "index": 2
    }))

    monkeypatch.setattr("alvarez.cli.hud.STREAM_STATE", str(state_file))
    monkeypatch.setattr("alvarez.cli.hud.STREAM_BOOT_TRACKER", str(tracker_file))
    monkeypatch.setattr("alvarez.cli.hud.is_agy_active", lambda pid: True)

    with patch("subprocess.Popen") as mock_popen, \
         patch("shutil.which", return_value="/bin/agy-rortings-stream"), \
         patch("os.path.exists", return_value=True):
        check_and_autostart_stream(99999, "test-session")
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert "ambient" in cmd
        assert "3" in cmd  # index 2 -> track 3
