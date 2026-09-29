#!/usr/bin/env python3
"""
HUD Statusline CLI Entry Point for agy-rortings.

Supports both instantaneous (<15ms) one-shot evaluation for prompt redraws,
and interactive high-refresh (--watch / --hud) TUI dashboard mode.
"""

import sys
import os

_REAL_FILE = os.path.realpath(__file__)
_PKG_ROOT = os.path.abspath(os.path.join(os.path.dirname(_REAL_FILE), "..", ".."))
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

import json
import time
import shutil
import select
import re
import subprocess
from typing import Optional
from alvarez.config import load_config
from alvarez.core.models import TelemetrySnapshot, AgentContext
from alvarez.telemetry.sysfs import HardwareTelemetry
from alvarez.telemetry.quotas import QuotaTelemetry
from alvarez.telemetry.containers import ContainerTelemetry
from alvarez.telemetry.environment import EnvironmentTelemetry
from alvarez.audio.player import StreamPlayer, SESSION_FILE, is_agy_active
from alvarez.ui.statusline import StatuslineRenderer

import tempfile

STREAM_BOOT_TRACKER = os.path.expanduser("~/.gemini/antigravity-cli/stream_boot_tracker.json")
STREAM_CONFIG = os.path.expanduser("~/.gemini/antigravity-cli/stream_config.json")
STREAM_STATE = os.path.expanduser("~/.gemini/antigravity-cli/stream_state.json")
if sys.platform == "linux" and os.path.isdir("/dev/shm") and os.access("/dev/shm", os.W_OK):
    TERM_WIDTH_FILE = "/dev/shm/agy_term_width.txt"
else:
    TERM_WIDTH_FILE = os.path.join(tempfile.gettempdir(), "agy_term_width.txt")


def find_agy_parent_pid() -> Optional[int]:
    try:
        import psutil
        p = psutil.Process(os.getpid())
        for parent in p.parents():
            if parent.name() in ('agy', 'agy.exe'):
                return parent.pid
    except Exception:
        pass
    try:
        import psutil
        for p in psutil.process_iter(['name', 'status']):
            if p.info['name'] in ('agy', 'agy.exe') and p.info['status'] not in (
                psutil.STATUS_STOPPED, psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD
            ):
                return p.pid
    except Exception:
        pass
    return None


def check_and_autostart_stream(agy_pid: Optional[int], session_id: Optional[str]):
    if not agy_pid or not is_agy_active(agy_pid):
        return

    last_tracker = {}
    if os.path.exists(STREAM_BOOT_TRACKER):
        try:
            with open(STREAM_BOOT_TRACKER, "r") as f:
                last_tracker = json.load(f)
        except Exception:
            pass

    if last_tracker.get("last_agy_pid") == agy_pid:
        return

    try:
        with open(STREAM_BOOT_TRACKER, "w") as f:
            json.dump({
                "last_agy_pid": agy_pid,
                "last_session_id": session_id or "",
                "boot_time": time.time()
            }, f)
    except Exception:
        pass

    # Inspect previous session's stream state
    prev_state = {}
    if os.path.exists(STREAM_STATE):
        try:
            with open(STREAM_STATE, "r") as f:
                prev_state = json.load(f)
        except Exception:
            pass

    # If stream is already actively playing right now, do nothing
    if prev_state.get("status") == "playing":
        pid = prev_state.get("pid")
        runner_pid = prev_state.get("runner_pid")
        is_alive = False
        if pid:
            try:
                os.kill(pid, 0)
                is_alive = True
            except OSError:
                pass
        if not is_alive and runner_pid:
            try:
                os.kill(runner_pid, 0)
                is_alive = True
            except OSError:
                pass
        if is_alive:
            return

    # Check if stream was active in the last session and should be restored
    # Rule: when ctrl-c and reboot, return to the audio that was streaming in the last session.
    # And if nothing was streaming, then nothing starts streaming.
    resume = prev_state.get("resume_on_boot", False)
    if not resume and prev_state.get("status") == "playing":
        resume = True

    if not resume:
        return

    last_preset = prev_state.get("preset")
    last_url = prev_state.get("url")
    last_index = prev_state.get("index")

    target = None
    if last_preset and last_preset not in ("custom", "live", "none", ""):
        target = last_preset
    elif last_url and (last_url.startswith("http://") or last_url.startswith("https://") or last_url.startswith("spotify:")):
        target = last_url

    if not target:
        return

    stream_bin = shutil.which("agy-rortings-stream") or shutil.which("alvarez-stream") or os.path.expanduser("~/.local/bin/alvarez-stream")
    if stream_bin and os.path.exists(stream_bin):
        try:
            cmd = [stream_bin, target]
            if target == last_preset and last_index is not None and isinstance(last_index, int) and last_index >= 0:
                cmd.append(str(last_index + 1))
            kw = {}
            if sys.platform != "win32":
                kw["start_new_session"] = True
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                **kw
            )
        except Exception:
            pass


