"""
ANSI TrueColor and Terminal Formatting Utilities for agy-rortings.

Provides precise string-length calculation (stripping invisible escape codes),
safe ANSI truncation, mini progress bar rendering, and human-friendly time delta formatting.
"""

import re
from typing import Tuple

# --- ANSI Formatting Constants ---
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
BLINK = "\033[5m"

# Semantic Color Codes (TrueColor 24-bit)
COLOR_NOMINAL_CYAN = "\033[38;2;80;200;240m"
COLOR_NOMINAL_GREEN = "\033[38;2;80;225;120m"
COLOR_NOMINAL_BLUE = "\033[38;2;100;165;255m"
COLOR_NOMINAL_PURPLE = "\033[38;2;190;130;255m"
COLOR_CAUTION_AMBER = "\033[38;2;255;185;35m"
COLOR_CRITICAL_RED = "\033[1;38;2;255;65;65m"
COLOR_CRITICAL_FLASH = "\033[1;5;38;2;255;45;45m"
COLOR_MUTED = "\033[38;2;105;115;130m"

# Audio Spectrum Ramp Characters
SPECTRUM_CHARS = " ▂▃▄▅▆▇█"
SPECTRUM_COLORS = [
    COLOR_NOMINAL_CYAN,
    COLOR_NOMINAL_CYAN,
    COLOR_NOMINAL_BLUE,
    COLOR_NOMINAL_BLUE,
    COLOR_NOMINAL_PURPLE,
    "\033[38;2;230;100;240m",
    "\033[38;2;255;90;200m",
    COLOR_CAUTION_AMBER,
]

ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')


def visible_len(text: str) -> int:
    """Calculates the rendered visible length of a string, omitting ANSI escape sequences."""
    return len(ANSI_RE.sub('', text))


def truncate_ansi(text: str, max_vis_len: int) -> str:
    """
    Truncates text to max_vis_len visible characters while safely preserving ANSI color sequences.
    Appends an ellipsis ('…') and RESET when truncated.
    """
    if visible_len(text) <= max_vis_len:
        return text

    result = []
    vis_count = 0
    in_ansi = False
    ansi_buf = []

    for char in text:
        if char == '\033':
            in_ansi = True
            ansi_buf.append(char)
        elif in_ansi:
            ansi_buf.append(char)
            if char in 'mHJhlsK':
                in_ansi = False
                result.append("".join(ansi_buf))
                ansi_buf = []
        else:
            if vis_count < max_vis_len - 1:
                result.append(char)
                vis_count += 1
            else:
                result.append("…")
                break

    result.append(RESET)
    return "".join(result)


def format_delta_time(seconds: int | float | None) -> str:
    """Formats a duration in seconds into a compact human-readable string (e.g. '4d19h', '1h2m', '18m', 'now')."""
    if seconds is None or seconds <= 0:
        return "now"
    sec = int(round(seconds))
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m"
    if sec < 86400:
        h = sec // 3600
        m = (sec % 3600) // 60
        return f"{h}h{m}m" if m > 0 else f"{h}h"
    d = sec // 86400
    h = (sec % 86400) // 3600
    return f"{d}d{h}h" if h > 0 else f"{d}d"


def make_mini_bar(percentage: float, width: int = 6) -> Tuple[str, str]:
    """
    Generates a compact unicode progress bar string with smooth block characters and semantic color.

    Returns:
        (bar_string, color_escape_code)
    """
    pct = max(0.0, min(100.0, percentage))
    filled_blocks = int(round((pct / 100.0) * width))

    if pct > 50.0:
        col = COLOR_NOMINAL_GREEN
    elif pct > 20.0:
        col = COLOR_CAUTION_AMBER
    else:
        col = COLOR_CRITICAL_RED

    bar = f"{col}{'█' * filled_blocks}{DIM}{'░' * (width - filled_blocks)}{RESET}"
    return bar, col


def make_vu_bar(rms: float, width: int = 4) -> str:
    """Renders a tricolor Left/Right audio VU peak meter."""
    pct = min(1.0, max(0.0, (rms / 3500.0) ** 0.55)) if rms > 15 else 0.0
    filled = int(round(pct * width))
    if width >= 4:
        g = "█" * min(2, filled)
        a = "█" * max(0, min(1, filled - 2))
        r = "█" * max(0, filled - 3)
    elif width == 3:
        g = "█" * min(1, filled)
        a = "█" * max(0, min(1, filled - 1))
        r = "█" * max(0, filled - 2)
    else:
        g = "█" * min(1, filled)
        a = ""
        r = "█" * max(0, filled - 1)
    e = " " * (width - filled)
    return f"{COLOR_NOMINAL_GREEN}{g}{COLOR_CAUTION_AMBER}{a}{COLOR_CRITICAL_RED}{r}{DIM}{e}{RESET}"
