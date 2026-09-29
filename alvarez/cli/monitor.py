#!/usr/bin/env python3
import os
import sys
import threading
import subprocess
import urllib.request
import time
import json
import re
import shutil
import textwrap
import signal
import select
from datetime import datetime

try:
    import termios
    import tty
    HAS_TTY = True
except ImportError:
    HAS_TTY = False

try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False

_REAL_FILE = os.path.realpath(__file__)
_PKG_ROOT = os.path.abspath(os.path.join(os.path.dirname(_REAL_FILE), "..", ".."))
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

from alvarez.config import load_config
from alvarez.telemetry.sysfs import HardwareTelemetry
from alvarez.telemetry.containers import ContainerTelemetry
from alvarez.telemetry.environment import EnvironmentTelemetry
from alvarez.telemetry.quotas import QuotaTelemetry
from alvarez.audio.player import StreamPlayer
from alvarez.ui.statusline import StatuslineRenderer
from alvarez.ui.widgets import UIWidgets, make_mini_bar, format_delta_time
from alvarez.core.models import TelemetrySnapshot, AgentContext
from alvarez.core.ansi import visible_len, RESET, BOLD, DIM, COLOR_NOMINAL_CYAN

CREDITS_CACHE_FILE = os.path.expanduser("~/.gemini/antigravity-cli/credits_cache.json")

extra_stats = {
    "ping": "Checking...",
    "news": "Fetching…",
    "news_source": "",
    "news_author": "",
    "news_posted": 0,
    "news_url": "",
    "net_tx": "0KB/s",
    "net_rx": "0KB/s",
    "credits": "..."
}

if os.path.exists(CREDITS_CACHE_FILE):
    try:
        with open(CREDITS_CACHE_FILE, "r") as f:
            c_val = json.load(f).get("credits")
            if c_val is not None:
                extra_stats["credits"] = f"{int(c_val):,}"
    except Exception:
        pass

thoughts_buffer = []
scroll_offset = 0
_shared_player: Optional[StreamPlayer] = None

def handle_key_action(c: str):
    global scroll_offset, shutdown_flag, _shared_player
    if c.lower() == 's':
        if _shared_player:
            _shared_player.next_track()
    elif c.lower() == 'v':
        if _shared_player:
            state = _shared_player.get_state()
            presets = _shared_player.get_available_presets()
            if not presets:
                presets = ["synth", "ambient", "lofi", "deep"]
            cur = (state.preset or "synth").lower()
            if cur not in presets:
                cur = presets[0]
            next_preset = presets[(presets.index(cur) + 1) % len(presets)]
            _shared_player.play_preset(next_preset, standalone=True)
    elif c.lower() == 'p' or c == ' ':
        if _shared_player:
            state = _shared_player.get_state()
            if state.status == "playing":
                _shared_player.stop()
            else:
                last_p = (state.preset or "").lower()
                valid_p = _shared_player.get_available_presets()
                if last_p not in valid_p:
                    last_p = valid_p[0] if valid_p else "synth"
                _shared_player.play_preset(last_p, start_index=state.index, standalone=True)
    elif c.lower() == 'q' or c == '\x03':
        shutdown_flag = True

