"""
Container and Local Inference Telemetry for agy-rortings.

Inspects Docker daemon health and local Ollama inference RTT via lightweight direct sockets.
"""

import os
import socket
import json
import time
import subprocess
from typing import Tuple
from alvarez.core.models import ContainerStats, InferenceStats, GitStats


class ContainerTelemetry:
    """Lightweight socket inspector for Docker, Ollama, and Git."""

    def __init__(self, docker_socket: str = "/var/run/docker.sock", ollama_host: str = "127.0.0.1", ollama_port: int = 11434):
        self.docker_socket = docker_socket
        self.ollama_host = ollama_host
        self.ollama_port = ollama_port

    def inspect_docker(self) -> ContainerStats:
        """Inspects Docker container count and health status via raw Unix socket."""
        stats = ContainerStats()
        if not os.path.exists(self.docker_socket):
            return stats

        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.08)
            s.connect(self.docker_socket)
            s.sendall(b"GET /containers/json?all=1 HTTP/1.0\r\nHost: localhost\r\n\r\n")
            res = b""
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                res += chunk
            s.close()

            parts = res.split(b"\r\n\r\n", 1)
            if len(parts) == 2:
                containers = json.loads(parts[1].decode("utf-8", errors="ignore"))
                stats.total = len(containers)
                running = 0
                unhealthy = False
                for c in containers:
                    if c.get("State") == "running":
                        running += 1
                    status = c.get("Status", "").lower()
                    if "unhealthy" in status:
                        unhealthy = True
                stats.running = running
                stats.unhealthy = unhealthy
        except Exception:
            pass
        return stats

    def inspect_ollama(self) -> InferenceStats:
        """Measures RTT to local Ollama server and checks loaded models."""
        stats = InferenceStats()
        t0 = time.perf_counter()
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.08)
            s.connect((self.ollama_host, self.ollama_port))
            stats.rtt_ms = round((time.perf_counter() - t0) * 1000.0, 1)

            req = b"GET /api/ps HTTP/1.1\r\nHost: 127.0.0.1:11434\r\nConnection: close\r\n\r\n"
            s.sendall(req)
            resp = b""
            while True:
                chunk = s.recv(2048)
                if not chunk:
                    break
                resp += chunk
            s.close()

            parts = resp.split(b"\r\n\r\n", 1)
            if len(parts) == 2:
                payload = json.loads(parts[1].decode("utf-8", errors="ignore"))
                models = payload.get("models", [])
                if models:
                    stats.loaded_model = models[0].get("name", "local-llm")
                    vram_bytes = models[0].get("size_vram", 0)
                    stats.kv_cache_gb = round(vram_bytes / (1024**3), 2)
        except Exception:
            stats.rtt_ms = None
            stats.loaded_model = None
            stats.kv_cache_gb = 0.0
        return stats

    @staticmethod
    def inspect_git(cwd: str = ".") -> GitStats:
        """Inspects Git branch and dirty state in the target working directory."""
        stats = GitStats()
        try:
            # Check branch
            branch_out = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=0.15,
            )
            if branch_out.returncode == 0:
                stats.branch = branch_out.stdout.strip()

            # Check dirty status
            status_out = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=0.2,
            )
            if status_out.returncode == 0:
                lines = [l for l in status_out.stdout.splitlines() if l.strip()]
                stats.dirty = len(lines) > 0
                stats.added = sum(1 for l in lines if l.startswith("A") or l.startswith("M") or l.startswith("?"))
                stats.deleted = sum(1 for l in lines if l.startswith("D"))
        except Exception:
            pass
        return stats
