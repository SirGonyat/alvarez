"""
Antigravity and LLM Quota Telemetry for agy-rortings.

Parses active rate limits, 5-hour rolling windows, weekly caps, and reset timestamps.
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
from alvarez.core.models import QuotaInfo


class QuotaTelemetry:
    """Parses and computes status for LLM rate limits."""

    @staticmethod
    def parse_quotas(payload_quota: Optional[Dict[str, Any]]) -> Dict[str, QuotaInfo]:
        """
        Parses raw quota dictionary from Antigravity CLI payload into typed QuotaInfo objects.
        """
        result: Dict[str, QuotaInfo] = {}
        if not payload_quota or not isinstance(payload_quota, dict):
            return result

        for name, data in payload_quota.items():
            if not isinstance(data, dict):
                continue

            rem_fraction = float(data.get("remaining_fraction", 1.0))
            reset_sec = data.get("reset_in_seconds")
            reset_time = data.get("reset_time")

            # Calculate dynamic remaining seconds from reset_time if provided
            if reset_time:
                try:
                    dt = datetime.fromisoformat(reset_time.replace("Z", "+00:00"))
                    diff = int((dt - datetime.now(timezone.utc)).total_seconds())
                    reset_sec = max(0, diff)
                except Exception:
                    pass

            result[name] = QuotaInfo(
                remaining_fraction=rem_fraction,
                reset_in_seconds=reset_sec,
                reset_time=reset_time,
            )

        return result
