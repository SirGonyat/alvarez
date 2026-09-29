"""
Inter-Process Communication (IPC) for agy-rortings.

Provides lock-free shared memory channels using POSIX shared memory (/dev/shm)
or memory-mapped buffers with atomic replacement semantics.
"""

import os
import sys
import time
import mmap
import struct
import tempfile
from typing import Optional


class SharedBuffer:
    """
    Lock-free, fast shared memory buffer between daemon and statusline.
    Uses memory-mapped file with length-prefixed protocol.
    """
    def __init__(self, filename: str, size: int = 8192):
        self.filename = filename
        self.size = size
        if sys.platform == "linux" and os.path.isdir("/dev/shm") and os.access("/dev/shm", os.W_OK):
            self.path = os.path.join("/dev/shm", filename)
        else:
            self.path = os.path.join(tempfile.gettempdir(), filename)
        self._mm: Optional[mmap.mmap] = None
        self._fd: Optional[int] = None

    def _ensure_open(self, writable: bool = False):
        if self._mm is not None:
            return
        try:
            if not os.path.exists(self.path):
                if not writable:
                    return
                with open(self.path, "wb") as f:
                    f.write(b"\x00" * self.size)

            flags = os.O_RDWR if writable else os.O_RDONLY
            prot = mmap.PROT_READ | (mmap.PROT_WRITE if writable else 0)
            self._fd = os.open(self.path, flags)
            self._mm = mmap.mmap(self._fd, self.size, prot=prot)
        except Exception:
            self._mm = None
            if self._fd is not None:
                try:
                    os.close(self._fd)
                except Exception:
                    pass
                self._fd = None

    def write(self, text: str) -> bool:
        """Atomically writes text to the buffer in /dev/shm."""
        try:
            tmp_path = f"{self.path}.tmp.{os.getpid()}"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp_path, self.path)
            return True
        except Exception:
            return False

    def read(self) -> str:
        """Reads the latest flushed payload from the shared buffer."""
        if not os.path.exists(self.path):
            return ""
        try:
            # Check file age (ignore stale buffer older than 3 seconds)
            if time.time() - os.path.getmtime(self.path) > 3.0:
                return ""
            with open(self.path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read().strip()
        except Exception:
            return ""

    def close(self):
        """Closes memory map and file descriptor."""
        if self._mm:
            try:
                self._mm.close()
            except Exception:
                pass
            self._mm = None
        if self._fd is not None:
            try:
                os.close(self._fd)
            except Exception:
                pass
            self._fd = None
