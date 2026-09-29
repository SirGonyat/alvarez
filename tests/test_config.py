"""
Unit tests for configuration loading and default settings.
"""

from alvarez.config import load_config, AppConfig


def test_load_config_defaults():
    cfg = load_config("/nonexistent/path/config.toml")
    assert isinstance(cfg, AppConfig)
    assert cfg.ui.theme == "gnostic_cyan"
    assert cfg.telemetry.root_mount == "/"
    assert cfg.audio.backend == "pipewire"
