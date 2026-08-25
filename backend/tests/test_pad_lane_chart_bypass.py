"""Pad-lane turnaround chart bypass — premium-led V-rip through bearish chart."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.local_base_chart_bypass import local_base_overrides_session_chart
from app.engines.pad_lane_capture import (
    pad_lane_turnaround_chart_bypass,
    pad_lane_turnaround_chart_bypass_for_snap,
)
from app.engines.spot_direction import chart_blocks_side, live_direction_blocks_side
from app.models.schemas import MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.pad_lane_chart_bypass_enabled = True
    s.pad_lane_chart_bypass_min_velocity_3s = 0.5
    s.pad_lane_chart_bypass_volume_awaken_min_velocity_3s = 0.2
    s.pad_lane_chart_bypass_max_off_low_pct = 30.0
    s.pad_lane_chart_bypass_max_peak_move_pct = 38.0
    s.pad_lane_chart_bypass_max_adverse_index_mom5_pct = 0.25
    s.pad_lane_chart_bypass_min_premium_velocity_9s = -0.3
    s.chart_alignment_enabled = True
    s.chart_live_direction_hard_block = True
    s.chart_counter_trend_bypass_block_enabled = True
    s.chart_min_trend_strength = 20
    s.chart_min_momentum_pct = 0.05
    s.chart_override_min_score = 75
    for key, value in overrides.items():
        setattr(s, key, value)
    return s


def _snap(direction: str = "BEARISH", mom5: float = -0.12) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime(2026, 8, 25, 14, 35, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=60.0,
        spot=24150.0,
        atmStrike=24150.0,
        spotChart=SpotChart(
            direction=direction,
            momentum5Pct=mom5,
            momentum10Pct=mom5 * 0.8,
            momentum15Pct=mom5 * 0.5,
            trendStrength=35,
            spot=24150.0,
        ),
    )


def _v_rip_alert(**overrides) -> dict:
    alert = {
        "side": "CALL",
        "strike": 24150.0,
        "premium": 79.65,
        "tier": "EXPLODING",
        "ictVRipReady": True,
        "vRipReady": True,
        "ictBaseRelativeMovePct": 24.9,
        "offLowMovePct": 24.9,
        "peakMovePct": 24.9,
        "velocity3s": 1.8,
        "velocity9s": 1.1,
        "volumeAwaken": True,
        "explosionScore": 72.0,
        "ictBaseReadinessReason": "v_rip_session_low_ready",
    }
    alert.update(overrides)
    return alert


@patch("app.engines.pad_lane_capture.get_settings")
def test_pad_lane_chart_bypass_allows_call_on_bearish_v_rip(mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap(direction="BEARISH", mom5=-0.12)
    alert = _v_rip_alert()

    assert pad_lane_turnaround_chart_bypass(Side.CALL, snap, alert=alert) is True


@patch("app.engines.pad_lane_capture.get_settings")
def test_pad_lane_chart_bypass_rejects_hard_index_dump(mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap(direction="BEARISH", mom5=-0.35)
    alert = _v_rip_alert()

    assert pad_lane_turnaround_chart_bypass(Side.CALL, snap, alert=alert) is False


@patch("app.engines.pad_lane_capture.get_settings")
def test_pad_lane_chart_bypass_rejects_extended_chase(mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap(direction="BEARISH", mom5=-0.08)
    alert = _v_rip_alert(ictBaseRelativeMovePct=35.0, offLowMovePct=35.0)

    assert pad_lane_turnaround_chart_bypass(Side.CALL, snap, alert=alert) is False


@patch("app.engines.pad_lane_capture.get_settings")
def test_pad_lane_chart_bypass_rejects_low_velocity(mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap(direction="BEARISH", mom5=-0.08)
    alert = _v_rip_alert(velocity3s=0.1, volumeAwaken=False)

    assert pad_lane_turnaround_chart_bypass(Side.CALL, snap, alert=alert) is False


@patch("app.engines.pad_lane_capture.get_settings")
def test_pad_lane_chart_bypass_volume_awaken_relaxes_velocity(mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap(direction="BEARISH", mom5=-0.08)
    alert = _v_rip_alert(velocity3s=0.35, volumeAwaken=True)

    assert pad_lane_turnaround_chart_bypass(Side.CALL, snap, alert=alert) is True


@patch("app.engines.pad_lane_capture.get_settings")
def test_pad_lane_chart_bypass_for_snap_scans_alerts(mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap(direction="BEARISH", mom5=-0.10)
    snap.explosionAlerts = [_v_rip_alert()]

    assert pad_lane_turnaround_chart_bypass_for_snap(Side.CALL, snap) is True


@patch("app.engines.local_base_chart_bypass.get_settings")
@patch("app.engines.pad_lane_capture.get_settings")
def test_local_base_overrides_session_chart_uses_pad_lane(
    mock_pad_settings, mock_local_settings,
):
    mock_pad_settings.return_value = _settings()
    mock_local_settings.return_value = MagicMock(
        local_base_overrides_session_chart_enabled=True,
        local_base_ichimoku_chart_bypass_enabled=True,
        local_base_chart_bypass_require_ichimoku=False,
        local_base_require_aligned_live_momentum=True,
        local_base_aligned_momentum_max_adverse_pct=0.05,
        local_base_ichimoku_max_adverse_mom5_pct=0.12,
        local_base_turn_bypass_enabled=True,
        local_base_turn_min_score=62.0,
        local_base_turn_min_vol_surge=2.0,
        local_base_turn_min_mom_shift_pct=0.05,
        local_base_turn_max_adverse_mom5_pct=0.12,
        explosion_local_base_entry_min_move_pct=15.0,
        explosion_local_base_chase_max_move_pct=40.0,
        local_base_adaptive_window_enabled=True,
        local_base_wide_window_min_vol_surge=3.0,
        local_base_elite_chase_max_move_pct=50.0,
        local_base_exploding_entry_min_move_pct=20.0,
        local_base_chart_bypass_min_score=38.0,
        local_base_chart_bypass_radar_min_move_pct=28.0,
    )
    snap = _snap(direction="BEARISH", mom5=-0.12)
    alert = _v_rip_alert()

    assert local_base_overrides_session_chart(Side.CALL, snap, alert=alert) is True


@patch("app.engines.spot_direction.get_settings")
def test_chart_live_bearish_passes_with_pad_lane_strict_bypass(mock_settings):
    mock_settings.return_value = _settings()
    chart = SpotChart(
        direction="BEARISH",
        momentum5Pct=-0.12,
        trendStrength=35,
        spot=24150.0,
    )

    blocked, reason = live_direction_blocks_side(
        Side.CALL,
        chart,
        strict_first_lift_bypass=True,
    )
    assert blocked is False
    assert reason == "ok"

    blocked, reason = chart_blocks_side(
        Side.CALL,
        chart,
        strict_first_lift_bypass=True,
        premium_led_bypass=True,
    )
    assert blocked is False
    assert reason == "ok"


@patch("app.engines.spot_direction.get_settings")
def test_chart_live_bearish_blocks_without_pad_lane_bypass(mock_settings):
    mock_settings.return_value = _settings()
    chart = SpotChart(
        direction="BEARISH",
        momentum5Pct=-0.12,
        trendStrength=35,
        spot=24150.0,
    )

    blocked, reason = live_direction_blocks_side(Side.CALL, chart)
    assert blocked is True
    assert reason == "chart_live_bearish_no_calls"


@pytest.mark.parametrize(
    "readiness_reason",
    [
        "slow_grind_sudden_lift_ready",
        "slow_grind_armed_trough_ready",
        "slow_grind_consolidation_base_ready",
        "fast_bullish_local_base_ready",
        "building_local_base_lift_ready",
    ],
)
@patch("app.engines.pad_lane_capture.get_settings")
def test_pad_lane_chart_bypass_accepts_pad_lane_reasons(
    mock_settings, readiness_reason,
):
    mock_settings.return_value = _settings()
    snap = _snap(direction="BEARISH", mom5=-0.08)
    alert = _v_rip_alert(
        ictVRipReady=False,
        vRipReady=False,
        ictBaseReadinessReason=readiness_reason,
    )

    assert (
        pad_lane_turnaround_chart_bypass(
            Side.CALL,
            snap,
            alert=alert,
            readiness_reason=readiness_reason,
        )
        is True
    )
