"""
Core Data Models for agy-rortings.

Provides strongly-typed dataclasses for system telemetry, inference metrics,
agent context, quota accounting, and media stream state.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class HardwareStats:
    """Snapshot of host system hardware telemetry."""
    cpu_pct: int = 0
    cpu_temp: float = 0.0
    fan_rpm: int = 0
    gpu_pct: int = 0
    gpu_temp: float = 0.0
    gpu_junc: float = 0.0
    pcie_link: str = "Gen4 x16"
    vram_used_gb: float = 0.0
    vram_total_gb: float = 16.0
    ram_used_gb: float = 0.0
    ram_total_gb: float = 32.0
    ram_pct: float = 0.0
    disk_free_gb: float = 0.0
    disk_pct: float = 0.0
    thermal_headroom: float = 55.0


@dataclass
class InferenceStats:
    """Local LLM inference performance and KV-cache utilization."""
    rtt_ms: Optional[float] = None
    kv_cache_gb: float = 0.0
    loaded_model: Optional[str] = None


@dataclass
class ContainerStats:
    """Container runtime health (Docker/Podman)."""
    running: int = 0
    total: int = 0
    unhealthy: bool = False


@dataclass
class GitStats:
    """VCS status for the current working directory."""
    branch: Optional[str] = None
    added: int = 0
    deleted: int = 0
    dirty: bool = False


@dataclass
class QuotaInfo:
    """LLM API Rate Limit & Quota state (e.g. 5-hour window or weekly allowance)."""
    remaining_fraction: float = 1.0
    reset_in_seconds: Optional[int] = None
    reset_time: Optional[str] = None

    @property
    def percentage(self) -> float:
        return max(0.0, min(100.0, self.remaining_fraction * 100.0))

    @property
    def is_refreshed(self) -> bool:
        return self.reset_in_seconds is not None and self.reset_in_seconds <= 0


@dataclass
class AgentContext:
    """Contextual metadata about the active AI agent conversation."""
    model_name: str = "Antigravity Brain"
    effort: Optional[str] = None
    turn_steps: int = 0
    total_steps: int = 0
    active_tool: Optional[str] = None
    turn_tokens: int = 0
    velocity: int = 0
    context_pct: float = 0.0
    context_size: int = 1048576

    def __post_init__(self):
        if isinstance(self.model_name, dict):
            if not self.effort and self.model_name.get("effort"):
                self.effort = self.model_name.get("effort")
            self.model_name = (
                self.model_name.get("display_name")
                or self.model_name.get("id")
                or "Antigravity Brain"
            )
        elif not isinstance(self.model_name, str):
            self.model_name = str(self.model_name)


@dataclass
class StreamState:
    """Media streamer playback state."""
    status: str = "stopped"  # "playing", "paused", "stopped"
    title: str = ""
    preset: str = "live"
    pid: Optional[int] = None
    runner_pid: Optional[int] = None
    url: Optional[str] = None
    source: Optional[str] = None
    index: int = 0
    volume: int = 100
    timestamp: float = 0.0
    resume_on_boot: bool = False


@dataclass
class TelemetrySnapshot:
    """Complete aggregated snapshot of system and agent telemetry."""
    hw: HardwareStats = field(default_factory=HardwareStats)
    inference: InferenceStats = field(default_factory=InferenceStats)
    docker: ContainerStats = field(default_factory=ContainerStats)
    git: GitStats = field(default_factory=GitStats)
    quotas: Dict[str, QuotaInfo] = field(default_factory=dict)
    media: StreamState = field(default_factory=StreamState)
    weather: str = ""
    tasks: List[str] = field(default_factory=list)
    volume: int = 0
    credits: Optional[str] = None
    timestamp: float = 0.0
