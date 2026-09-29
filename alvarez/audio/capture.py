"""
Audio Capture Engine for agy-rortings.

Captures real-time PCM audio streams from PipeWire desktop sink monitor (@DEFAULT_AUDIO_SINK@.monitor).
"""

import os
import subprocess
import shutil
try:
    import fcntl
except ImportError:
    fcntl = None

from typing import Optional


class AudioCapture:
    """Spawns and manages a non-blocking PipeWire audio recorder stream."""

    def __init__(self, sample_rate: int = 8000, channels: int = 2):
        self.sample_rate = sample_rate
        self.channels = channels
        self.process: Optional[subprocess.Popen] = None

    def start(self) -> bool:
        """Starts pw-record subprocess reading from the default audio sink monitor."""
        if self.process is not None and self.process.poll() is None:
            return True

        cmd = []
        if shutil.which("pw-record"):
            cmd = [
                "pw-record",
                "--target=@DEFAULT_AUDIO_SINK@",
                "-P", "{ stream.capture.sink = true }",
                f"--rate={self.sample_rate}",
                f"--channels={self.channels}",
                "--format=s16",
                "--latency=25ms",
                "-",
            ]
        elif shutil.which("parec"):
            cmd = [
                "parec",
                "--format=s16le",
                f"--rate={self.sample_rate}",
                f"--channels={self.channels}",
            ]
        else:
            return False

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
            # Set stdout to non-blocking
            if self.process.stdout:
                fd = self.process.stdout.fileno()
                if fcntl:
                    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
                    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
                elif hasattr(os, "set_blocking"):
                    os.set_blocking(fd, False)
            return True
        except Exception:
            self.process = None
            return False

    def read_latest_chunk(self, chunk_size: int = 1600) -> bytes:
        """Drains non-blocking buffer and returns the most recent PCM audio chunk."""
        if not self.process or not self.process.stdout:
            return b""

        chunks = []
        try:
            fd = self.process.stdout.fileno()
            while True:
                data = os.read(fd, 4096)
                if not data:
                    break
                chunks.append(data)
        except (BlockingIOError, InterruptedError, OSError):
            pass

        if not chunks:
            return b""

        raw_all = b"".join(chunks)
        return raw_all[-chunk_size:] if len(raw_all) >= chunk_size else raw_all


    def stop(self):
        """Terminates the audio capture subprocess."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=0.2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None