def get_input():
    global scroll_offset, old_tty_settings, shutdown_flag, _shared_player
    if HAS_MSVCRT:
        while not shutdown_flag:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch in (b'\x00', b'\xe0'):
                    ch2 = msvcrt.getch()
                    if ch2 == b'H':  # Up arrow
                        scroll_offset += 2
                    elif ch2 == b'P':  # Down arrow
                        scroll_offset = max(0, scroll_offset - 2)
                    elif ch2 == b'I':  # Page Up
                        scroll_offset += 10
                    elif ch2 == b'Q':  # Page Down
                        scroll_offset = max(0, scroll_offset - 10)
                else:
                    try:
                        c = ch.decode("utf-8", errors="ignore")
                        handle_key_action(c)
                    except Exception:
                        pass
            time.sleep(0.05)
        return

    if not HAS_TTY or not sys.stdin.isatty(): return
    old_tty_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setcbreak(sys.stdin.fileno())
        while not shutdown_flag:
            if select.select([sys.stdin], [], [], 0.05)[0]:
                c = sys.stdin.read(1)
                if c == '\x1b':
                    if select.select([sys.stdin], [], [], 0.05)[0]:
                        c2 = sys.stdin.read(1)
                        if c2 == '[':
                            if select.select([sys.stdin], [], [], 0.05)[0]:
                                c3 = sys.stdin.read(1)
                                if c3 == 'A':
                                    scroll_offset += 2
                                elif c3 == 'B':
                                    scroll_offset = max(0, scroll_offset - 2)
                                elif c3 == '5':
                                    if select.select([sys.stdin], [], [], 0.05)[0]:
                                        sys.stdin.read(1)
                                    scroll_offset += 10
                                elif c3 == '6':
                                    if select.select([sys.stdin], [], [], 0.05)[0]:
                                        sys.stdin.read(1)
                                    scroll_offset = max(0, scroll_offset - 10)
                else:
                    handle_key_action(c)
    except Exception:
        pass
    finally:
        if old_tty_settings is not None and HAS_TTY and sys.stdin.isatty():
            try:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_tty_settings)
            except Exception:
                pass

_ollama_model: str = ""

def _pick_ollama_model() -> str:
    """Return the name of the best available small Ollama text model."""
    global _ollama_model
    if _ollama_model:
        return _ollama_model
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/tags",
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            models = json.loads(resp.read().decode()).get("models", [])
        if not models:
            return ""
        # Prefer small general text models; avoid vision/coder/large models
        def score(m):
            n = m["name"].lower()
            if any(x in n for x in ("vision", "llava", "coder", "embed")): return 0
            # Prefer smaller parameter counts
            for size in ("1b", "3b", "7b", "8b", "14b", "32b", "70b"):
                if size in n: return {"1b":9,"3b":8,"7b":7,"8b":6,"14b":5,"32b":4,"70b":3}[size]
            return 1
        best = max(models, key=score)
        _ollama_model = best["name"]
    except Exception:
        _ollama_model = ""
    return _ollama_model

def ollama_rephrase(headline: str) -> str:
    """Ask local Ollama to restate a headline as one crisp sentence."""
    model = _pick_ollama_model()
    if not model:
        return headline
    try:
        prompt = (
            "Rewrite this news headline as exactly one short, natural, informative sentence. "
            "Output only the sentence — no preamble, no quotes, no explanation:\n\n"
            + headline
        )
        payload = json.dumps({
            "model": model,
            "prompt": (
                "In one clear, complete sentence, summarize what is happening in this news story. "
                "Be direct and informative. Output only the sentence, no preamble:\n\n"
                + headline
            ),
            "stream": False,
            "options": {"temperature": 0.35, "num_predict": 120}
        }).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = json.loads(resp.read().decode()).get("response", "").strip()
        # Strip surrounding quotes, collapse newlines
        raw = re.sub(r'^["\'\u201c\u2018]+|["\'\u201d\u2019]+$', '', raw.replace('\n', ' ')).strip()
        return raw if raw else headline
    except Exception:
        return headline

_live_quota: dict = {}   # populated by fetch_extras; read by load_payload

def fetch_extras():
    global _live_quota
    while True:
        # ── Live quota (always fresh, bypasses stale statusline cache) ──
        try:
            res_q = subprocess.run(
                ["agy", "-p", "/quota", "--output-format", "json"],
                capture_output=True, text=True, timeout=12
            )
            if res_q.returncode == 0 and res_q.stdout.strip():
                q_data = json.loads(res_q.stdout)
                groups = q_data.get("command", {}).get("data", {}).get("groups", [])
                fresh = {}
                for group in groups:
                    for bucket in group.get("buckets", []):
                        bid = bucket.get("id")
                        if bid:
                            fresh[bid] = {
                                "remaining_fraction": bucket.get("remaining_fraction", 1.0),
                                "reset_time":        bucket.get("reset_time"),
                            }
                if fresh:
                    _live_quota = fresh
        except Exception:
            pass

        # ── Credits ──
        try:
            res_c = subprocess.run(["agy", "-p", "/credits", "--output-format", "json"], capture_output=True, text=True, timeout=8)
            if res_c.returncode == 0 and res_c.stdout.strip():
                c_data = json.loads(res_c.stdout)
                rem_c = c_data.get("command", {}).get("data", {}).get("remaining_credits")
                if rem_c is not None:
                    extra_stats["credits"] = f"{int(rem_c):,}"
                    try:
                        with open(CREDITS_CACHE_FILE, "w") as cf:
                            json.dump({"credits": rem_c, "timestamp": time.time()}, cf)
                    except Exception:
                        pass
        except Exception:
            pass

        time.sleep(30)

