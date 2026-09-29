from unittest.mock import patch
import sys
import tempfile
import os
from alvarez.core.paths import AlvarezPaths
from alvarez.core.ipc import SharedBuffer
from alvarez.audio.player import is_agy_active, StreamPlayer


def test_win32_paths():
    with patch("sys.platform", "win32"), patch.dict(os.environ, {"APPDATA": "C:\\Users\\Test\\AppData\\Roaming"}):
        cfg_dir = AlvarezPaths.config_dir()
        assert "alvarez" in str(cfg_dir)
        assert "AppData" in str(cfg_dir)


def test_win32_shared_buffer(tmp_path):
    with patch("sys.platform", "win32"):
        buf = SharedBuffer("test_buf.txt")
        assert tempfile.gettempdir() in buf.path
        assert buf.write("hello windows")
        assert buf.read() == "hello windows"
        buf.close()


def test_win32_is_agy_active():
    with patch("sys.platform", "win32"):
        # Should not crash or attempt /proc checks on Windows
        assert not is_agy_active(999999)
