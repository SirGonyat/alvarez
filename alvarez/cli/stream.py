#!/usr/bin/env python3
"""
Audio Streaming CLI Entry Point for agy-rortings.

Usage:
  agy-rortings-stream synth
  agy-rortings-stream ambient
  agy-rortings-stream lofi
  agy-rortings-stream deep
  agy-rortings-stream <url>
  agy-rortings-stream stop
  agy-rortings-stream status
  agy-rortings-stream next
  agy-rortings-stream prev
  agy-rortings-stream volume <0-100>
  agy-rortings-stream list
  agy-rortings-stream autostart [on|off]
"""

import sys
import os

_REAL_FILE = os.path.realpath(__file__)
_PKG_ROOT = os.path.abspath(os.path.join(os.path.dirname(_REAL_FILE), "..", ".."))
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

import json
from alvarez.config import load_config
from alvarez.audio.player import StreamPlayer, CONFIG_FILE, PRESETS
from alvarez.core.ansi import (
    RESET, BOLD, COLOR_NOMINAL_GREEN, COLOR_NOMINAL_CYAN,
    COLOR_CAUTION_AMBER, COLOR_CRITICAL_RED, COLOR_NOMINAL_BLUE, COLOR_MUTED
)


def run_stream():
    config = load_config()
    player = StreamPlayer(streams_dir=config.audio.streams_dir)

    if len(sys.argv) < 2:
        print(f"{BOLD}Usage:{RESET} agy-rortings-stream <synth|ambient|lofi|deep|<url>|stop|status|next|prev|volume|list|autostart>")
        sys.exit(1)

    cmd = sys.argv[1]

    # Internal background worker dispatcher
    if cmd == "--worker":
        if len(sys.argv) < 4:
            sys.exit(1)
        mode = sys.argv[2]
        if mode == "playlist":
            cat = sys.argv[3]
            start_idx = None
            target_pid = None
            standalone = "--standalone" in sys.argv
            rem = [a for a in sys.argv[4:] if a != "--standalone"]
            if len(rem) >= 2 and rem[0].isdigit() and rem[1].isdigit():
                start_idx = int(rem[0])
                target_pid = int(rem[1])
            elif len(rem) == 1 and rem[0].isdigit():
                start_idx = int(rem[0])
            player.run_playlist_worker(cat, start_index=start_idx, target_pid=target_pid, standalone=standalone)
        elif mode == "direct":
            url = sys.argv[3]
            title = sys.argv[4] if len(sys.argv) > 4 else "Custom Stream"
            target_pid = int(sys.argv[5]) if len(sys.argv) > 5 and sys.argv[5].isdigit() else None
            standalone = "--standalone" in sys.argv
            player.run_direct_worker(url, title, target_pid=target_pid, standalone=standalone)
        sys.exit(0)

    cmd_lower = cmd.lower()

    if cmd_lower == "stop":
        stopped = player.stop()
        if stopped:
            print(f"{COLOR_CAUTION_AMBER}⏹ Audio stream stopped.{RESET}")
        else:
            print("No active audio stream found.")
    elif cmd_lower == "status":
        state = player.get_state()
        if state.status == "playing":
            print(f"{COLOR_NOMINAL_GREEN}▶ Playing ({state.preset}):{RESET} {state.title} [PID: {state.pid}]")
        else:
            print("Stream status: stopped")
    elif cmd_lower in ("next", "skip"):
        if player.next_track():
            print(f"{COLOR_NOMINAL_GREEN}⏭ Advancing to next track...{RESET}")
        else:
            print("Unable to advance (no active playlist).")
    elif cmd_lower in ("prev", "previous"):
        if player.prev_track():
            print(f"{COLOR_NOMINAL_GREEN}⏮ Returning to previous track...{RESET}")
        else:
            print("Unable to go back (no active playlist).")
    elif cmd_lower in ("vol", "volume"):
        if len(sys.argv) < 3:
            state = player.get_state()
            print(f"Volume: {state.volume}%")
        else:
            try:
                v = int(sys.argv[2].replace("%", ""))
                player.set_volume(v)
                print(f"Volume set to {v}%")
            except ValueError:
                print("Error: volume must be an integer between 0 and 100")
    elif cmd_lower in ("list", "ls", "presets"):
        print(f"{BOLD}Available Built-In Presets & Streams:{RESET}")
        for k in PRESETS:
            pl, src_file = player.get_playlist_for_category(k)
            src_hint = f"({len(pl)} tracks from {src_file})" if src_file else f"({len(pl)} built-in tracks)"
            print(f"  • {COLOR_NOMINAL_CYAN}{k}{RESET}: {PRESETS[k]['title']} {COLOR_MUTED}{src_hint}{RESET}")
    elif cmd_lower == "autostart":
        cfg = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    cfg = json.load(f)
            except Exception:
                pass
        if len(sys.argv) >= 3:
            val = sys.argv[2].lower() in ("on", "true", "1", "yes")
            cfg["autostart_on_agy_boot"] = val
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            with open(CONFIG_FILE, "w") as f:
                json.dump(cfg, f, indent=2)
            print(f"Autostart on Antigravity CLI boot: {'Enabled' if val else 'Disabled'}")
        else:
            cur = cfg.get("autostart_on_agy_boot", True)
            print(f"Autostart on Antigravity CLI boot is currently: {'Enabled' if cur else 'Disabled'}")
    elif cmd_lower in [p.lower() for p in player.get_available_presets()]:
        start_index = int(sys.argv[2]) - 1 if len(sys.argv) > 2 and sys.argv[2].isdigit() else None
        pl, src_file = player.get_playlist_for_category(cmd_lower)
        src_info = f"({len(pl)} clip(s)) [from {src_file}]" if src_file else f"({len(pl)} built-in clip(s))"
        print(f"▶ Launching {cmd_lower.capitalize()} Stream {src_info}...")
        state = player.play_preset(cmd_lower, start_index=start_index)
        if state:
            print(f"{COLOR_NOMINAL_GREEN}✓ Playing:{RESET} {state.title}")
        else:
            print(f"{COLOR_CRITICAL_RED}Failed to start stream (check ffplay installation or network connection).{RESET}")
    elif cmd.startswith("http://") or cmd.startswith("https://") or cmd.startswith("spotify:"):
        print(f"▶ Launching custom audio stream: {cmd}...")
        state = player.play_url(cmd)
        if state:
            print(f"{COLOR_NOMINAL_GREEN}✓ Playing:{RESET} {state.title}")
        else:
            print(f"{COLOR_CRITICAL_RED}Failed to play stream.{RESET}")
    else:
        avail_list = ", ".join(player.get_available_presets())
        print(f"Unknown command '{cmd}'. Available presets: {avail_list}. Commands: stop, status, next, prev, volume, list, autostart")


if __name__ == "__main__":
    run_stream()