def clean_thought(thinking: str) -> str:
    lines = thinking.strip().split('\n')
    cleaned = [line for line in lines if not re.match(r'^\s*\*\*[^*]+\*\*\s*$', line)]
    return '\n'.join(cleaned).strip()

_last_valid_payload = {}

def load_payload():
    global _last_valid_payload
    payload = {}
    for path in ["~/.gemini/antigravity-cli/statusline_cache.json", "~/.gemini/antigravity-cli/statusline_stdin.json"]:
        p = os.path.expanduser(path)
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and data:
                        if "quota" in data or "model" in data or "context_window" in data:
                            payload = data
                            break
                        elif not payload:
                            payload = data
            except Exception:
                pass

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

    if payload:
        curr_cw = payload.get("context_window")
        if not curr_cw or not float(curr_cw.get("used_percentage", 0.0)):
            if _last_valid_payload.get("context_window"):
                payload["context_window"] = _last_valid_payload["context_window"]

        if not payload.get("quota") and _last_valid_payload.get("quota"):
            payload["quota"] = _last_valid_payload["quota"]

        # Overlay fresh live quota (from agy /quota) over any stale cache values
        if _live_quota:
            merged = dict(payload.get("quota") or {})
            merged.update(_live_quota)
            payload["quota"] = merged

        _last_valid_payload = payload.copy()
    else:
        payload = _last_valid_payload.copy()

    return payload

def build_context(payload):
    raw_model = payload.get("model")
    model_name = "Antigravity Monitor"
    effort = payload.get("effort")
    if isinstance(raw_model, dict):
        effort = raw_model.get("effort") or effort
        model_name = raw_model.get("display_name") or raw_model.get("id") or model_name
    elif isinstance(raw_model, str) and raw_model.strip():
        model_name = raw_model.strip()

    if model_name:
        m = re.search(r"\((High|Medium|Low)\)", model_name, re.IGNORECASE)
        if m:
            if not effort:
                effort = m.group(1).lower()
            model_name = re.sub(r"\s*\((High|Medium|Low)\)", "", model_name, flags=re.IGNORECASE).strip()

    cw = payload.get("context_window", {})
    return AgentContext(
        model_name=model_name,
        effort=effort,
        turn_steps=payload.get("turn_steps", 0),
        total_steps=payload.get("total_steps", 0),
        active_tool=payload.get("active_tool"),
        turn_tokens=payload.get("turn_tokens", 0),
        velocity=payload.get("token_velocity", 0),
        context_pct=float(cw.get("used_percentage", 0.0)),
        context_size=int(cw.get("context_window_size", 1048576)),
    )

import math

