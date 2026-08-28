"""Afternoon premium capture — 1pm consolidation breakouts (NIFTY 24250 PE style)."""

from datetime import datetime, timedelta
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
    s.afternoon_capture_peak_halve_lock_enabled = True
    s.afternoon_capture_peak_halve_min_best_points = 10.0
    s.afternoon_capture_peak_halve_giveback_ratio = 0.50
    s.afternoon_capture_peak_halve_min_remain_points = 1.0
    s.afternoon_capture_peak_halve_min_hold_seconds = 120
    s.afternoon_capture_peak_halve_skip_stage_ladder_min_projected_tp = 80.0
    s.afternoon_capture_skip_exit_tighten_on_stage_ladder = True
    s.explosion_stage_trail_min_hold_seconds = 90.0
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
    s.runner_min_best_points = 25.0
    s.runner_trail_keep_ratio = 0.55
    s.explosion_failed_launch_exit_enabled = False
    s.explosion_never_green_stop_enabled = False
    s.explosion_peak_fade_lock_enabled = False
    s.explosion_early_green_lock_enabled = False
    s.emergency_stop_enabled = False
    s.explosion_stop_min_hold_seconds = 0
    s.explosion_per_trade_max_loss_inr = 0
    s.elite_full_lot_risk_inr = 0
    s.adaptive_exits_enabled = True
    s.moment_stage_trail_enabled = True
    s.explosion_trail_pre_stage_suppress_step = True
    s.ftv_runner_pct_trail_enabled = True
    s.ftv_runner_pct_trail_arm_pct = 25.0
    s.ftv_runner_pct_trail_keep_ratio = 0.75
    s.ftv_runner_pct_trail_min_best_points = 6.0
    s.explosion_trail_arm_points = 4.0
    s.explosion_trail_keep_ratio = 0.61
    s.explosion_initial_stop_points = 8.0
    s.explosion_target_standard = 18.0
    s.explosion_trail_step_points = 2.0
    s.explosion_trail_tight_arm = 12.0
    s.explosion_trail_tight_points = 5.0
    s.explosion_micro_target_points = 3.0
    s.explosion_stop_pct_of_premium = 0.10
    s.scalp_stop_min_points = 3.0
    s.runner_micro_giveback_points = 4.0
    s.high_conviction_defer_profit_lock = True
    s.high_conviction_trail_keep_ratio = 0.30
    s.chart_confidence_defer_tp_min = 90.0
    s.ict_max_profit_skip_hard_target = True
    s.moment_stage_giveback_ratio = 0.50
    s.moment_stage_late_giveback_ratio = 1.0
    s.moment_stage_late_progress = 0.70
    s.moment_stage_min_remain_points = 1.0
    s.moment_stage_hot_hold_velocity_3s = 2.5
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


@patch("app.engines.morning_premium_capture.in_all_day_explosion_window", return_value=False)
@patch("app.engines.morning_premium_capture.in_afternoon_premium_capture_window", return_value=True)
def test_explosion_entry_allows_building_afternoon(mock_window, mock_all_day):
    # Use real Settings — MagicMock invents unusable numeric attrs once move > 0.
    # Hard entry window is 28–65% unstructured — fixture must print a real move.
    event = _nifty_24250_pe_event(daily_move_pct=35.0, peak_move_pct=35.0)
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


@patch("app.engines.explosion_profit.get_settings", return_value=_settings())
def test_afternoon_capture_peak_halve_lock_books_half_peak(mock_settings):
    from app.engines.explosion_profit import (
        afternoon_capture_peak_halve_lock_reason,
        evaluate_explosion_exit,
    )
    from app.models.schemas import PaperTrade, Side, StrategyType

    from datetime import datetime
    from zoneinfo import ZoneInfo

    trade = PaperTrade(
        id="t1",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24250.0,
        entryPremium=100.5,
        currentPremium=109.5,
        lots=3,
        pnlPoints=9.0,
        pnlInr=1755.0,
        bestPnlPoints=19.92,
        maxLtp=121.85,
        openedAt=datetime.now(ZoneInfo("Asia/Kolkata")) - timedelta(minutes=3),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={"afternoonCapture": True, "explosionTier": "EXPLODING"},
    )
    assert afternoon_capture_peak_halve_lock_reason(
        trade, best=19.92, pnl_pts=9.0,
    ) == "afternoon_capture_peak_halve_lock"
    assert afternoon_capture_peak_halve_lock_reason(
        trade, best=19.92, pnl_pts=12.0,
    ) is None

    reason, _ = evaluate_explosion_exit(
        trade,
        109.5,
        "EXPLODING",
        65,
        live_velocity_3s=0.0,
    )
    assert reason == "afternoon_capture_peak_halve_lock"


@patch("app.engines.explosion_profit.get_settings", return_value=_settings())
def test_afternoon_halve_lock_skips_fresh_stage_ladder_runner(mock_settings):
    """Aug28 SENSEX 77300/77200 — no halve-lock in first 2m on projected 800+ runner."""
    from app.engines.explosion_profit import (
        afternoon_capture_peak_halve_lock_reason,
        evaluate_explosion_exit,
    )
    from app.models.schemas import PaperTrade, Side, StrategyType
    from app.engines.adaptive_exits import AdaptiveExitPlan
    from app.engines.explosion_profit import explosion_exit_params_from_plan

    opened = datetime.now(IST) - timedelta(seconds=16)
    trade = PaperTrade(
        id="sensex-77300",
        symbol="SENSEX",
        side=Side.PUT,
        strike=77300.0,
        entryPremium=387.53,
        lots=23,
        openedAt=opened,
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=12.07,
        maxLtp=399.6,
        entryContext={
            "afternoonCapture": True,
            "momentStageLadder": True,
            "projectedMaxTp": 811.18,
            "stageSize": 75.0,
            "exitPlan": {
                "momentStageLadder": True,
                "projectedMaxTp": 811.18,
                "stageSize": 75.0,
                "trailArmPoints": 16.43,
            },
        },
    )
    assert afternoon_capture_peak_halve_lock_reason(
        trade, best=12.07, pnl_pts=2.02, hold_seconds=16.0,
    ) is None

    plan = AdaptiveExitPlan(
        stopPoints=40.0,
        targetPoints=54.72,
        trailArmPoints=16.43,
        trailKeepRatio=0.61,
        microTargetPoints=3.32,
    )
    params = explosion_exit_params_from_plan(plan, "ELITE")
    reason, _ = evaluate_explosion_exit(
        trade, 389.55, "ELITE", 20, params=params, live_velocity_3s=4.5,
    )
    assert reason is None or reason not in (
        "afternoon_capture_peak_halve_lock",
        "explosion_stage_trail",
        "explosion_peak_keep_trail",
    )
