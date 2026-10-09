"""Open-window detection cadence and Oct 1 negative-velocity policy."""

from __future__ import annotations

from unittest.mock import patch

from app.engines.live_paper_parity import oct_paper_elite_rip_context
from app.engines.session_timing import (
    effective_building_ltp_monitor_min_ms,
    effective_ws_overlay_interval_ms,
)
from app.engines.trade_ranking import rank_trade_evidence
from tests.mock_defaults import settings_mock


def test_ws_overlay_interval_aggressive_open_window_under_one_second():
    s = settings_mock(
        latency_mode="aggressive",
        ws_snapshot_cache_interval_ms=400,
        explosion_open_scan_interval_ms=400,
        tick_snapshot_interval_ms=50,
        sse_heartbeat_seconds=0.5,
    )
    with patch("app.engines.session_timing.get_settings", return_value=s), patch(
        "app.engines.session_timing.in_open_premium_window", return_value=True,
    ), patch("app.engines.session_timing.get_market_phase", return_value="LIVE_MARKET"):
        ms = effective_ws_overlay_interval_ms()
    assert ms <= 400


def test_building_ltp_tighter_in_open_window():
    s = settings_mock(building_ltp_monitor_min_ms=75.0)
    with patch("app.engines.session_timing.get_settings", return_value=s), patch(
        "app.engines.session_timing.in_open_premium_window", return_value=True,
    ):
        assert effective_building_ltp_monitor_min_ms() == 40.0


@patch("app.config.get_settings")
def test_oct_paper_elite_negative_v_at_open_launch_not_rejected(mock_settings):
    mock_settings.return_value = settings_mock(
        october_frozen_profile_enabled=True,
        enable_live_trading=True,
        aggressive_min_explosion_score=45.0,
    )
    evidence = {
        "tier": "ELITE",
        "explosionScore": 100.0,
        "velocity3s": -0.5,
        "velocity9s": 2.0,
        "ictArmedBaseLaunch": True,
        "armedBaseLaunch": True,
        "localBaseMovePct": 12.0,
        "mode": "explosion",
        "tqs": 55.0,
        "chartConfidence": 50.0,
    }
    ranking = rank_trade_evidence(evidence)
    assert ranking["grade"] != "REJECT"


@patch("app.config.get_settings")
def test_oct_paper_negative_v_late_chase_outside_open_rejects(mock_settings):
    mock_settings.return_value = settings_mock(
        october_frozen_profile_enabled=True,
        enable_live_trading=True,
        aggressive_min_explosion_score=45.0,
    )
    evidence = {
        "tier": "ELITE",
        "explosionScore": 100.0,
        "velocity3s": -1.2,
        "velocity9s": -0.5,
        "ictVRipReady": True,
        "localBaseMovePct": 42.0,
        "sessionRangePosition": 0.72,
        "mode": "explosion",
        "tqs": 55.0,
        "chartConfidence": 50.0,
    }
    with patch("app.engines.session_timing.in_open_premium_window", return_value=False):
        assert oct_paper_elite_rip_context(evidence, settings=mock_settings.return_value) is False
        ranking = rank_trade_evidence(evidence)
    assert ranking["grade"] == "REJECT"
