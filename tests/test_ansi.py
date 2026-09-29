"""
Unit tests for ANSI formatting, visible length calculation, and safe truncation.
"""

from alvarez.core.ansi import (
    visible_len,
    truncate_ansi,
    make_mini_bar,
    format_delta_time,
    RESET,
    BOLD,
    COLOR_NOMINAL_CYAN,
    COLOR_NOMINAL_GREEN,
    COLOR_CRITICAL_RED,
)


def test_visible_len():
    assert visible_len("hello world") == 11
    assert visible_len(f"{BOLD}hello{RESET} world") == 11
    assert visible_len(f"{COLOR_NOMINAL_CYAN}colored text{RESET}") == 12
    assert visible_len("") == 0


def test_truncate_ansi():
    text = f"{COLOR_NOMINAL_CYAN}Antigravity Developer HUD Statusline{RESET}"
    truncated = truncate_ansi(text, 15)
    # Visible length should not exceed 15
    assert visible_len(truncated) <= 15
    assert truncated.endswith(f"…{RESET}")

    # No-op if text fits
    short_text = f"{COLOR_NOMINAL_GREEN}Short{RESET}"
    assert truncate_ansi(short_text, 10) == short_text


def test_format_delta_time():
    assert format_delta_time(0) == "now"
    assert format_delta_time(-10) == "now"
    assert format_delta_time(45) == "45s"
    assert format_delta_time(125) == "2m"
    assert format_delta_time(3660) == "1h1m"
    assert format_delta_time(18000) == "5h"
    assert format_delta_time(86400 * 4 + 3600 * 19) == "4d19h"
    assert format_delta_time(None) == "now"


def test_make_mini_bar():
    bar_full, col_full = make_mini_bar(100.0, width=6)
    assert "█" * 6 in bar_full
    assert col_full == COLOR_NOMINAL_GREEN

    bar_empty, col_empty = make_mini_bar(0.0, width=6)
    assert "░" * 6 in bar_empty
    assert col_empty == COLOR_CRITICAL_RED
