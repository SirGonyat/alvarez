#!/usr/bin/env python3
"""
Visualizer Daemon CLI Entry Point for agy-rortings.

Continuously captures live desktop audio via PipeWire PCM, performs FFT spectrum analysis
with spatial smoothing and dual-rate ballistics, and updates the shared-memory visualizer buffer.
"""

import os
import sys

_REAL_FILE = os.path.realpath(__file__)
_PKG_ROOT = os.path.abspath(os.path.join(os.path.dirname(_REAL_FILE), "..", ".."))
if _PKG_ROOT not in sys.path:
    sys.path.insert(0, _PKG_ROOT)

import time
import json
import signal
import fcntl
import math
import shutil
from typing import Optional, List, Tuple
from alvarez.config import load_config
from alvarez.audio.capture import AudioCapture
from alvarez.audio.player import StreamPlayer
from alvarez.core.ipc import SharedBuffer
from alvarez.ui.widgets import UIWidgets

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False

LOCK_FILE = "/tmp/agy_visualizer.lock"
SHM_DATA_FILE = "/dev/shm/agy_vis_data.json" if os.path.exists("/dev/shm") else "/tmp/agy_vis_data.json"
SHM_LINE_FILE = "/dev/shm/agy_vis_line.txt" if os.path.exists("/dev/shm") else "/tmp/agy_vis_line.txt"
TERM_WIDTH_FILE = "/dev/shm/agy_term_width.txt" if os.path.exists("/dev/shm") else "/tmp/agy_term_width.txt"

_lock_fd = None


def acquire_singleton_lock() -> bool:
    global _lock_fd
    if os.environ.get("AGY_LOCKED") == "1":
        return True
    try:
        _lock_fd = open(LOCK_FILE, "w")
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (IOError, OSError):
        return False


class EqualizerEngine:
    def __init__(self, num_half_bars: int = 20):
        self.num_half_bars = num_half_bars
        self.peak_ref = 500.0
        self.smooth_bands = np.zeros(num_half_bars, dtype=float) if HAVE_NUMPY else [0.0] * num_half_bars
        self.audio_history = np.zeros(800, dtype=np.float32) if HAVE_NUMPY else []
        self.smooth_rms_l = 0.0
        self.smooth_rms_r = 0.0
        self.frame_count = 0

    def compute_fft_and_levels(self, pcm_bytes: bytes) -> Tuple[List[float], float, float]:
        if not HAVE_NUMPY or not pcm_bytes or len(pcm_bytes) < 128:
            return [], 0.0, 0.0

        try:
            samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
            if len(samples) % 2 != 0:
                samples = samples[:-1]
            left = samples[0::2]
            right = samples[1::2]

            inst_l = float(np.sqrt(np.mean(left**2))) if len(left) > 0 else 0.0
            inst_r = float(np.sqrt(np.mean(right**2))) if len(right) > 0 else 0.0

            # Ballistic smoothing on Left and Right RMS for silky VU meters
            if inst_l > self.smooth_rms_l:
                self.smooth_rms_l += (inst_l - self.smooth_rms_l) * 0.70
            else:
                self.smooth_rms_l *= 0.85

            if inst_r > self.smooth_rms_r:
                self.smooth_rms_r += (inst_r - self.smooth_rms_r) * 0.70
            else:
                self.smooth_rms_r *= 0.85

            mono_chunk = (left + right) * 0.5
            # Maintain 100ms continuous window with 50% temporal overlap (800 samples at 8kHz)
            if len(self.audio_history) == 800 and len(mono_chunk) == 400:
                analysis_window = np.concatenate([self.audio_history[-400:], mono_chunk])
            elif len(mono_chunk) >= 800:
                analysis_window = mono_chunk[-800:]
            else:
                analysis_window = np.pad(mono_chunk, (max(0, 800 - len(mono_chunk)), 0))
            self.audio_history = analysis_window

            n = len(analysis_window)
            window = np.hanning(n)
            fft = np.abs(np.fft.rfft(analysis_window * window))
            fft_len = len(fft)

            # Logarithmic frequency distribution covering 20Hz - 3800Hz
            log_edges = np.logspace(np.log10(2), np.log10(fft_len), self.num_half_bars + 1)
            raw_bands = np.zeros(self.num_half_bars)
            for i in range(self.num_half_bars):
                s = int(log_edges[i])
                e = max(s + 1, int(log_edges[i + 1]))
                raw_bands[i] = np.mean(fft[s:e]) if e > s else 0.0

            # Equal-loudness Fletcher-Munson weighting: boost bass punch and crisp highs
            eq_curve = np.linspace(0.85, 2.3, self.num_half_bars)
            weighted = raw_bands * eq_curve

            # Spatial smoothing across neighboring bands
            kernel = np.array([0.08, 0.22, 0.40, 0.22, 0.08])
            padded = np.pad(weighted, (2, 2), mode='edge')
            spatial = np.convolve(padded, kernel, mode='valid')

            # Dynamic auto-gain with decay
            cur_max = float(np.max(spatial))
            if cur_max > self.peak_ref:
                self.peak_ref = cur_max
            else:
                self.peak_ref = max(300.0, self.peak_ref * 0.93)

            # Attack / Decay ballistics
            attack_mask = spatial > self.smooth_bands
            self.smooth_bands[attack_mask] += (spatial[attack_mask] - self.smooth_bands[attack_mask]) * 0.70
            self.smooth_bands[~attack_mask] *= 0.85

            normalized = (self.smooth_bands / max(self.peak_ref, 1.0)) ** 0.45
            curved = np.tanh(normalized * 1.25) * 7.0
            norm_half = np.clip(curved, 0, 7).astype(int).tolist()
            return norm_half, self.smooth_rms_l, self.smooth_rms_r
        except Exception:
            return [], 0.0, 0.0


