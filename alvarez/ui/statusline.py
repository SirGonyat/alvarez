"""
Statusline Multi-Line HUD Assembler for agy-rortings.

Coordinates all widgets, quotas, compute telemetry, services, and shared-memory
audio visualizer lines into a complete high-density terminal HUD.
"""

import os
import sys
import json
import time
import tempfile
from typing import List, Dict, Any, Optional
from alvarez.core.models import TelemetrySnapshot, AgentContext
from alvarez.core.ipc import SharedBuffer
from alvarez.core.ansi import (
    RESET, BOLD, DIM, COLOR_NOMINAL_CYAN, COLOR_NOMINAL_BLUE,
    COLOR_CAUTION_AMBER, COLOR_CRITICAL_RED, COLOR_NOMINAL_GREEN,
    visible_len
)
from alvarez.ui.layout import DynamicTiler
from alvarez.ui.widgets import UIWidgets
from alvarez.config import AppConfig

if sys.platform == "linux" and os.path.isdir("/dev/shm") and os.access("/dev/shm", os.W_OK):
    VIS_DATA_FILE = "/dev/shm/agy_vis_data.json"
else:
    VIS_DATA_FILE = os.path.join(tempfile.gettempdir(), "agy_vis_data.json")


class StatuslineRenderer:
    """Assembles all telemetry snapshots and context into a polished 4-line terminal HUD."""

    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or AppConfig()
        self.vis_buffer = SharedBuffer("agy_vis_line.txt")

    def render(self, snapshot: TelemetrySnapshot, ctx: AgentContext, term_width: int = 135) -> str:
        is_compact = term_width < self.config.ui.compact_breakpoint
        is_ultra_compact = term_width < self.config.ui.ultra_compact_breakpoint

        rendered_rows: List[str] = []

        # ================= LINE 1: AGENT & QUOTA CONTEXT =================
        l1_elements: List[str] = []
        l1_elements.append(UIWidgets.render_model_badge(ctx, is_compact=is_compact))
        if snapshot.credits:
            l1_elements.append(f"\033[1;38;5;220mCredits:\033[0m \033[1;37m{snapshot.credits}\033[0m")
        l1_elements.extend(UIWidgets.render_quota_chips(snapshot.quotas, is_compact=is_compact, model_name=ctx.model_name))

        if ctx.context_pct > 0:
            l1_elements.append(UIWidgets.render_context_chip(ctx))

        l1_elements.extend(UIWidgets.render_turn_chips(ctx, is_compact=is_compact))

        for row in DynamicTiler.tile_elements(l1_elements, max_width=term_width):
            rendered_rows.append(row)

        # ================= LINE 2: HARDWARE & COMPUTE TELEMETRY =================
        l2_elements = UIWidgets.render_hardware_chips(snapshot.hw, snapshot.inference, is_compact=is_compact, term_width=term_width)
        for row in DynamicTiler.tile_elements(l2_elements, max_width=term_width):
            rendered_rows.append(row)

        # ================= LINE 3: DEV SERVICES & ENVIRONMENT =================
        l3_elements = UIWidgets.render_service_chips(
            snapshot.git,
            snapshot.docker,
            snapshot.inference,
            snapshot.weather,
            snapshot.tasks,
            snapshot.media,
            volume=snapshot.volume,
            is_compact=is_compact
        )
        for row in DynamicTiler.tile_elements(l3_elements, max_width=term_width):
            rendered_rows.append(row)

        # ================= LINE 4: REAL-TIME AUDIO VISUALIZER =================
        l4_rows: Optional[List[str]] = None

        # Priority 1: Direct live FFT data from companion daemon
        if os.path.exists(VIS_DATA_FILE):
            try:
                if time.time() - os.path.getmtime(VIS_DATA_FILE) < 3.0:
                    with open(VIS_DATA_FILE, "r") as df:
                        v_data = json.load(df)
                    if v_data and (time.time() - v_data.get("timestamp", 0) < 3.0):
                        l4_rows = UIWidgets.render_visualizer_line(
                            title=v_data.get("title", ""),
                            norm_half=v_data.get("norm_half", []),
                            rms_l=v_data.get("rms_l", 0.0),
                            rms_r=v_data.get("rms_r", 0.0),
                            term_width=term_width
                        )
            except Exception:
                pass

        # Priority 2: Pre-formatted live string from shared buffer
        if not l4_rows:
            vis_line = self.vis_buffer.read()
            if vis_line:
                l4_rows = [vis_line]

        # Priority 3: Fallback synth wave if playing, else idle line
        if not l4_rows:
            if snapshot.media.status == "playing":
                t_raw = snapshot.media.title or "Audio Stream"
                l4_rows = UIWidgets.render_visualizer_line(
                    title=t_raw,
                    norm_half=None,
                    rms_l=1500.0,
                    rms_r=1500.0,
                    term_width=term_width
                )
            else:
                l4_rows = UIWidgets.render_idle_line(term_width=term_width)

        if l4_rows:
            for r in l4_rows:
                rendered_rows.append(r)

        return "\n".join(rendered_rows)