def render_visualizer(width: int, media):
    """5-row audio visualizer with per-row gradient colours and smooth idle ripple."""
    ROWS = 5
    LEVELS_PER_ROW = 7          # 7 fractional sub-levels per row
    TOTAL_LEVELS = ROWS * LEVELS_PER_ROW  # 35

    if sys.platform == "linux" and os.path.isdir("/dev/shm") and os.access("/dev/shm", os.W_OK):
        VIS_DATA_FILE = "/dev/shm/agy_vis_data.json"
    else:
        VIS_DATA_FILE = os.path.join(tempfile.gettempdir(), "agy_vis_data.json")
    title = ""
    raw_bars = []

    if os.path.exists(VIS_DATA_FILE) and time.time() - os.path.getmtime(VIS_DATA_FILE) < 3.0:
        try:
            with open(VIS_DATA_FILE, "r") as f:
                v_data = json.load(f)
            if v_data and (time.time() - v_data.get("timestamp", 0) < 3.0):
                title = v_data.get("title", "Audio Stream")
                raw_data = v_data.get("norm_half", [])
                raw_bars = [min(1.0, max(0.0, float(b) / 7.0)) for b in raw_data]
        except:
            pass

    max_bars = (width - 4) // 2
    if max_bars < 10: max_bars = 10
    if max_bars % 2 != 0: max_bars -= 1
    half_bars = max_bars // 2
    half_data = []
    is_idle = False

    if not raw_bars and media and media.status == "playing":
        title = title or media.title or "Audio Stream"
        t = time.time() * 2.5
        for i in range(half_bars):
            val = (math.sin(t + i * 0.6) * math.cos(t * 0.9 - i * 0.15) + 1.0) / 2.0
            val = max(0.0, (val * 1.5) - 0.3) ** 1.5
            half_data.append(min(1.0, val))
    elif raw_bars:
        for i in range(half_bars):
            idx_float = i * (len(raw_bars) - 1) / max(1, half_bars - 1)
            idx = int(idx_float)
            frac = idx_float - idx
            if idx + 1 < len(raw_bars):
                val = raw_bars[idx] * (1 - frac) + raw_bars[idx + 1] * frac
            else:
                val = raw_bars[idx]
            val = max(0.0, (val * 1.6) - 0.25) ** 1.3
            half_data.append(min(1.0, val))
    else:
        is_idle = True
        t = time.time() * 0.7
        for i in range(half_bars):
            # Gentle breathing ripple at the bottom when idle
            val = (math.sin(t + i * 0.35) + 1.0) / 2.0 * 0.09
            half_data.append(val)

    bars = half_data[::-1] + half_data

    # Row 0 = topmost (hot pink), Row 4 = bottom (cyan) — bars fill bottom-up
    row_colors = [
        "\033[38;5;199m",   # row 0  top    — hot pink
        "\033[38;5;171m",   # row 1  upper  — magenta
        "\033[38;5;135m",   # row 2  mid    — purple
        "\033[38;5;87m",    # row 3  lower  — sky blue
        "\033[38;5;51m",    # row 4  bottom — cyan
    ]
    block_chars = ["▂", "▃", "▄", "▅", "▆", "▇"]   # indices 0-5 for sub=1..6
    reset = "\033[0m"
    rows = [""] * ROWS

    for val in bars:
        level = int(val * TOTAL_LEVELS)
        for row_idx in range(ROWS):
            # Bottom rows fill first: row 4 is zone 0-7, row 0 is zone 28-35
            zone_bottom = (ROWS - 1 - row_idx) * LEVELS_PER_ROW
            zone_top    = zone_bottom + LEVELS_PER_ROW
            col = row_colors[row_idx]
            if level >= zone_top:
                rows[row_idx] += f"{col}█{reset} "
            elif level > zone_bottom:
                sub = level - zone_bottom          # 1..6
                rows[row_idx] += f"{col}{block_chars[sub - 1]}{reset} "
            else:
                rows[row_idx] += "  "

    if is_idle:
        display_title = f"\033[38;5;239m◈  stream idle\033[0m"
    elif media and media.status == "playing":
        display_title = f"\033[38;5;51m▶  \033[0;37m{title}\033[0m"
    else:
        display_title = f"\033[38;5;51m◈  \033[0;37m{title}\033[0m"

    return display_title, rows


def section_rule(width: int) -> str:
    """Thin Unicode horizontal rule — no letter borders."""
    return f"\033[38;5;235m{'─' * width}\033[0m"

def content_line(text: str) -> str:
    """Content row with 2-space indent, no side borders."""
    return f"  {text}"

def handle_exit(sig=None, frame=None):
    global old_tty_settings, shutdown_flag
    shutdown_flag = True
    if old_tty_settings is not None and HAS_TTY and sys.stdin.isatty():
        try:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_tty_settings)
        except Exception:
            pass
    try:
        sys.stdout.write("\033[r\033[?1049l\033[?25h\n")
        sys.stdout.flush()
    except Exception:
        pass

