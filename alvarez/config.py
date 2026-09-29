"""
Configuration Management for agy-rortings.

Loads user preferences from ~/.config/agy-rortings/config.toml (or JSON fallback)
and provides typed defaults for display themes, weather locations, telemetry mounts,
and audio streaming presets.
"""

import os
import json
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

try:
    import tomllib
    HAVE_TOMLLIB = True
except ImportError:
    HAVE_TOMLLIB = False

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.config/agy-rortings/config.toml")


@dataclass
class UIConfig:
    theme: str = "gnostic_cyan"
    min_width: int = 80
    compact_breakpoint: int = 125
    ultra_compact_breakpoint: int = 90
    visualizer_style: str = "braille"  # "braille", "block", "mirrored"


@dataclass
class EnvironmentConfig:
    location: str = "auto"
    auto_detect_location: bool = True
    temp_unit: str = "C"


@dataclass
class TelemetryConfig:
    root_mount: str = "/"
    poll_docker: bool = True
    docker_socket: str = "/var/run/docker.sock"
    poll_ollama: bool = True
    ollama_endpoint: str = "http://127.0.0.1:11434"
    gpu_vendor: str = "auto"  # "auto", "amd", "nvidia", "none"


@dataclass
class AudioConfig:
    backend: str = "pipewire"  # "pipewire", "pulseaudio"
    fps: int = 12
    streams_dir: str = os.path.expanduser("~/Streams")
    auto_start_on_boot: bool = False
    default_preset: str = "ambient"


@dataclass
class AppConfig:
    ui: UIConfig = field(default_factory=UIConfig)
    env: EnvironmentConfig = field(default_factory=EnvironmentConfig)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """Loads configuration from TOML/JSON file or returns standard defaults."""
    cfg = AppConfig()
    path = config_path or DEFAULT_CONFIG_PATH

    if not os.path.exists(path):
        return cfg

    try:
        raw: Dict[str, Any] = {}
        if path.endswith(".toml") and HAVE_TOMLLIB:
            with open(path, "rb") as f:
                raw = tomllib.load(f)
        elif path.endswith(".json"):
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)

        if "ui" in raw:
            for k, v in raw["ui"].items():
                if hasattr(cfg.ui, k):
                    setattr(cfg.ui, k, v)

        if "env" in raw:
            for k, v in raw["env"].items():
                if hasattr(cfg.env, k):
                    setattr(cfg.env, k, v)

        if "telemetry" in raw:
            for k, v in raw["telemetry"].items():
                if hasattr(cfg.telemetry, k):
                    setattr(cfg.telemetry, k, v)

        if "audio" in raw:
            for k, v in raw["audio"].items():
                if hasattr(cfg.audio, k):
                    setattr(cfg.audio, k, v)

    except Exception:
        # Fallback to standard defaults on corrupt user config
        pass

    return cfg
