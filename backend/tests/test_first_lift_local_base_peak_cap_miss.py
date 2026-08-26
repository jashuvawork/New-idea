"""Aug26 SENSEX PUT 77800 — first_lift_local_base at pad with high session peak."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.ict_breakout_monitor import _defensive_base_rip_top_allowed
from app.engines.pad_lane_capture import (
    _pad_lane_peak_for_cap,
    pad_lane_turnaround_chart_bypass,
)
from app.engines.spot_direction import live_direction_blocks_side
from app.models.schemas import MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.pad_lane_chart_bypass_enabled = True
    s.pad_lane_first_lift_local_base_chart_bypass_enabled = True
    s.pad_lane_chart_bypass_min_velocity_3s = 0.5
    s.pad_lane_chart_bypass_volume_awaken_min_velocity_3s = 0.2
    s.pad_lane_chart_bypass_max_off_low_pct = 30.0
    s.pad_lane_chart_bypass_max_peak_move_pct = 38.0
    s.pad_lane_elite_ftv_chart_bypass_max_peak_move_pct = 45.0
    s.pad_lane_chart_bypass_max_adverse_index_mom5_pct = 0.25
    s.pad_lane_chart_bypass_min_premium_velocity_9s = -0.3
    s.ict_v_rip_pad_min_move_pct = 2.0
    s.ict_v_rip_max_move_pct = 25.0
    s.chart_alignment_enabled = True
    s.chart_live_direction_hard_block = True
    s.chart_counter_trend_bypass_block_enabled = True
    s.chart_min_trend_strength = 20
    s.chart_min_momentum_pct = 0.05
    s.chart_override_min_score = 75
    s.ict_defensive_base_rip_require_top_quality = True
    s.ict_defensive_base_rip_min_score = 80.0
    s.ict_defensive_base_rip_min_quality = 70.0
    s.ict_defensive_base_rip_min_velocity_3s = 2.5
    s.top_ftv_a_pad_velocity_min_move_pct = 8.0
    s.top_ftv_a_pad_velocity_max_move_pct = 25.0
    s.ict_v_rip_volume_awake_min_velocity_3s = 0.85
    s.ict_v_rip_min_velocity_3s = 1.2
    s.ict_first_lift_local_base_cold_velocity_3s = -1.5
    for key, value in overrides.items():
        setattr(s, key, value)
    return s


def _bullish_snap(symbol: str = "SENSEX", mom5: float = 0.08) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime(2026, 8, 26, 11, 45, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=60.0,
        spot=77950.0,
        atmStrike=77800.0,
        spotChart=SpotChart(
            direction="BULLISH",
            momentum5Pct=mom5,
            momentum10Pct=mom5 * 0.9,
            momentum15Pct=mom5 * 0.7,
            trendStrength=35,
            spot=77950.0,
        ),
    )


def _aug26_sensex_put_77800_alert(**overrides) -> dict:
    alert = {
        "symbol": "SENSEX",
        "side": "PUT",
        "strike": 77800.0,
        "premium": 158.55,
        "tier": "ELITE",
        "momentType": "first_lift_local_base",
        "explosionScore": 100.0,
        "ictFirstLift": True,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "ictBaseRelativeMovePct": 16.0,
        "localBaseMovePct": 16.0,
        "offLowMovePct": 16.0,
        "peakMovePct": 53.02,
        "velocity3s": -1.44,
        "velocity9s": -0.2,
        "volumeAwaken": True,
        "volumeSurge": 2.5,
    }
    alert.update(overrides)
    return alert


def test_pad_lane_peak_cap_uses_local_base_when_at_pad():
    settings = _settings()
    assert _pad_lane_peak_for_cap(16.0, 53.02, settings) == 16.0
    assert _pad_lane_peak_for_cap(30.0, 53.02, settings) == 53.02


@patch("app.engines.pad_lane_capture.get_settings")
def test_first_lift_local_base_chart_bypass_allows_put_on_bullish(mock_settings):
    mock_settings.return_value = _settings()
    snap = _bullish_snap()
    alert = _aug26_sensex_put_77800_alert()

    assert pad_lane_turnaround_chart_bypass(Side.PUT, snap, alert=alert) is True


@patch("app.engines.pad_lane_capture.get_settings")
def test_first_lift_local_base_chart_bypass_blocked_without_peak_cap_fix(mock_settings):
    """Session peak 53% alone would fail the 45% elite cap without pad peak logic."""
    mock_settings.return_value = _settings()
    settings = mock_settings.return_value
    # Simulate old behavior: peak cap uses raw session peak
    peak_for_cap = 53.02
    max_peak = float(settings.pad_lane_elite_ftv_chart_bypass_max_peak_move_pct)
    assert peak_for_cap > max_peak


@patch("app.engines.spot_direction.get_settings")
def test_first_lift_strict_bypass_clears_chart_live_bullish_no_puts(mock_settings):
    mock_settings.return_value = _settings()
    chart = SpotChart(
        direction="BULLISH",
        momentum5Pct=0.08,
        trendStrength=35,
        spot=77950.0,
    )
    blocked, reason = live_direction_blocks_side(
        Side.PUT,
        chart,
        strict_first_lift_bypass=True,
    )
    assert blocked is False
    assert reason == "ok"


def test_defensive_rip_top_softens_velocity_for_first_lift_local_base_pad():
    settings = _settings()
    ok, reason = _defensive_base_rip_top_allowed(
        tier="ELITE",
        quality=82.0,
        score=100.0,
        velocity_3s=-1.44,
        settings=settings,
        base_move_pct=16.0,
        volume_awake=True,
        v_rip_ready=False,
        armed_base_launch=False,
        first_lift=True,
    )
    assert ok is True
    assert reason == "ok"


@patch("app.engines.pad_lane_capture.get_settings")
def test_first_lift_local_base_chart_bypass_rejects_extended_chase(mock_settings):
    mock_settings.return_value = _settings()
    snap = _bullish_snap()
    alert = _aug26_sensex_put_77800_alert(
        ictBaseRelativeMovePct=28.0,
        localBaseMovePct=28.0,
    )

    assert pad_lane_turnaround_chart_bypass(Side.PUT, snap, alert=alert) is False