def handle_sig(sig, frame):
    global shutdown_flag
    shutdown_flag = True

signal.signal(signal.SIGINT, handle_sig)
signal.signal(signal.SIGTERM, handle_sig)

def process_transcript_line(line, w):
    try:
        import json, textwrap, re
        from datetime import datetime
        data = json.loads(line)
        etype = data.get("type", "")
        source = data.get("source", "")
        now = datetime.fromisoformat(data.get("created_at", datetime.now().isoformat() + "Z")[:-1]).strftime("%H:%M:%S") if "created_at" in data else datetime.now().strftime("%H:%M:%S")
        
        out_str = ""
        if etype == "USER_INPUT":
            content_data = data.get("content", "").strip()
            if content_data:
                wrapped = "\n".join(textwrap.wrap(content_data, width=w-4))
                out_str = f"\n\033[38;5;51m[{now}] 👤 USER\033[0m\n{wrapped}\n"
        
        elif etype == "PLANNER_RESPONSE":
            thinking = data.get("thinking", "")
            agent_content = data.get("content", "")
            
            blocks = []
            if thinking:
                lines = thinking.strip().split('\n')
                cleaned = [l for l in lines if not re.match(r'^\s*\*\*[^*]+\*\*\s*$', l)]
                thinking_clean = '\n'.join(cleaned).strip()
                if thinking_clean:
                    for p in thinking_clean.split('\n'):
                        if not p.strip(): blocks.append("")
                        else: blocks.append("\n".join(textwrap.wrap(p, width=w-4)))
            
            tool_calls = data.get("tool_calls", [])
            for tc in tool_calls:
                t_name = tc.get("name", "tool")
                args = tc.get("args", {})
                action = args.get("toolAction", t_name)
                if isinstance(action, str): action = action.strip('"\'')
                if any(x in t_name.lower() for x in ("edit", "replace", "write", "patch")):
                    blocks.append(f"\033[38;5;214m ⚠ Modifying: {action}\033[0m")
                elif any(x in t_name.lower() for x in ("command", "run", "bash")):
                    blocks.append(f"\033[38;5;177m ⚡ Executing: {action}\033[0m")
                else:
                    blocks.append(f"\033[38;5;75m ⚙ Reading: {action}\033[0m")
                
            if agent_content:
                wrapped_content = "\n".join(textwrap.wrap(agent_content, width=w-4))
                blocks.append(f"\033[38;5;46m💬 {wrapped_content}\033[0m")
                
            if blocks:
                body = "\n".join(blocks)
                out_str = f"\n\033[96m[{now}] ✦ AGENT\033[0m\n{body}\n"
                
        
        
        if out_str:
            for l in out_str.split('\n'):
                thoughts_buffer.append(l)
    except:
        pass

import tempfile

def ensure_visualizer_daemon():
    daemon_bin = shutil.which("agy-rortings-vis") or shutil.which("alvarez-vis") or os.path.expanduser("~/.local/bin/alvarez-vis")
    lock_file = os.path.join(tempfile.gettempdir(), "agy_visualizer.lock")
    if daemon_bin and os.path.exists(daemon_bin):
        try:
            if sys.platform != "win32" and shutil.which("flock"):
                cmd = ["flock", "-n", lock_file, "env", "AGY_LOCKED=1", sys.executable, daemon_bin]
            else:
                cmd = [sys.executable, daemon_bin]
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

