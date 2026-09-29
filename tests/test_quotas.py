"""
Unit tests for Antigravity rate limit quota parsing.
"""

from alvarez.telemetry.quotas import QuotaTelemetry


def test_parse_quotas_valid():
    raw_payload = {
        "gemini-5h": {
            "remaining_fraction": 0.42,
            "reset_in_seconds": 7200,
        },
        "gemini-weekly": {
            "remaining_fraction": 0.88,
            "reset_in_seconds": 86400,
        },
    }

    quotas = QuotaTelemetry.parse_quotas(raw_payload)
    assert "gemini-5h" in quotas
    assert "gemini-weekly" in quotas

    assert quotas["gemini-5h"].percentage == 42.0
    assert quotas["gemini-5h"].reset_in_seconds == 7200

    assert quotas["gemini-weekly"].percentage == 88.0


def test_parse_quotas_empty_or_none():
    assert QuotaTelemetry.parse_quotas(None) == {}
    assert QuotaTelemetry.parse_quotas({}) == {}
    assert QuotaTelemetry.parse_quotas({"invalid_structure": "not a dict"}) == {}