def run_visualizer():
    if not acquire_singleton_lock():
        sys.exit(0)

    # Monitor parent agy PID if passed
    parent_agy_pid = None
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        parent_agy_pid = int(sys.argv[1])

    config = load_config()
    capture = AudioCapture(sample_rate=8000, channels=2)
    eq_engine = EqualizerEngine(num_half_bars=20)
    player = StreamPlayer(streams_dir=config.audio.streams_dir)
    buffer = SharedBuffer("agy_vis_line.txt")

    if not capture.start():
        sys.exit(1)

    running = True

    def _sig_handler(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    fps = max(10, config.audio.fps)

    try:
        while running:
            # Check parent watchdog
            if parent_agy_pid and parent_agy_pid > 1:
                try:
                    os.kill(parent_agy_pid, 0)
                except OSError:
                    break

            start_time = time.time()
            chunk = capture.read_latest_chunk(chunk_size=1600)
            state = player.get_state()
            eq_engine.frame_count += 1

            term_width = 135
            if os.path.exists(TERM_WIDTH_FILE):
                try:
                    with open(TERM_WIDTH_FILE, "r") as f:
                        tw = int(f.read().strip())
                        if tw > 20:
                            term_width = tw
                except Exception:
                    pass

            norm_half, rms_l, rms_r = eq_engine.compute_fft_and_levels(chunk)
            is_active = (state.status == "playing") or (rms_l > 15 or rms_r > 15)

            if is_active:
                title = state.title if state.status == "playing" else "Desktop Audio"
                # Write data file
                try:
                    with open(SHM_DATA_FILE + ".tmp", "w") as f:
                        json.dump({
                            "title": title,
                            "norm_half": norm_half,
                            "rms_l": rms_l,
                            "rms_r": rms_r,
                            "timestamp": time.time()
                        }, f)
                    os.replace(SHM_DATA_FILE + ".tmp", SHM_DATA_FILE)
                except Exception:
                    pass

                # Render live equalizer line
                lines = UIWidgets.render_visualizer_line(
                    title=title,
                    norm_half=norm_half,
                    rms_l=rms_l,
                    rms_r=rms_r,
                    term_width=term_width,
                    frame_idx=eq_engine.frame_count
                )
                buffer.write("\n".join(lines))

                # Send redraw tick (SIGWINCH) to parent agy process to update statusline smoothly
                if parent_agy_pid and parent_agy_pid > 1:
                    try:
                        os.kill(parent_agy_pid, signal.SIGWINCH)
                    except OSError:
                        break

                elapsed = time.time() - start_time
                sleep_dur = max(0.01, (1.0 / fps) - elapsed)
                time.sleep(sleep_dur)
            else:
                # Idle line
                lines = UIWidgets.render_idle_line(term_width=term_width)
                buffer.write("\n".join(lines))
                if os.path.exists(SHM_DATA_FILE):
                    try:
                        os.remove(SHM_DATA_FILE)
                    except Exception:
                        pass

                # Send 1Hz redraw tick to parent agy process while idle
                if parent_agy_pid and parent_agy_pid > 1:
                    try:
                        os.kill(parent_agy_pid, signal.SIGWINCH)
                    except OSError:
                        break

                time.sleep(1.0)
    finally:
        capture.stop()
        if os.path.exists(SHM_DATA_FILE):
            try:
                os.remove(SHM_DATA_FILE)
            except Exception:
                pass


if __name__ == "__main__":
    run_visualizer()
