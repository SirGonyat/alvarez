"""
Hardware and Sysfs Telemetry for Alvarez.

Directly inspects Linux /proc and /sys filesystem interfaces for sub-millisecond execution,
with seamless fallback to psutil for macOS and Windows cross-platform compatibility.
Strictly observes host storage isolation (confining disk queries to root filesystem mount).
"""

import os
import glob
import time
import json
import shutil
import subprocess
import tempfile
from typing import Optional
from alvarez.core.models import HardwareStats
from alvarez.telemetry.base import TelemetryProvider

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

GPU_TJMAX = 100.0  # AMD RDNA3 / Nvidia standard thermal junction ceiling


class HardwareTelemetry(TelemetryProvider):
    """Gathers CPU, discrete GPU, memory, and filesystem metrics with psutil fallback."""

    def __init__(self, root_mount: str = "/"):
        self.root_mount = root_mount
        self.stat_cache_path = os.path.join(tempfile.gettempdir(), "alvarez_stat.json")

    def collect(self) -> HardwareStats:
        stats = HardwareStats()
        self._update_cpu(stats)
        self._update_gpu(stats)
        self._update_ram(stats)
        self._update_disk(stats)
        return stats

    def _update_cpu(self, stats: HardwareStats):
        """Measures CPU load and thermal readings."""
        # 1. Temperature via hwmon (Linux) or psutil sensors (macOS/Linux)
        if os.path.exists("/sys/class/hwmon"):
            for h in glob.glob("/sys/class/hwmon/hwmon*"):
                try:
                    name_path = f"{h}/name"
                    if os.path.exists(name_path):
                        chip_name = open(name_path).read().strip()
                        if chip_name in ("k10temp", "coretemp", "zenpower"):
                            for t in glob.glob(f"{h}/temp*_input"):
                                stats.cpu_temp = float(open(t).read().strip()) / 1000.0
                                break
                            break
                except (IOError, OSError, ValueError):
                    pass
        elif HAS_PSUTIL and hasattr(psutil, "sensors_temperatures"):
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    for name, entries in temps.items():
                        if entries:
                            stats.cpu_temp = entries[0].current
                            break
            except Exception:
                pass

        # 2. CPU Load delta via /proc/stat or psutil
        if os.path.exists("/proc/stat"):
            try:
                now_t = time.time()
                with open("/proc/stat", "r") as f:
                    fields = [int(x) for x in f.readline().split()[1:]]
                idle = fields[3] + fields[4]
                total = sum(fields)
                calculated = False

                if os.path.exists(self.stat_cache_path):
                    try:
                        with open(self.stat_cache_path, "r") as f:
                            prev = json.load(f)
                        dt_time = now_t - prev.get("ts", 0)
                        dt_total = total - prev.get("total", 0)
                        dt_idle = idle - prev.get("idle", 0)
                        if 0.05 <= dt_time <= 15.0 and dt_total > 0:
                            pct = max(0.0, min(100.0, (1.0 - (dt_idle / dt_total)) * 100.0))
                            stats.cpu_pct = int(round(pct))
                            calculated = True
                    except Exception:
                        pass

                if not calculated:
                    if hasattr(os, "getloadavg"):
                        load1, _, _ = os.getloadavg()
                        ncpus = os.cpu_count() or 1
                        stats.cpu_pct = min(100, max(0, int(round((load1 / ncpus) * 100.0))))
                    else:
                        stats.cpu_pct = 0

                try:
                    with open(self.stat_cache_path, "w") as f:
                        json.dump({"total": total, "idle": idle, "ts": now_t}, f)
                except Exception:
                    pass
            except Exception:
                pass
        elif HAS_PSUTIL:
            try:
                stats.cpu_pct = int(round(psutil.cpu_percent(interval=None)))
            except Exception:
                stats.cpu_pct = 0

    def _update_gpu(self, stats: HardwareStats):
        """Reads AMD/Nvidia discrete GPU metrics."""
        active_card = None
        for card in glob.glob("/sys/class/drm/card*/device"):
            b_file = os.path.join(card, "gpu_busy_percent")
            v_used = os.path.join(card, "mem_info_vram_used")
            v_total = os.path.join(card, "mem_info_vram_total")
            l_speed = os.path.join(card, "current_link_speed")
            l_width = os.path.join(card, "current_link_width")
            if os.path.exists(b_file) and os.path.exists(v_used):
                try:
                    stats.gpu_pct = int(open(b_file).read().strip())
                    stats.vram_used_gb = int(open(v_used).read().strip()) / (1024**3)
                    stats.vram_total_gb = int(open(v_total).read().strip()) / (1024**3)
                    if os.path.exists(l_speed) and os.path.exists(l_width):
                        spd = open(l_speed).read().strip()
                        wth = open(l_width).read().strip()
                        gen = "Gen4" if "16.0" in spd else ("Gen3" if "8.0" in spd else "Gen5")
                        stats.pcie_link = f"{gen} x{wth}"
                    active_card = card
                    break
                except Exception:
                    pass

        # Fan & Junction Temp
        hwmon_dirs = []
        if active_card:
            hwmon_dirs = glob.glob(f"{active_card}/hwmon/hwmon*")
        elif os.path.exists("/sys/class/hwmon"):
            hwmon_dirs = glob.glob("/sys/class/hwmon/hwmon*")

        for h in hwmon_dirs:
            try:
                name_path = f"{h}/name"
                if os.path.exists(name_path) and open(name_path).read().strip() == "amdgpu":
                    f_file = f"{h}/fan1_input"
                    if os.path.exists(f_file):
                        stats.fan_rpm = int(open(f_file).read().strip())
                    t1 = f"{h}/temp1_input"  # Edge
                    t2 = f"{h}/temp2_input"  # Junction
                    if os.path.exists(t1):
                        stats.gpu_temp = float(open(t1).read().strip()) / 1000.0
                    if os.path.exists(t2):
                        stats.gpu_junc = float(open(t2).read().strip()) / 1000.0
                    break
            except Exception:
                pass

        # If no sysfs AMD GPU, check for Nvidia GPU via nvidia-smi
        if not active_card:
            try:
                nv_bin = shutil.which("nvidia-smi")
            except Exception:
                nv_bin = None

            if nv_bin:
                try:
                    res = subprocess.run(
                        [nv_bin, "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu", "--format=csv,noheader,nounits"],
                        capture_output=True,
                        text=True,
                        timeout=0.1,
                    )
                    if res.returncode == 0 and res.stdout.strip():
                        parts = [x.strip() for x in res.stdout.strip().split("\n")[0].split(",")]
                        if len(parts) >= 4:
                            stats.gpu_pct = int(parts[0])
                            stats.vram_used_gb = float(parts[1]) / 1024.0
                            stats.vram_total_gb = float(parts[2]) / 1024.0
                            stats.gpu_temp = float(parts[3])
                            active_temp = max(stats.gpu_temp, stats.cpu_temp)
                            stats.thermal_headroom = max(0.0, GPU_TJMAX - active_temp)
                            return
                except Exception:
                    pass

        active_temp = max(stats.gpu_temp, stats.gpu_junc, stats.cpu_temp)
        stats.thermal_headroom = max(0.0, GPU_TJMAX - active_temp)

    def _update_ram(self, stats: HardwareStats):
        """Reads system RAM through /proc/meminfo or psutil."""
        if os.path.exists("/proc/meminfo"):
            try:
                meminfo = {}
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        p = line.split(":")
                        if len(p) == 2:
                            meminfo[p[0].strip()] = int(p[1].split()[0])
                t_kb = meminfo.get("MemTotal", 0)
                a_kb = meminfo.get("MemAvailable", 0)
                if t_kb > 0:
                    stats.ram_used_gb = (t_kb - a_kb) / (1024 * 1024)
                    stats.ram_total_gb = t_kb / (1024 * 1024)
                    stats.ram_pct = ((t_kb - a_kb) / t_kb) * 100.0
                return
            except Exception:
                pass

        if HAS_PSUTIL:
            try:
                vm = psutil.virtual_memory()
                stats.ram_used_gb = vm.used / (1024**3)
                stats.ram_total_gb = vm.total / (1024**3)
                stats.ram_pct = vm.percent
            except Exception:
                pass

    def _update_disk(self, stats: HardwareStats):
        """Reads host disk utilization strictly on the specified mount."""
        try:
            target_mount = self.root_mount if os.path.exists(self.root_mount) else "/"
            usage = shutil.disk_usage(target_mount)
            if usage.total > 0:
                stats.disk_free_gb = usage.free / (1024**3)
                stats.disk_pct = ((usage.total - usage.free) / usage.total) * 100.0
        except Exception:
            pass