def find_latest_transcript() -> Optional[str]:
    session_file = os.path.expanduser("~/.gemini/antigravity-cli/agy_active_session.json")
    if os.path.exists(session_file):
        try:
            with open(session_file, "r") as f:
                sdata = json.load(f)
            cid = sdata.get("session_id") or sdata.get("conversation_id")
            if cid:
                p_full = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{cid}/.system_generated/logs/transcript_full.jsonl")
                if os.path.exists(p_full):
                    return p_full
                p_comp = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{cid}/.system_generated/logs/transcript.jsonl")
                if os.path.exists(p_comp):
                    return p_comp
        except Exception:
            pass

    brain_dir = os.path.expanduser("~/.gemini/antigravity-cli/brain")
    if os.path.isdir(brain_dir):
        subdirs = []
        for d in os.listdir(brain_dir):
            full_d = os.path.join(brain_dir, d)
            if os.path.isdir(full_d):
                t_full = os.path.join(full_d, ".system_generated", "logs", "transcript_full.jsonl")
                t_comp = os.path.join(full_d, ".system_generated", "logs", "transcript.jsonl")
                if os.path.exists(t_full):
                    subdirs.append((os.path.getmtime(t_full), t_full))
                elif os.path.exists(t_comp):
                    subdirs.append((os.path.getmtime(t_comp), t_comp))
        if subdirs:
            subdirs.sort(key=lambda x: x[0], reverse=True)
            return subdirs[0][1]
    return None

cached_snapshot = None
last_snapshot_time = 0
shutdown_flag = False

