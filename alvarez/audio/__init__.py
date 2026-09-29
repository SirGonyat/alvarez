"""
Audio and DSP Subsystem for agy-rortings.

Provides real-time PCM audio capture, spectrum analysis, and background media streaming.
"""

from alvarez.audio.capture import AudioCapture
from alvarez.audio.dsp import SpectrumAnalyzer
from alvarez.audio.player import StreamPlayer

__all__ = ["AudioCapture", "SpectrumAnalyzer", "StreamPlayer"]
