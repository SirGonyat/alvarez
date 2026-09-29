"""
DSP and Audio Spectrum Analysis for agy-rortings.

Processes PCM stereo buffers into log-spaced FFT frequency bins and Left/Right peak meters.
Renders high-density Unicode Braille spectrum equalizers.
"""

import math
from typing import Tuple, List

try:
    import numpy as np
    HAVE_NUMPY = True
except ImportError:
    HAVE_NUMPY = False

BRAILLE_DOTS = [
    [0x01, 0x08],  # Row 1 (top): left, right
    [0x02, 0x10],  # Row 2: left, right
    [0x04, 0x20],  # Row 3: left, right
    [0x40, 0x80],  # Row 4 (bottom): left, right
]


class SpectrumAnalyzer:
    """Computes FFT frequency magnitudes and renders braille equalizer graphics."""

    def __init__(self, num_bands: int = 16):
        self.num_bands = num_bands

    def process_pcm(self, pcm_bytes: bytes) -> Tuple[List[float], float, float]:
        """
        Processes 16-bit interleaved stereo PCM into normalized frequency bands and L/R RMS levels.
        Returns: (normalized_bands, rms_left, rms_right)
        """
        if not pcm_bytes or len(pcm_bytes) < 64:
            return [0.0] * self.num_bands, 0.0, 0.0

        if HAVE_NUMPY:
            return self._process_numpy(pcm_bytes)
        return self._process_fallback(pcm_bytes)

    def _process_numpy(self, pcm_bytes: bytes) -> Tuple[List[float], float, float]:
        try:
            samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            if len(samples) % 2 != 0:
                samples = samples[:-1]
            left = samples[0::2]
            right = samples[1::2]

            rms_l = float(np.sqrt(np.mean(left**2))) if len(left) > 0 else 0.0
            rms_r = float(np.sqrt(np.mean(right**2))) if len(right) > 0 else 0.0

            mono = (left + right) * 0.5
            n = len(mono)
            if n < self.num_bands:
                return [0.0] * self.num_bands, rms_l, rms_r

            window = np.hanning(n)
            fft = np.abs(np.fft.rfft(mono * window))
            fft_len = len(fft)

            # Logarithmic frequency binning
            bands = []
            log_edges = np.logspace(0, np.log10(fft_len), self.num_bands + 1)
            for i in range(self.num_bands):
                idx_start = int(log_edges[i])
                idx_end = max(idx_start + 1, int(log_edges[i + 1]))
                val = float(np.mean(fft[idx_start:idx_end])) if idx_end > idx_start else 0.0
                norm_val = min(1.0, max(0.0, val * 3.5))
                bands.append(norm_val)

            return bands, rms_l, rms_r
        except Exception:
            return [0.0] * self.num_bands, 0.0, 0.0

    def _process_fallback(self, pcm_bytes: bytes) -> Tuple[List[float], float, float]:
        # Minimalist fallback if NumPy is missing
        import struct
        count = len(pcm_bytes) // 2
        shorts = struct.unpack(f"<{count}h", pcm_bytes[: count * 2])
        if not shorts:
            return [0.0] * self.num_bands, 0.0, 0.0

        left = [s / 32768.0 for s in shorts[0::2]]
        right = [s / 32768.0 for s in shorts[1::2]]

        rms_l = math.sqrt(sum(x * x for x in left) / len(left)) if left else 0.0
        rms_r = math.sqrt(sum(x * x for x in right) / len(right)) if right else 0.0

        bands = [min(1.0, max(0.0, (rms_l + rms_r) * 1.5))] * self.num_bands
        return bands, rms_l, rms_r

    @staticmethod
    def render_braille_bars(left_height: float, right_height: float) -> str:
        """Renders a single braille character encoding two vertical bar heights [0.0 - 1.0]."""
        code = 0x2800
        l_dots = int(round(max(0.0, min(1.0, left_height)) * 4.0))
        r_dots = int(round(max(0.0, min(1.0, right_height)) * 4.0))

        # Fill dots from bottom up (Row 4 to Row 1)
        for r in range(4):
            dot_idx = 3 - r
            if l_dots > r:
                code |= BRAILLE_DOTS[dot_idx][0]
            if r_dots > r:
                code |= BRAILLE_DOTS[dot_idx][1]

        return chr(code)