def run_monitor():
    global cached_snapshot, last_snapshot_time, shutdown_flag
    import threading
    t = threading.Thread(target=get_input, daemon=True)
    t.start()
    initial_mtime = os.stat(_REAL_FILE).st_mtime
    threading.Thread(target=fetch_extras, daemon=True).start()
    
    config = load_config()
    hw_telemetry = HardwareTelemetry(root_mount=config.telemetry.root_mount)
    container_telemetry = ContainerTelemetry(docker_socket=config.telemetry.docker_socket)
    env_telemetry = EnvironmentTelemetry(location=config.env.location)
    stream_player = StreamPlayer(streams_dir=config.audio.streams_dir)
    global _shared_player
    _shared_player = stream_player
    renderer = StatuslineRenderer(config=config)
    
    ensure_visualizer_daemon()

    MONITOR_RESUME_FILE = os.path.expanduser("~/.gemini/antigravity-cli/monitor_resume.json")
    was_playing_on_last_exit = False
    saved_preset = None
    saved_index = 0
    try:
        with open(MONITOR_RESUME_FILE) as _mrf:
            _mr = json.load(_mrf)
        was_playing_on_last_exit = bool(_mr.get("was_playing"))
        saved_preset = _mr.get("preset")
        saved_index  = int(_mr.get("index", 0))
    except Exception:
        pass

    cur_media = stream_player.get_state()
    if was_playing_on_last_exit and cur_media.status != "playing":
        raw_target = saved_preset or cur_media.preset
        valid_presets = stream_player.get_available_presets()
        if raw_target and raw_target.lower() in ("synthwave", "synth"):
            target_preset = "synth"
        elif raw_target and raw_target.lower() in valid_presets:
            target_preset = raw_target.lower()
        else:
            target_preset = valid_presets[0] if valid_presets else "synth"
        stream_player.play_preset(target_preset, start_index=saved_index, standalone=True)

    current_transcript_path = find_latest_transcript()
    transcript_f = None
    if current_transcript_path and os.path.exists(current_transcript_path):
        try:
            transcript_f = open(current_transcript_path, "r")
            term_size = shutil.get_terminal_size((135, 24))
            w = term_size.columns - 2
            for line in transcript_f:
                process_transcript_line(line, w)
        except Exception:
            pass

    sys.stdout.write("\033[?1049h\033[?25l\033[2J")
    sys.stdout.flush()

    last_term_size = None
    last_check_transcript = time.time()

    try:
        while not shutdown_flag:
            if os.stat(_REAL_FILE).st_mtime != initial_mtime:
                sys.stdout.write("\033[r\033[?1049l\033[?25h\n")
                sys.stdout.flush()
                if transcript_f:
                    try:
                        transcript_f.close()
                    except Exception:
                        pass
                os.execv(sys.executable, ['python3', _REAL_FILE])

            if shutdown_flag:
                break

            term_size = shutil.get_terminal_size((135, 24))
            w = term_size.columns - 2
            h = term_size.lines
            
            payload = load_payload()
            ctx = build_context(payload)
            
            now_time = time.time()
            if cached_snapshot is None or now_time - last_snapshot_time >= 1.0:
                cached_snapshot = TelemetrySnapshot(
                    hw=hw_telemetry.collect(),
                    inference=container_telemetry.inspect_ollama() if config.telemetry.poll_ollama else None,
                    docker=container_telemetry.inspect_docker() if config.telemetry.poll_docker else None,
                    git=ContainerTelemetry.inspect_git(),
                    quotas=QuotaTelemetry.parse_quotas(payload.get("quota")),
                    media=stream_player.get_state(),
                    weather=env_telemetry.get_weather(),
                    tasks=env_telemetry.get_tasks(),
                    volume=env_telemetry.get_volume(),
                    timestamp=now_time
                )
                last_snapshot_time = now_time
            else:
                cached_snapshot.media = stream_player.get_state()
                cached_snapshot.timestamp = now_time
                
            snapshot = cached_snapshot
            
            # 1. Agent & Credits Line
            agent_chips = [UIWidgets.render_model_badge(ctx)]
            if extra_stats.get("credits") and extra_stats["credits"] != "...":
                agent_chips.append(f"\033[1;38;5;220mCredits:\033[0m \033[1;37m{extra_stats['credits']}\033[0m")
            if ctx.context_pct > 0:
                agent_chips.append(UIWidgets.render_context_chip(ctx))
            agent_chips.extend(UIWidgets.render_turn_chips(ctx))
            agent_line = f" {DIM}│{RESET} ".join(agent_chips)

            # 2. Dynamic Model-Specific Quotas (Gemini vs Claude/GPT-OSS)
            bar_w = 4 if w < 130 else 6
            def format_bucket(name, q):
                if not q: return None
                rem_pct = max(0.0, min(100.0, q.remaining_fraction * 100.0))
                t = format_delta_time(q.reset_in_seconds)
                bar, col = make_mini_bar(rem_pct, width=bar_w)
                return f"{name}: {col}{rem_pct:.0f}%{RESET}[{bar}] {t}"

            m_str = str(ctx.model_name or "").lower()
            is_3p_model = any(k in m_str for k in ("claude", "gpt", "openai", "codex", "sonnet", "haiku", "opus"))

            gem_5h = format_bucket("5h", snapshot.quotas.get("gemini-5h"))
            gem_wk = format_bucket("Wk", snapshot.quotas.get("gemini-weekly"))
            gem_parts = [p for p in (gem_5h, gem_wk) if p]
            gem_str = f"{BOLD}{COLOR_NOMINAL_CYAN}Gemini:{RESET} {'  '.join(gem_parts)}" if gem_parts else ""

            p3_5h = format_bucket("5h", snapshot.quotas.get("3p-5h"))
            p3_wk = format_bucket("Wk", snapshot.quotas.get("3p-weekly"))
            p3_parts = [p for p in (p3_5h, p3_wk) if p]
            p3_str = f"{BOLD}\033[38;5;208mClaude/GPT-OSS:{RESET} {'  '.join(p3_parts)}" if p3_parts else ""

            quota_rows = []
            if is_3p_model:
                if p3_str:
                    quota_rows.append(p3_str)
                elif gem_str:
                    quota_rows.append(gem_str)
            else:
                if gem_str:
                    quota_rows.append(gem_str)
                elif p3_str:
                    quota_rows.append(p3_str)
            if not quota_rows:
                quota_rows = [f"{DIM}Quotas: N/A{RESET}"]

            # 3. Hardware Rows
            hw_chips = UIWidgets.render_hardware_chips(snapshot.hw, snapshot.inference, term_width=w-8)

            vis_title, vis_lines = render_visualizer(w, snapshot.media)

            # ── Header: title left, live clock right, thin rule connecting them ──
            title_text = "✦  ANTIGRAVITY MONITOR"
            clock_str  = datetime.now().strftime("%H:%M:%S")
            fill_w = w - len(title_text) - len(clock_str) - 6
            if fill_w < 1: fill_w = 1
            header_fill = f"\033[38;5;235m{'─' * fill_w}\033[0m"
            header_line = (
                f"  \033[1;37m{title_text}\033[0m"
                f"  {header_fill}  "
                f"\033[38;5;244m{clock_str}\033[0m"
            )


            # ── Assemble HUD rows ──
            hud_rows = [
                header_line,
                section_rule(w),
                content_line(agent_line),
                section_rule(w),
            ]
            for ql in quota_rows:
                hud_rows.append(content_line(ql))
            hud_rows.append(section_rule(w))
            for hc in hw_chips:
                hud_rows.append(content_line(hc))
            hud_rows.extend([
                section_rule(w),
                content_line(vis_title),
            ])
            for vl in vis_lines:
                hud_rows.append(content_line(vl))
            hud_rows.append(section_rule(w))
            
            hud_rows = [r + "\033[K" for r in hud_rows]
            hud_text = "\n".join(hud_rows)
            hud_height = len(hud_rows)
            
            if term_size != last_term_size:
                sys.stdout.write("\033[2J")
                last_term_size = term_size

            sys.stdout.write(f"\033[1;1H{hud_text}")


            
            if now_time - last_check_transcript > 3.0:
                last_check_transcript = now_time
                new_t_path = find_latest_transcript()
                if new_t_path and new_t_path != current_transcript_path:
                    if transcript_f:
                        try:
                            transcript_f.close()
                        except Exception:
                            pass
                    current_transcript_path = new_t_path
                    if os.path.exists(current_transcript_path):
                        try:
                            transcript_f = open(current_transcript_path, "r")
                            thoughts_buffer.clear()
                            for line in transcript_f:
                                process_transcript_line(line, w)
                        except Exception:
                            pass

            if transcript_f:
                while True:
                    line = transcript_f.readline()
                    if not line:
                        break
                    process_transcript_line(line, w)
            
            thought_h = h - hud_height - 2
            if thought_h > 0:
                start_idx = max(0, len(thoughts_buffer) - thought_h - scroll_offset)
                end_idx = start_idx + thought_h
                visible_lines = thoughts_buffer[start_idx:end_idx]
                
                while len(visible_lines) < thought_h:
                    visible_lines.append("")
                    
                for i, l in enumerate(visible_lines):
                    sys.stdout.write(f"\033[{hud_height + 1 + i};1H\033[K{l}")
                    
            footer = f"\033[{h};1H\033[38;5;239m  Monitoring Agent Stream... [\033[1mS\033[22m Skip, \033[1mV\033[22m Vibe, \033[1mP/Space\033[22m Play/Stop, \033[1m↑/↓\033[22m Scroll, \033[1mQ\033[22m Exit]\033[0m\033[K"
            sys.stdout.write(footer)
            sys.stdout.flush()

            time.sleep(0.08)

    except KeyboardInterrupt:
        pass
    finally:
        shutdown_flag = True

        # ── Snapshot stream state BEFORE stopping ──
        try:
            _exit_media = stream_player.get_state()
            _was_playing = (_exit_media.status == "playing")
            _exit_preset  = _exit_media.preset or "synth"
            _exit_index   = _exit_media.index
        except Exception:
            _was_playing = False
            _exit_preset = "synth"
            _exit_index  = 0

        # ── Stop the stream ──
        try:
            stream_player.stop()
        except Exception:
            pass

        # ── Write monitor resume file ──
        try:
            with open(MONITOR_RESUME_FILE, "w") as _mrf:
                json.dump({
                    "was_playing": _was_playing,
                    "preset":      _exit_preset,
                    "index":       _exit_index,
                }, _mrf)
        except Exception:
            pass

        # ── Close transcript ──
        if transcript_f:
            try:
                transcript_f.close()
            except Exception:
                pass

        # ── Restore terminal — no blocking calls ──
        try:
            if old_tty_settings is not None and HAS_TTY and sys.stdin.isatty():
                termios.tcsetattr(sys.stdin, termios.TCSANOW, old_tty_settings)
        except Exception:
            pass
        try:
            sys.stdout.write("\033[r\033[?1049l\033[?25h\r\n")
            sys.stdout.flush()
        except Exception:
            pass

        os._exit(0)

if __name__ == "__main__":
    run_monitor()
