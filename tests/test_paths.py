"""
Unit tests for platform-agnostic path resolver in Alvarez.
"""

from alvarez.core.paths import AlvarezPaths


def test_alvarez_paths():
    assert AlvarezPaths.user_home().exists()
    assert "antigravity-cli" in str(AlvarezPaths.gemini_dir())
    assert "Streams" in str(AlvarezPaths.streams_dir())
    assert "alvarez" in str(AlvarezPaths.config_dir())
