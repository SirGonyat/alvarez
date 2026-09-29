"""
Unit tests for data models and QuotaInfo logic.
"""

from alvarez.core.models import QuotaInfo, HardwareStats, StreamState


def test_quota_info_properties():
    q = QuotaInfo(remaining_fraction=0.85, reset_in_seconds=3600)
    assert q.percentage == 85.0
    assert q.is_refreshed is False

    refreshed_q = QuotaInfo(remaining_fraction=1.0, reset_in_seconds=0)
    assert refreshed_q.is_refreshed is True


def test_hardware_stats_defaults():
    hw = HardwareStats()
    assert hw.cpu_pct == 0
    assert hw.thermal_headroom == 55.0
    assert hw.pcie_link == "Gen4 x16"


def test_stream_state():
    state = StreamState(status="playing", title="Synth Track", pid=1234)
    assert state.status == "playing"
    assert state.pid == 1234


def test_agent_context_normalization():
    from alvarez.core.models import AgentContext
    from alvarez.ui.widgets import UIWidgets

    # Test with dictionary model object as passed by Antigravity CLI stdin
    dict_model = {
        "id": "Gemini 3.8 Flash (Medium)",
        "display_name": "Gemini 3.8 Flash (Medium)",
        "effort": "medium"
    }
    ctx = AgentContext(model_name=dict_model)
    assert ctx.model_name == "Gemini 3.8 Flash (Medium)"
    assert ctx.effort == "medium"

    badge = UIWidgets.render_model_badge(ctx)
    assert "✦ [Gemini 3.8 Flash (Medium)]" in badge
    assert "Medium" in badge
