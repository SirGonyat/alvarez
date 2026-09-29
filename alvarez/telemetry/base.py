"""
Base interface for Telemetry Providers.
"""

from abc import ABC, abstractmethod
from typing import Any


class TelemetryProvider(ABC):
    """Abstract base class for modular telemetry collectors."""

    @abstractmethod
    def collect(self) -> Any:
        """Collects and returns updated telemetry snapshot."""
        pass
