"""Afternoon premium capture — 1pm consolidation breakouts (NIFTY 24250 PE style)."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.explosion_detector import ExplosionEvent, event_to_dict
from app.engines.explosion_profit import check_explosion_entry
from app.engines.morning_premium_capture import (
    afternoon_capture_active,
    afternoon_capture_exit_params,
    afternoon_capture_skips_chart_block,
    dominant_single_side_surge,
    in_afternoon_premium_capture_window,
    is_afternoon_capture_event,
    is_premium_capture_event,
    premium_capture_active,
)
from app.models.schemas import Breadth, Side, SpotChart, SymbolSnapshot, SuggestedTrade, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = MagicMock()
    s.morning_premium_capture_enabled = True
    s.morning_capture_start_hour = 9
    s.morning_capture_start_minute = 15
    s.morning_capture_end_hour = 11
    s.morning_capture_end_minute = 45
    s.morning_capture_min_rank_score = 48.0
    s.morning_capture_building_min_score = 38.0
    s.morning_capture_min_velocity_3s = 2.0
    s.morning_capture_min_velocity_9s = 2.8
    s.morning_capture_building_min_velocity_3s = 2.0
    s.morning_capture_min_vol_surge = 1.3
    s.morning_capture_skip_chart_on_extreme_velocity = True
    s.morning_capture_extreme_velocity_3s = 3.0
    s.morning_capture_extreme_velocity_9s = 4.0
    s.afternoon_premium_capture_enabled = True
    s.afternoon_capture_min_rank_score = 46.0
    s.afternoon_capture_building_min_score = 35.0
    s.afternoon_capture_min_velocity_3s = 1.2
    s.afternoon_capture_min_velocity_9s = 1.8
    s.afternoon_capture_building_min_velocity_3s = 1.0
    s.afternoon_capture_min_vol_surge = 1.4
    s.afternoon_capture_consolidation_vol_surge = 1.5
    s.afternoon_capture_consolidation_velocity_9s = 1.2
    s.afternoon_capture_skip_chart_on_volume = True
    s.afternoon_capture_chart_bypass_vol_surge = 1.5
    s.afternoon_capture_chart_bypass_velocity_9s = 1.2
    s.afternoon_capture_bearish_min_score = 42.0
    s.afternoon_capture_dominant_velocity_min = 1.6
    s.afternoon_capture_dominant_velocity_ratio = 1.4
    s.afternoon_capture_exit_target_points = 18.0
    s.afternoon_capture_exit_stop_points = 4.0
    s.afternoon_capture_exit_trail_arm_points = 6.0
    s.afternoon_capture_exit_max_hold_seconds = 480
    s.afternoon_capture_exit_trail_keep_ratio = 0.55
    s.explosion_target_elite = 25.0
    s.premium_led_counter_breadth_enabled = True
    s.premium_led_min_velocity_3s = 2.8
    s.premium_led_min_velocity_9s = 3.5
    s.premium_led_min_explosion_score = 42.0
    s.whipsaw_single_side_surge_bypass_enabled = True
    s.whipsaw_dominant_velocity_min = 2.5
    s.whipsaw_dominant_velocity_ratio = 1.6
    s.aggressive_min_explosion_score = 45
    s.explosion_breadth_alignment_enabled = True
    s.explosion_no_progress_enabled = True
    s.explosion_no_progress_skip_when_aligned = True
    s.explosion_no_progress_aligned_seconds = 300
    s.explosion_no_progress_seconds = 120
    s.momentum_rally_start_hour = 10
    s.momentum_rally_start_minute = 0
    s.momentum_rally_end_hour = 15
    s.momentum_rally_end_minute = 25
    s.all_day_explosion_capture_enabled = False
    s.all_day_explosion_session_move_min_pct = 40.0
    s.all_day_explosion_min_score = 38.0
    return s


def _nifty_24250_pe_event(**kwargs) -> ExplosionEvent:
    defaults = dict(
        symbol="NIFTY",
        side=Side.PUT,
        strike=24250.0,
        premium=54.25,
        velocity_3s=1.1,
        velocity_9s=1.35,
        velocity_15s=2.0,
        volume_surge=1.62,
        explosion_score=40.5,
        tier="BUILDING",
        reason="consolidation breakout vol×1.6",
    )
    defaults.update(kwargs)
    return ExplosionEvent(**defaults)


@patch("app.engines.morning_premium_capture.get_market_phase", return_value="LIVE_MARKET")
@patch("app.engines.chop_day_guards._minutes_now", return_value=13 * 60)
@patch("app.engines.chop_day_guards.get_market_phase", return_value="LIVE_MARKET")
@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
def test_afternoon_window_active_at_1pm(mock_settings, mock_phase2, mock_mins, mock_phase):
    with patch(
        "app.engines.morning_premium_capture.in_morning_premium_capture_window",
        return_value=False,
    ):
        assert in_afternoon_premium_capture_window() is True


@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
@patch("app.engines.morning_premium_capture.in_afternoon_premium_capture_window", return_value=True)
def test_consolidation_breakout_qualifies_low_velocity(mock_window, mock_settings):
    chart = SpotChart(direction="BULLISH", momentum5Pct=0.02, macdBias="BULLISH", rsi=52)
    event = _nifty_24250_pe_event()
    assert is_afternoon_capture_event(event, chart=chart) is True
    assert is_premium_capture_event(event, chart=chart) is True


@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
@patch("app.engines.morning_premium_capture.in_afternoon_premium_capture_window", return_value=True)
def test_volume_bypasses_bullish_chart_for_put(mock_window, mock_settings):
    chart = SpotChart(direction="BULLISH", momentum5Pct=0.04, macdBias="BULLISH", rsi=55)
    event = _nifty_24250_pe_event()
    assert afternoon_capture_skips_chart_block(event, chart) is True


@patch("app.engines.morning_premium_capture.in_all_day_explosion_window", return_value=False)
@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
@patch("app.engines.morning_premium_capture.in_afternoon_premium_capture_window", return_value=True)
def test_event_to_dict_marks_afternoon_tradeable(mock_window, mock_settings, mock_all_day):
    d = event_to_dict(_nifty_24250_pe_event())
    assert d["tradeable"] is True
    assert d["afternoonCapture"] is True
    assert d["premiumCapture"] is True


@pytest.mark.xfail(
    reason=(
        "Live-confirm gate (0912598 'Block wrong-timing explosions: require live "
        "velocity + ICT structure') now blocks this genuine low-velocity afternoon "
        "consolidation breakout (v3=1.1, v9=1.35) even with ICT structure. Slow "
        "afternoon premium captures are gated out — pending product decision on "
        "whether check_explosion_entry should exempt afternoon/premium-capture events."
    ),
    strict=True,
)
@patch("app.engines.morning_premium_capture.in_all_day_explosion_window", return_value=False)
@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
@patch("app.engines.morning_premium_capture.in_afternoon_premium_capture_window", return_value=True)
def test_explosion_entry_allows_building_afternoon(mock_window, mock_morn, mock_exp_settings, mock_all_day):
    mock_exp_settings.return_value = _settings()
    event = _nifty_24250_pe_event()
    trade = SuggestedTrade(
        id="x",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24250,
        lastPremium=54.25,
        tqs=42,
        strategyType=StrategyType.EXPLOSIVE,
        confidence=40.5,
    )
    chart = SpotChart(direction="BULLISH", momentum5Pct=0.02, macdBias="BULLISH")
    ok, reason = check_explosion_entry(
        event, trade, Breadth(bias="BEARISH", score=50, aligned=False), False, chart=chart,
    )
    assert ok, reason


@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
@patch("app.engines.morning_premium_capture.in_afternoon_premium_capture_window", return_value=True)
def test_afternoon_capture_active_from_snapshots(mock_window, mock_settings):
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase="LIVE_MARKET",
        dataAvailable=True,
        explosionAlerts=[
            {
                "symbol": "NIFTY",
                "side": "PUT",
                "strike": 24250,
                "premium": 54.25,
                "velocity3s": 1.1,
                "velocity9s": 1.35,
                "velocity15s": 2.0,
                "volumeSurge": 1.62,
                "explosionScore": 40.5,
                "tier": "BUILDING",
            }
        ],
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.02, macdBias="BULLISH"),
    )
    assert afternoon_capture_active({"NIFTY": snap}) is True
    assert premium_capture_active({"NIFTY": snap}) is True


@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
@patch("app.engines.morning_premium_capture.in_afternoon_premium_capture_window", return_value=True)
def test_dominant_put_surge_lower_threshold_in_afternoon(mock_window, mock_settings):
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase="LIVE_MARKET",
        dataAvailable=True,
        explosiveRunnerWatchlist=[
            {"side": "PUT", "premiumVelocityPct": 1.8, "score": 55},
            {"side": "CALL", "premiumVelocityPct": 0.9, "score": 40},
        ],
    )
    assert dominant_single_side_surge(snap) is True


@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
def test_afternoon_exit_params_wider_target(mock_settings):
    params = afternoon_capture_exit_params("BUILDING")
    assert params.target_points == 18.0
    assert params.stop_points == 4.0
    assert params.trail_arm_points == 6.0