def ensure_visualizer_daemon(agy_pid: Optional[int]):
    if not agy_pid or agy_pid <= 1:
        return

    daemon_bin = shutil.which("agy-rortings-vis") or shutil.which("alvarez-vis") or os.path.expanduser("~/.local/bin/alvarez-vis")
    lock_file = os.path.join(tempfile.gettempdir(), "agy_visualizer.lock")
    if daemon_bin and os.path.exists(daemon_bin):
        try:
            if sys.platform != "win32" and shutil.which("flock"):
                cmd = ["flock", "-n", lock_file, "env", "AGY_LOCKED=1", sys.executable, daemon_bin, str(agy_pid)]
            else:
                cmd = [sys.executable, daemon_bin, str(agy_pid)]
            kw = {}
            if sys.platform != "win32":
                kw["start_new_session"] = True
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                **kw
            )
        except Exception:
            pass


def run_hud():
    watch_mode = "--watch" in sys.argv or "--hud" in sys.argv
    quiet_mode = "--quiet" in sys.argv or "-q" in sys.argv or "--cache-only" in sys.argv

    config = load_config()
    hw_telemetry = HardwareTelemetry(root_mount=config.telemetry.root_mount)
    container_telemetry = ContainerTelemetry(docker_socket=config.telemetry.docker_socket)
    env_telemetry = EnvironmentTelemetry(location=config.env.location)
    stream_player = StreamPlayer(streams_dir=config.audio.streams_dir)
    renderer = StatuslineRenderer(config=config)

    STATUSLINE_CACHE = os.path.expanduser("~/.gemini/antigravity-cli/statusline_cache.json")
    STATUSLINE_STDIN = os.path.expanduser("~/.gemini/antigravity-cli/statusline_stdin.json")

    # 1. Read optional JSON payload from stdin (strictly non-blocking, microsecond return)
    payload = {}
    if not sys.stdin.isatty():
        try:
            can_read = False
            if sys.platform == "win32":
                can_read = True
            else:
                r, _, _ = select.select([sys.stdin], [], [], 0.05)
                can_read = bool(r)

            if can_read:
                raw_input = sys.stdin.read()
                if raw_input.strip():
                    payload = json.loads(raw_input)
                    for path in [STATUSLINE_CACHE, STATUSLINE_STDIN]:
                        try:
                            tmp_p = path + ".tmp"
                            with open(tmp_p, "w") as f:
                                f.write(raw_input)
                            os.replace(tmp_p, path)
                        except Exception:
                            pass
        except Exception:
            pass

    # If stdin didn't provide a payload (such as during rapid redraw ticks while typing),
    # fall back to the most recent cached payload so agent context and metrics remain stable
    if not payload:
        for path in [STATUSLINE_CACHE, STATUSLINE_STDIN]:
            if os.path.exists(path):
                try:
                    with open(path, "r") as f:
                        cached = json.load(f)
                        if isinstance(cached, dict) and cached:
                            payload = cached
                            break
                except Exception:
                    pass

    # 2. Extract Agent Context
    settings_file = os.path.expanduser("~/.gemini/antigravity-cli/settings.json")
    if os.path.exists(settings_file):
        try:
            with open(settings_file, "r") as f:
                s_data = json.load(f)
            curr_model = s_data.get("model")
            if curr_model and str(curr_model).strip().lower() not in ("none", "null", ""):
                payload["model"] = curr_model
        except Exception:
            pass

    raw_model = payload.get("model")
    model_name = "Antigravity Brain"
    effort = payload.get("effort")

    if isinstance(raw_model, dict):
        effort = raw_model.get("effort") or effort
        model_name = raw_model.get("display_name") or raw_model.get("id") or "Antigravity Brain"
    elif isinstance(raw_model, str) and raw_model.strip():
        model_name = raw_model.strip()

    if model_name:
        m = re.search(r"\((High|Medium|Low)\)", model_name, re.IGNORECASE)
        if m:
            if not effort:
                effort = m.group(1).lower()
            model_name = re.sub(r"\s*\((High|Medium|Low)\)", "", model_name, flags=re.IGNORECASE).strip()

    turn_steps = payload.get("turn_steps", 0)
    total_steps = payload.get("total_steps", 0)
    active_tool = payload.get("active_tool")

    if not turn_steps:
        transcript_path = payload.get("transcript_path")
        if not transcript_path and payload.get("conversation_id"):
            for base in ["~/.gemini/antigravity-cli/brain", "~/.gemini/antigravity/brain"]:
                candidate = os.path.expanduser(f"{base}/{payload['conversation_id']}/.system_generated/logs/transcript.jsonl")
                if os.path.exists(candidate):
                    transcript_path = candidate
                    break
        if transcript_path and os.path.exists(transcript_path):
            try:
                with open(transcript_path, "r", errors="ignore") as f:
                    lines = [l for l in f if l.strip()]
                    total_steps = len(lines)
                    last_user_idx = -1
                    for idx, l in enumerate(lines):
                        if '"USER_INPUT"' in l:
                            last_user_idx = idx
                    if last_user_idx != -1:
                        turn_steps = max(1, total_steps - 1 - last_user_idx)
                    elif total_steps > 0:
                        turn_steps = 1

                    for l in reversed(lines[-8:]):
                        if '"tool_calls"' in l:
                            try:
                                d = json.loads(l)
                                tc = d.get("tool_calls")
                                if tc and isinstance(tc, list):
                                    active_tool = tc[0].get("name") or tc[0].get("function_name")
                                    break
                            except Exception:
                                pass
            except Exception:
                pass

    cw = payload.get("context_window", {})
    context_pct = float(cw.get("used_percentage", 0.0))
    context_size = int(cw.get("context_window_size", 1048576))

    ctx = AgentContext(
        model_name=model_name,
        effort=effort,
        turn_steps=turn_steps,
        total_steps=total_steps,
        active_tool=active_tool,
        turn_tokens=payload.get("turn_tokens", 0),
        velocity=payload.get("token_velocity", 0),
        context_pct=context_pct,
        context_size=context_size,
    )

    term_width = int(payload.get("terminal_width") or shutil.get_terminal_size((135, 24)).columns)
    try:
        with open(TERM_WIDTH_FILE, "w") as f:
            f.write(str(term_width))
    except Exception:
        pass

    # 3. Parent agy session tracking and auto-start services
    agy_pid = find_agy_parent_pid()
    try:
        os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
        with open(SESSION_FILE, "w") as f:
            json.dump({"pid": agy_pid, "timestamp": time.time()}, f)
    except Exception:
        pass

    check_and_autostart_stream(agy_pid, payload.get("session_id") or payload.get("conversation_id"))
    ensure_visualizer_daemon(agy_pid)

    if quiet_mode:
        sys.exit(0)

    # 4. Gather Snapshot Telemetry
    snapshot = TelemetrySnapshot(
        hw=hw_telemetry.collect(),
        inference=container_telemetry.inspect_ollama() if config.telemetry.poll_ollama else None,
        docker=container_telemetry.inspect_docker() if config.telemetry.poll_docker else None,
        git=ContainerTelemetry.inspect_git(),
        quotas=QuotaTelemetry.parse_quotas(payload.get("quota")),
        media=stream_player.get_state(),
        weather=env_telemetry.get_weather(),
        tasks=env_telemetry.get_tasks(),
        volume=env_telemetry.get_volume(),
        timestamp=time.time(),
    )

    if watch_mode:
        print("\033[?25l\033[2J", end="")
        try:
            while True:
                term_width = shutil.get_terminal_size((135, 24)).columns
                output = renderer.render(snapshot, ctx, term_width=term_width)
                sys.stdout.write(f"\033[H\033[J{output}\n")
                sys.stdout.flush()
                time.sleep(0.08)
        except KeyboardInterrupt:
            print("\033[?25h\nExiting...")
            sys.exit(0)
    else:
        output = renderer.render(snapshot, ctx, term_width=term_width)
        print(output)


if __name__ == "__main__":
    run_hud()
