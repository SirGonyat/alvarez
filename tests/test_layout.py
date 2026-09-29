"""
Unit tests for DynamicTiler row packing and width constraint enforcement.
"""

from alvarez.ui.layout import DynamicTiler
from alvarez.core.ansi import visible_len, COLOR_NOMINAL_CYAN, RESET


def test_dynamic_tiler_wrapping():
    elements = [
        f"{COLOR_NOMINAL_CYAN}Model: Gemini 3.8{RESET}",
        "5h: 85% [■■■■··] 4h 12m",
        "Wk: 92% [■■■■■·] 2d 14h",
        "Ctx: 12.5%/1M",
        "Turn: 4 (12 tot)",
    ]

    # Max width 50: elements must split across multiple rows without any single row exceeding 50
    rows = DynamicTiler.tile_elements(elements, max_width=50, separator=" │ ")
    assert len(rows) > 1

    for row in rows:
        assert visible_len(row) <= 50


def test_dynamic_tiler_empty():
    assert DynamicTiler.tile_elements([], max_width=80) == []
    assert DynamicTiler.tile_elements(["", "   "], max_width=80) == []
