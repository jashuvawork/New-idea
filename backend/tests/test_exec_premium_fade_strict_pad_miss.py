"""Aug26 SENSEX PUT 77600 — live chart monitor must allow pad-lane premium retest fills."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.execution_chart_monitor import validate_execution_charts
from app.engines.pad_lane_capture import resolve_strict_pad_lane_for_entry
from app.engines.spot_direction import premium_blocks_entry
from app.engines.winner_entry_guards import premium_fading_blocks_entry
from app.models.schemas import MarketPhase, PremiumChart, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.execution_chart_premium_check_enabled = True
    s.execution_chart_min_premium_momentum_pct = 0.0
    s.pad_lane_premium_fade_fill_enabled = True
    s.pad_lane_premium_fade_fill_max_drawdown_pct = -1.2
    s.ftv_premium_fade_fill_enabled = True
    s.ftv_premium_fade_fill_max_drawdown_pct = -0.6
    s.all_day_explosion_extreme_move_min_pct = 999.0
    s.pad_lane_chart_bypass_enabled = True
    s.pad_lane_first_lift_local_base_chart_bypass_enabled = True
    s.pad_lane_armed_base_launch_chart_bypass_enabled = True
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
    s.chart_min_trend_strength = 20
    s.chart_min_momentum_pct = 0.05
    s.chart_override_min_score = 75
    s.execution_mtf_enabled = False
    for key, value in overrides.items():
        setattr(s, key, value)
    return s


def _aligned_bearish_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime(2026, 8, 26, 13, 27, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=50.0,
        spot=77700.0,
        atmStrike=77700.0,
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=-0.08,
            trendStrength=35,
            spot=77700.0,
        ),
    )


def _aug26_put_77600_alert(**overrides) -> dict:
    alert = {
        "symbol": "SENSEX",
        "side": "PUT",
        "strike": 77600.0,
        "premium": 98.0,
        "tier": "ELITE",
        "momentType": "armed_base_launch",
        "explosionScore": 100.0,
        "ictFirstLift": True,
        "ictArmedBaseLaunch": True,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "localBaseMovePct": 8.2,
        "ictBaseRelativeMovePct": 8.2,
        "offLowMovePct": 8.2,
        "peakMovePct": 34.9,
        "velocity3s": 0.2,
        "velocity9s": 0.1,
        "volumeAwaken": True,
        "ictBaseReadinessReason": "v_rip_session_low_ready",
    }
    alert.update(overrides)
    return alert


def _explosion_event(**overrides):
    base = SimpleNamespace(tier="ELITE", daily_move_pct=8.2, explosion_score=100.0)
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


@patch("app.engines.pad_lane_capture.get_settings")
@patch("app.engines.ict_breakout_monitor.get_settings")
def test_strict_pad_resolves_on_chart_aligned_put(mock_ict, mock_pad):
    settings = _settings()
    mock_pad.return_value = settings
    mock_ict.return_value = settings
    snap = _aligned_bearish_snap()
    alert = _aug26_put_77600_alert()
    event = _explosion_event()

    with patch(
        "app.engines.ict_breakout_monitor.first_lift_entry_readiness",
        return_value=(True, "v_rip_session_low_ready"),
    ):
        pad_lane, strict = resolve_strict_pad_lane_for_entry(
            Side.PUT,
            snap,
            mode="explosion",
            explosion_event=event,
            alert=alert,
        )

    assert pad_lane is False
    assert strict is True


@patch("app.engines.winner_entry_guards.get_settings")
def test_pad_lane_premium_fade_allows_base_retest_wider_than_ftv(mock_settings):
    mock_settings.return_value = _settings()
    event = _explosion_event()
    blocked, reason = premium_fading_blocks_entry(
        premium_momentum_3s=-0.8,
        premium_momentum_5s=-0.7,
        explosion_event=event,
        confirmed_ftv_bypass=True,
        pad_lane_bypass=True,
    )
    assert blocked is False
    assert reason == "pad_lane_shallow_fade_ok"


@patch("app.engines.spot_direction.get_settings")
@patch("app.engines.winner_entry_guards.get_settings")
def test_premium_blocks_entry_uses_strict_pad_on_aligned_chart(mock_guard, mock_spot):
    settings = _settings()
    mock_guard.return_value = settings
    mock_spot.return_value = settings
    premium = PremiumChart(
        direction="BEARISH",
        momentum3Pct=-0.8,
        momentum5Pct=-0.7,
        lastPremium=98.0,
    )
    blocked, reason = premium_blocks_entry(
        Side.PUT,
        premium,
        explosion_event=_explosion_event(),
        confirmed_ftv_bypass=True,
        pad_lane_bypass=True,
    )
    assert blocked is False
    assert reason == "pad_lane_shallow_fade_ok"


@patch("app.engines.execution_chart_monitor.get_settings")
@patch("app.engines.mtf_chart_analysis.get_settings")
@patch("app.engines.spot_direction.get_settings")
@patch("app.engines.winner_entry_guards.get_settings")
def test_validate_execution_charts_strict_pad_premium_fade(
    mock_guard, mock_spot, mock_mtf, mock_exec,
):
    settings = _settings()
    mock_guard.return_value = settings
    mock_spot.return_value = settings
    mock_mtf.return_value = settings
    mock_exec.return_value = settings
    index = SpotChart(direction="BEARISH", momentum5Pct=-0.08, trendStrength=35, spot=77700.0)
    premium = PremiumChart(
        direction="BEARISH",
        momentum3Pct=-0.8,
        momentum5Pct=-0.7,
        lastPremium=98.0,
    )
    passed, reason, _meta = validate_execution_charts(
        Side.PUT,
        index,
        premium_chart=premium,
        trade_score=100.0,
        first_lift_bypass=True,
        confirmed_ftv_bypass=True,
        pad_lane_bypass=True,
        explosion_event=_explosion_event(),
        mode="explosion",
    )
    assert passed is True
    assert reason == "ok"
