"""
Environment and Weather Telemetry for agy-rortings.

Provides background-cached meteorological updates and formatted local timestamps.
Never blocks prompt redraws; returns instantaneous cached weather state.
"""

import os
import json
import time
import urllib.request
import threading
import tempfile
from typing import Optional

import subprocess
from typing import Optional, List

CLI_WEATHER_CACHE = os.path.expanduser("~/.gemini/antigravity-cli/weather_cache.json")
WEATHER_CACHE_FILE = os.path.join(tempfile.gettempdir(), "alvarez_weather.json")
CACHE_TTL_SECONDS = 900  # 15 minutes


class EnvironmentTelemetry:
    """Manages asynchronous weather polling, background tasks, and audio volume."""

    def __init__(self, location: str = "auto"):
        self.location = location or "auto"

    def get_weather(self) -> str:
        """Returns the latest cached weather string, launching a background refresh if expired."""
        # 1. Check Antigravity CLI weather cache first
        if os.path.exists(CLI_WEATHER_CACHE):
            try:
                with open(CLI_WEATHER_CACHE, "r") as f:
                    data = json.load(f)
                summary = data.get("summary", "")
                if summary:
                    return summary
            except Exception:
                pass

        cached_str, age = self._read_cache()
        if cached_str and age < CACHE_TTL_SECONDS:
            return cached_str

        # Launch non-blocking background fetch if expired
        threading.Thread(target=self._fetch_weather_worker, daemon=True).start()

        return cached_str or "⛅ --°C"

    def get_tasks(self) -> List[str]:
        """Detects active, long-running developer background processes (e.g. ollama, python3)."""
        procs: List[str] = []
        try:
            ps_out = subprocess.check_output(
                ["ps", "-eo", "etimes,comm", "--sort=-etimes"],
                timeout=0.12, stderr=subprocess.DEVNULL
            ).decode()
            for line in ps_out.strip().split("\n")[1:]:
                parts = line.strip().split()
                if len(parts) >= 2:
                    comm = parts[1]
                    if comm in ["docker", "docker-compose", "python", "python3", "ollama", "cargo", "ffmpeg", "n8n"]:
                        t = int(parts[0])
                        if t > 30:
                            h = t // 3600
                            m = (t % 3600) // 60
                            dur = f"{h}h" if h > 0 else f"{m}m"
                            procs.append(f"{comm} ({dur})")
                            if len(procs) >= 2:
                                break
        except Exception:
            pass
        return procs

    def get_volume(self) -> int:
        """Queries desktop audio volume via WirePlumber wpctl."""
        try:
            v_out = subprocess.check_output(
                ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                timeout=0.08, stderr=subprocess.DEVNULL
            ).decode()
            parts = v_out.strip().split()
            if len(parts) >= 2:
                return int(round(float(parts[1]) * 100))
        except Exception:
            pass
        return 0

    def _read_cache(self) -> tuple[str, float]:
        if not os.path.exists(WEATHER_CACHE_FILE):
            return "", float("inf")
        try:
            with open(WEATHER_CACHE_FILE, "r") as f:
                data = json.load(f)
            age = time.time() - data.get("timestamp", 0)
            return data.get("text", ""), age
        except Exception:
            return "", float("inf")

    def _fetch_weather_worker(self):
        try:
            if not self.location or self.location.lower() == "auto":
                url = "https://wttr.in/?format=j1"
            else:
                loc_encoded = urllib.parse.quote(self.location)
                url = f"https://wttr.in/{loc_encoded}?format=j1"

            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            cur = data["current_condition"][0]
            temp_c = cur.get("temp_C", "--")
            desc = cur.get("weatherDesc", [{}])[0].get("value", "").lower()

            icon = "☀️"
            if "rain" in desc or "drizzle" in desc:
                icon = "🌧️"
            elif "snow" in desc:
                icon = "❄️"
            elif "cloud" in desc or "overcast" in desc:
                icon = "☁️"
            elif "sun" in desc or "clear" in desc:
                icon = "☀️"
            elif "thunder" in desc or "storm" in desc:
                icon = "⛈️"
            else:
                icon = "⛅"

            formatted = f"{icon}  +{temp_c}°C" if not temp_c.startswith("-") else f"{icon}  {temp_c}°C"

            with open(WEATHER_CACHE_FILE, "w") as f:
                json.dump({"text": formatted, "timestamp": time.time()}, f)
            with open(CLI_WEATHER_CACHE, "w") as f:
                json.dump({"summary": formatted, "timestamp": time.time()}, f)
        except Exception:
            pass
