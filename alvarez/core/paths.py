"""
Alvarez Core System Paths (Platform-Agnostic)
"""

import os
import sys
from pathlib import Path


class AlvarezPaths:
    """Provides platform-agnostic paths for Alvarez configuration, cache, and Antigravity CLI integration."""

    @staticmethod
    def user_home() -> Path:
        return Path.home()

    @classmethod
    def gemini_dir(cls) -> Path:
        return cls.user_home() / ".gemini" / "antigravity-cli"

    @classmethod
    def config_dir(cls) -> Path:
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA")
            if appdata:
                return Path(appdata) / "alvarez"
        return cls.user_home() / ".config" / "alvarez"

    @classmethod
    def streams_dir(cls) -> Path:
        return cls.user_home() / "Streams"

    @classmethod
    def brain_dir(cls) -> Path:
        return cls.gemini_dir() / "brain"

    @classmethod
    def credits_cache_file(cls) -> Path:
        return cls.gemini_dir() / "credits_cache.json"

    @classmethod
    def monitor_resume_file(cls) -> Path:
        return cls.gemini_dir() / "monitor_resume.json"

    @classmethod
    def active_session_file(cls) -> Path:
        return cls.gemini_dir() / "agy_active_session.json"
