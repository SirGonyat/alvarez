"""
UI Visual Widgets and Components for agy-rortings.

Provides formatted ANSI badges, mini progress bars, quota chips, system telemetry,
and real-time audio visualizer layouts.
"""

import math
from datetime import datetime
from typing import Dict, Optional, List, Any
from alvarez.core.ansi import (
    RESET, BOLD, DIM,
    COLOR_NOMINAL_CYAN, COLOR_NOMINAL_GREEN, COLOR_NOMINAL_BLUE,
    COLOR_NOMINAL_PURPLE, COLOR_CAUTION_AMBER, COLOR_CRITICAL_RED,
    COLOR_CRITICAL_FLASH, COLOR_MUTED, make_mini_bar, format_delta_time,
    make_vu_bar, visible_len, truncate_ansi
)
from alvarez.core.models import (
    AgentContext, HardwareStats, InferenceStats, ContainerStats,
    GitStats, QuotaInfo, StreamState
)

CHARS = " ▂▃▄▅▆▇█"
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


class UIWidgets:
    """Renders formatted ANSI chips and widgets for the statusline."""

    @staticmethod
    def render_model_badge(ctx: AgentContext, is_compact: bool = False) -> str:
        model_name = ctx.model_name
        if isinstance(model_name, dict):
            model_name = model_name.get("display_name") or model_name.get("id") or "Antigravity Brain"
        elif not isinstance(model_name, str):
            model_name = str(model_name)

        short_model = model_name.replace("Gemini ", "").strip()
        display_name = short_model if is_compact else model_name
        model_chip = f"{BOLD}{COLOR_NOMINAL_CYAN}✦ [{display_name}]{RESET}"

        if not ctx.effort:
            return model_chip

        eff_cap = str(ctx.effort).strip().capitalize()
        eff_upper = eff_cap.upper()
        if "HIGH" in eff_upper:
            eff_col = COLOR_NOMINAL_PURPLE
        elif "MED" in eff_upper:
            eff_col = COLOR_NOMINAL_CYAN
        else:
            eff_col = COLOR_NOMINAL_GREEN

        eff_label = eff_cap[:3] if is_compact else eff_cap
        return f"{model_chip} {eff_col}{eff_label}{RESET}"

    @staticmethod
    def render_quota_chips(quotas: Dict[str, QuotaInfo], is_compact: bool = False, model_name: Optional[str] = None) -> List[str]:
        chips = []
        bar_w = 4 if is_compact else 6

        def format_bucket(name: str, q: Optional[QuotaInfo]) -> Optional[str]:
            if not q:
                return None
            pct = q.percentage
            t = format_delta_time(q.reset_in_seconds)
            bar, col = make_mini_bar(pct, width=bar_w)
            return f"{name}: {col}{pct:.0f}%{RESET}[{bar}] {t}"

        # Resolve active model identity for quota display filtering
        m_str = str(model_name or "").lower()
        is_gemini_active = "gemini" in m_str or not m_str
        is_3p_active = any(k in m_str for k in ("claude", "gpt", "openai", "codex", "sonnet", "opus", "haiku"))

        # Gemini limits
        q_gem_5h = format_bucket("5h", quotas.get("gemini-5h"))
        q_gem_wk = format_bucket("Wk", quotas.get("gemini-weekly"))
        gem_parts = [p for p in (q_gem_5h, q_gem_wk) if p]

        # Claude & GPT-OSS limits
        q_3p_5h = format_bucket("5h", quotas.get("3p-5h"))
        q_3p_wk = format_bucket("Wk", quotas.get("3p-weekly"))
        p3_parts = [p for p in (q_3p_5h, q_3p_wk) if p]

        if is_3p_active and p3_parts:
            p3_label = f"{BOLD}\033[38;5;208mClaude/GPT-OSS:{RESET}"
            chips.append(f"{p3_label} {' '.join(p3_parts)}")
            if not is_compact and gem_parts:
                gem_label = f"{DIM}Gemini:{RESET}"
                chips.append(f"{gem_label} {' '.join(gem_parts)}")
        elif gem_parts:
            gem_label = f"{BOLD}{COLOR_NOMINAL_CYAN}Gemini:{RESET}"
            chips.append(f"{gem_label} {' '.join(gem_parts)}")
            if not is_compact and is_3p_active and p3_parts:
                p3_label = f"{BOLD}\033[38;5;208mClaude/GPT-OSS:{RESET}"
                chips.append(f"{p3_label} {' '.join(p3_parts)}")
        elif p3_parts:
            p3_label = f"{BOLD}\033[38;5;208mClaude/GPT-OSS:{RESET}"
            chips.append(f"{p3_label} {' '.join(p3_parts)}")

        return chips

    @staticmethod
    def render_context_chip(ctx: AgentContext) -> str:
        ctx_pct = ctx.context_pct
        ctx_sz = ctx.context_size or 1048576
        sz_str = f"{ctx_sz // 1000000}M" if ctx_sz >= 1000000 else f"{ctx_sz // 1000}k"
        ctx_col = COLOR_CRITICAL_RED if ctx_pct > 80 else (COLOR_CAUTION_AMBER if ctx_pct > 60 else COLOR_NOMINAL_GREEN)
        return f"Ctx: {ctx_col}{ctx_pct:.1f}%/{sz_str}{RESET}"

    @staticmethod
    def render_turn_chips(ctx: AgentContext, is_compact: bool = False) -> List[str]:
        chips = []
        if ctx.turn_steps > 0:
            step_col = COLOR_CRITICAL_RED if ctx.turn_steps > 25 else (COLOR_CAUTION_AMBER if ctx.turn_steps > 15 else COLOR_NOMINAL_BLUE)
            tool_str = f" {COLOR_CAUTION_AMBER}{ctx.active_tool}*{RESET}" if ctx.active_tool else ""
            if is_compact:
                chips.append(f"T: {step_col}{ctx.turn_steps}{RESET} {DIM}({ctx.total_steps}){RESET}{tool_str}")
            else:
                chips.append(f"Turn: {step_col}{ctx.turn_steps}{RESET} {DIM}({ctx.total_steps} tot){RESET}{tool_str}")

        vel_str = f"⚡ {ctx.velocity} t/s" if ctx.velocity > 0 else ""
        if ctx.turn_tokens > 0:
            chips.append(f"~{ctx.turn_tokens:,} tok {vel_str}".strip())
        elif vel_str:
            chips.append(vel_str)

        return chips

    @staticmethod
    def render_hardware_chips(hw: HardwareStats, inf: Optional[InferenceStats] = None, is_compact: bool = False, term_width: int = 135) -> List[str]:
        def make_bar(pct, col, width=20):
            filled = int((pct / 100.0) * width)
            filled = max(0, min(width, filled))
            return f"{col}{'█'*filled}{DIM}{'░'*(width-filled)}{RESET}"
            
        bar_w = 20 if term_width > 100 else 10
        
        # CPU
        cpu_col = COLOR_CRITICAL_RED if hw.cpu_pct > 85 else (COLOR_CAUTION_AMBER if hw.cpu_pct > 65 else COLOR_NOMINAL_GREEN)
        cpu_temp = f"{hw.cpu_temp:.0f}°C" if hw.cpu_temp > 0 else "---"
        cpu_bar = make_bar(hw.cpu_pct, cpu_col, bar_w)
        cpu_str = f"{BOLD}CPU{RESET} [{cpu_temp:>5}] {cpu_col}{hw.cpu_pct:>3}%{RESET} {cpu_bar}"

        # GPU
        gpu_col = COLOR_CRITICAL_RED if hw.gpu_pct > 90 else (COLOR_CAUTION_AMBER if hw.gpu_pct > 70 else COLOR_NOMINAL_GREEN)
        gpu_temp = f"{hw.gpu_temp:.0f}°C" if hw.gpu_temp > 0 else "---"
        gpu_bar = make_bar(hw.gpu_pct, gpu_col, bar_w)
        gpu_str = f"{BOLD}GPU{RESET} [{gpu_temp:>5}] {gpu_col}{hw.gpu_pct:>3}%{RESET} {gpu_bar}"

        # RAM
        ram_col = COLOR_CRITICAL_RED if hw.ram_pct > 85 else (COLOR_CAUTION_AMBER if hw.ram_pct > 70 else COLOR_NOMINAL_GREEN)
        ram_bar = make_bar(hw.ram_pct, ram_col, bar_w)
        ram_str = f"{BOLD}RAM{RESET} [{hw.ram_used_gb:>4.1f}G] {ram_col}{hw.ram_pct:>3.0f}%{RESET} {ram_bar}"
        
        # VRAM
        vram_pct = (hw.vram_used_gb / hw.vram_total_gb) * 100.0 if hw.vram_total_gb > 0 else 0
        vram_col = COLOR_CRITICAL_FLASH if vram_pct > 95 else (COLOR_CAUTION_AMBER if vram_pct > 85 else COLOR_NOMINAL_BLUE)
        vram_bar = make_bar(vram_pct, vram_col, bar_w)
        vram_str = f"{BOLD}VRM{RESET} [{hw.vram_used_gb:>4.1f}G] {vram_col}{vram_pct:>3.0f}%{RESET} {vram_bar}"

        # Headroom & Dedicated Host Disk Telemetry
        headroom = hw.thermal_headroom
        head_col = COLOR_CRITICAL_FLASH if headroom < 5 else (COLOR_CAUTION_AMBER if headroom < 15 else COLOR_NOMINAL_GREEN)
        sys_head = f"{BOLD}SYS{RESET} [Headroom: {head_col}Δ{headroom:.0f}°C{RESET}]"

        d_col = COLOR_CRITICAL_RED if hw.disk_pct > 90 else (COLOR_CAUTION_AMBER if hw.disk_pct > 80 else COLOR_NOMINAL_GREEN)
        disk_bar = make_bar(hw.disk_pct, d_col, bar_w)
        disk_str = f"{BOLD}Disk{RESET} [{hw.disk_free_gb:>5.1f}G free] {d_col}{hw.disk_pct:>3.0f}%{RESET} {disk_bar}"

        # Combine into wide rows
        if term_width > 120:
            row1 = f"{cpu_str}    {ram_str}"
            row2 = f"{gpu_str}    {vram_str}    {sys_head}"
            row3 = f"{disk_str}"
            return [row1, row2, row3]
        else:
            return [cpu_str, ram_str, gpu_str, vram_str, sys_head, disk_str]

    @staticmethod
    def render_service_chips(
        git: GitStats,
        docker: ContainerStats,
        inf: Optional[InferenceStats],
        weather: str,
        tasks: List[str],
        media: StreamState,
        volume: int = 0,
        is_compact: bool = False
    ) -> List[str]:
        # Date & Time + Weather
        now = datetime.now()
        dt_fmt = "%b %d %H:%M" if is_compact else "%b %d %H:%M:%S"
        dt_str = f"{now.strftime(dt_fmt)} {weather}".strip()

        # Git
        if git.branch:
            if git.dirty:
                diff_badge = f"{COLOR_CAUTION_AMBER}(+{git.added}/-{git.deleted})*{RESET}"
                git_str = f"git:({git.branch} {diff_badge})"
            else:
                git_str = f"git:({git.branch} {COLOR_NOMINAL_GREEN}✔{RESET})"
        else:
            git_str = f"{COLOR_MUTED}none{RESET}"

        # Docker
        if docker.total > 0:
            dk_col = COLOR_CRITICAL_FLASH if docker.unhealthy else (COLOR_NOMINAL_GREEN if docker.running == docker.total else COLOR_CAUTION_AMBER)
            dk_str = f"🐳 {dk_col}{docker.running}/{docker.total}{RESET}"
        else:
            dk_str = f"🐳 {COLOR_MUTED}0/0{RESET}"

        # RTT / Network
        if inf and inf.rtt_ms is not None:
            rtt_col = COLOR_CRITICAL_RED if inf.rtt_ms > 150 else (COLOR_CAUTION_AMBER if inf.rtt_ms > 50 else COLOR_NOMINAL_GREEN)
            rtt_str = f"🌐 {rtt_col}{inf.rtt_ms:.1f}ms{RESET}"
        else:
            rtt_str = f"🌐 {COLOR_MUTED}down{RESET}"

        # Active Tasks
        if is_compact and len(tasks) > 1:
            tasks_str = f"{len(tasks)} tasks"
        else:
            tasks_str = f"{', '.join(tasks)}" if tasks else f"{COLOR_MUTED}idle{RESET}"

        # Media status & volume
        vol_pct = volume or media.volume
        if media.status == "playing":
            preset_name = media.preset.capitalize() if media.preset else "Stream"
            media_str = f"{preset_name} 🔊 {vol_pct}%"
        else:
            media_str = f"{COLOR_MUTED}⏹ idle 🔊 {vol_pct}%{RESET}"

        return [dt_str, git_str, dk_str, rtt_str, tasks_str, media_str]

    @staticmethod
    def render_visualizer_line(
        title: str,
        norm_half: Optional[List[float]] = None,
        rms_l: float = 0.0,
        rms_r: float = 0.0,
        term_width: int = 135,
        frame_idx: int = 0
    ) -> List[str]:
        badge = f"{BOLD}{COLOR_NOMINAL_PURPLE}🎵{RESET}"
        clean_title = title or "Active Stream"

        if term_width >= 125:
            half_bars = 20
            max_title = 24
            vu_w = 4
            show_live_txt = True
        elif term_width >= 100:
            half_bars = 14
            max_title = 18
            vu_w = 4
            show_live_txt = True
        elif term_width >= 80:
            half_bars = 9
            max_title = 14
            vu_w = 3
            show_live_txt = False
        else:
            half_bars = 6
            max_title = 10
            vu_w = 2
            show_live_txt = False

        display_title = (clean_title[:max_title - 1] + "…") if len(clean_title) > max_title else clean_title
        t_str = f"{COLOR_NOMINAL_CYAN}{display_title}{RESET}"

        # Build equalizer bars
        if norm_half and len(norm_half) > 0:
            try:
                import numpy as np
                norm_arr = np.array(norm_half)
                if half_bars == len(norm_arr):
                    sub = norm_arr
                else:
                    indices = np.round(np.linspace(0, len(norm_arr) - 1, half_bars)).astype(int)
                    sub = norm_arr[indices]
                mirrored = np.concatenate([sub[::-1], sub])
                bar_items = [f"{SPECTRUM_COLORS[min(int(lvl), len(SPECTRUM_COLORS)-1)]}{CHARS[min(int(lvl), 7)]}{RESET}" for lvl in mirrored]
                eq_bars = "".join(bar_items)
            except Exception:
                eq_bars = ""
        else:
            # Fallback animated synthetic waveform
            t = frame_idx * 0.15
            sub = []
            for i in range(half_bars):
                v = (math.sin(t * 3.5 + i * (5.0 / half_bars)) + math.cos(t * 2.2 - i * (3.6 / half_bars)) * 0.5)
                lvl = int(max(0, min(7, (v + 1.5) / 3.0 * 7)))
                sub.append(lvl)
            mirrored = sub[::-1] + sub
            bar_items = [f"{SPECTRUM_COLORS[min(lvl, len(SPECTRUM_COLORS)-1)]}{CHARS[lvl]}{RESET}" for lvl in mirrored]
            eq_bars = "".join(bar_items)

        vu_l = make_vu_bar(rms_l, width=vu_w)
        vu_r = make_vu_bar(rms_r, width=vu_w)
        vu_str = f"{DIM}L[{RESET}{vu_l}{DIM}]{RESET} {DIM}R[{RESET}{vu_r}{DIM}]{RESET}"
        live_dot = f"{COLOR_NOMINAL_GREEN}● LIVE{RESET}" if show_live_txt else f"{COLOR_NOMINAL_GREEN}●{RESET}"

        if term_width < 65:
            row1 = f"{badge} {t_str} {COLOR_MUTED}│{RESET} {live_dot}"
            row2 = f"{eq_bars} {COLOR_MUTED}│{RESET} {vu_str}"
            return [row1, row2]
        else:
            line = f"{badge} {t_str} {COLOR_MUTED}│{RESET} {eq_bars} {COLOR_MUTED}│{RESET} {vu_str} {COLOR_MUTED}│{RESET} {live_dot}"
            return [line]

    @staticmethod
    def render_idle_line(term_width: int = 135) -> List[str]:
        msg = " ⏹ idle (no active audio) "
        if term_width < 45:
            return [f"{DIM}🎵 ⏹ idle{RESET}"]
        dash_len = max(2, (term_width - len(msg) - 4) // 2)
        dashes = "─" * dash_len
        return [f"{DIM}🎵 {dashes}{msg}{dashes}{RESET}"]
