"""Peak + fast reversal → 75% peak-keep exit (Sep08 23800 PE gap)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.explosion_profit import (
    ExplosionExitParams,
    evaluate_explosion_exit,
    peak_velocity_reversal_keep_reason,
)
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.peak_velocity_reversal_keep_enabled = True
    s.peak_velocity_reversal_min_best_points = 8.0
    s.peak_velocity_reversal_keep_ratio = 0.75
    s.peak_velocity_reversal_min_velocity_3s = 2.0
    s.peak_velocity_reversal_min_giveback_points = 2.0
    s.peak_velocity_reversal_skip_hot_velocity_3s = 2.0
    s.explosion_peak_fade_lock_enabled = False
    s.explosion_peak_capture_enabled = False
    s.explosion_faded_rip_no_green_exit_enabled = False
    s.explosion_failed_launch_exit_enabled = False
    s.explosion_armed_base_expiry_exit_enabled = False
    s.explosion_barely_green_stop_enabled = False
    s.explosion_never_green_stop_enabled = False
    s.explosion_stop_min_hold_seconds = 0
    s.emergency_stop_enabled = False
    s.ict_max_profit_skip_hard_target = True
    s.ict_max_profit_target_points = 180.0
    s.ict_max_profit_trail_keep_ratio = 0.42
    s.high_conviction_trail_keep_ratio = 0.30
    s.high_conviction_defer_profit_lock = True
    s.runner_min_best_points = 25.0
    s.runner_trail_keep_ratio = 0.55
    s.runner_micro_giveback_points = 4.0
    s.explosion_trail_arm_points = 22.0
    s.explosion_trail_keep_ratio = 0.55
    s.explosion_trail_step_points = 2.0
    s.explosion_trail_tight_arm = 999.0
    s.explosion_trail_tight_points = 0.0
    s.explosion_trail_hot_defer_enabled = True
    s.explosion_trail_pre_stage_suppress_step = True
    s.explosion_target_standard = 18.0
    s.explosion_stage_trail_min_hold_seconds = 0
    s.explosion_elite_max_hold_seconds = 1800
    s.explosion_chop_elite_max_hold_seconds = 900
    s.ict_max_profit_max_hold_seconds = 1200
    s.afternoon_capture_exit_max_hold_seconds = 900
    s.explosion_thesis_hold_enabled = True
    s.explosion_thesis_hold_min_best_points = 2.0
    s.explosion_no_progress_enabled = False
    s.ftv_runner_pct_trail_enabled = True
    s.ftv_runner_pct_trail_arm_pct = 25.0
    s.ftv_runner_pct_trail_arm_min_best_points = 20.0
    s.ftv_runner_pct_trail_keep_ratio = 0.75
    s.ftv_runner_pct_trail_min_best_points = 6.0
    s.moment_stage_trail_enabled = True
    s.moment_stage_giveback_ratio = 0.50
    s.moment_stage_late_giveback_ratio = 1.0
    s.moment_stage_hot_hold_velocity_3s = 2.5
    s.moment_stage_min_remain_points = 1.0
    s.moment_stage_near_complete_frac = 0.82
    s.modest_peak_mode_enabled = True
    s.peak_velocity_reversal_defer_elite_runner_enabled = True
    s.peak_velocity_reversal_defer_elite_runner_min_gain_pct = 8.0
    s.peak_velocity_reversal_defer_elite_runner_min_rank_score = 85.0
    s.peak_velocity_reversal_defer_elite_runner_max_progress_frac = 0.05
    s.peak_velocity_reversal_require_rollover_confirm = True
    s.explosion_peak_capture_max_live_velocity_3s = 1.0
    s.explosion_peak_capture_max_premium_mom_pct = 0.15
    s.explosion_peak_fade_defer_when_bullish = True
    s.explosion_peak_fade_bullish_min_remain_points = 3.0
    s.explosion_peak_fade_bullish_min_velocity_3s = 1.5
    s.eod_learning_apply_enabled = False
    s.chart_confidence_defer_tp_min = 60.6
    s.explosion_adaptive_stop_min_hold_seconds = 0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _sep08_deep_itm_trade(*, pnl_pts: float, best: float = 16.0) -> PaperTrade:
    entry = 150.80
    now = datetime.now(tz=IST)
    return PaperTrade(
        id="69a50ca8",
        symbol="NIFTY",
        side=Side.PUT,
        strike=23800.0,
        entryPremium=entry,
        currentPremium=entry + pnl_pts,
        lots=18,
        pnlInr=0,
        openedAt=now - timedelta(minutes=40),
        status="OPEN",
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=best,
        maxLtp=entry + best,
        entryContext={
            "maxProfitCapture": True,
            "eliteHot": True,
            "topExplosionMaxLots": True,
            "eliteFullLot": True,
            "ictArmedBaseLaunch": True,
            "explosionTier": "ELITE",
            "projectedMaxTp": 200.0,
            "stageSize": 50.0,
            "momentStageLadder": True,
            "exitPlan": {
                "stopPoints": 27.0,
                "targetPoints": 60.0,
                "trailArmPoints": 19.0,
                "trailKeepRatio": 0.54,
            },
            "executionChart": {
                "premiumChart": {"momentum3Pct": 0.0, "momentum5Pct": 0.0},
            },
        },
    )


@patch("app.engines.explosion_profit.get_settings")
def test_reversal_keep_reason_fires_sep08_scenario(mock_settings):
    s = _settings()
    mock_settings.return_value = s
    trade = _sep08_deep_itm_trade(pnl_pts=11.0)
    reason = peak_velocity_reversal_keep_reason(
        trade, best=16.0, pnl_pts=11.0, live_velocity_3s=-3.5,
    )
    assert reason == "explosion_peak_velocity_reversal_keep"


@patch("app.engines.explosion_profit.get_settings")
def test_reversal_keep_holds_above_75pct_floor(mock_settings):
    s = _settings()
    mock_settings.return_value = s
    trade = _sep08_deep_itm_trade(pnl_pts=13.0)
    reason = peak_velocity_reversal_keep_reason(
        trade, best=16.0, pnl_pts=13.0, live_velocity_3s=-3.5,
    )
    assert reason is None


@patch("app.engines.explosion_profit.get_settings")
def test_reversal_keep_requires_negative_velocity(mock_settings):
    s = _settings()
    mock_settings.return_value = s
    trade = _sep08_deep_itm_trade(pnl_pts=13.0)
    reason = peak_velocity_reversal_keep_reason(
        trade, best=16.0, pnl_pts=13.0, live_velocity_3s=-0.5,
    )
    assert reason is None


def _sep09_elite_runner_trade(*, pnl_pts: float, best: float = 9.35) -> PaperTrade:
    """Sep09 SENSEX 75100 PE — Grade-A armed-base runner, early +9pt peak."""
    entry = 230.65
    now = datetime.now(tz=IST)
    return PaperTrade(
        id="df2f763d",
        symbol="SENSEX",
        side=Side.PUT,
        strike=75100.0,
        entryPremium=entry,
        currentPremium=entry + pnl_pts,
        lots=39,
        pnlInr=0,
        openedAt=now - timedelta(minutes=12),
        status="OPEN",
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=best,
        maxLtp=entry + best,
        entryContext={
            "maxProfitCapture": True,
            "eliteRunnerExitBundle": True,
            "vBaseFtvRunner": True,
            "ictArmedBaseLaunch": True,
            "ictFlatThenVertical": True,
            "momentStageLadder": True,
            "rankScore": 92.8,
            "rankGrade": "A",
            "projectedMaxTp": 800.0,
            "stageSize": 75.0,
            "eliteAssessment": {"eliteScore": 93.4, "grade": "A", "setup": "V"},
            "chartExitLive": {"letRun": True},
            "exitPlan": {
                "stopPoints": 40.0,
                "trailArmPoints": 20.32,
                "trailKeepRatio": 0.514,
                "projectedMaxTp": 800.0,
                "momentStageLadder": True,
            },
        },
    )


@patch("app.engines.explosion_profit.get_settings")
def test_reversal_keep_defers_sep09_elite_runner_early_peak(mock_settings):
    """+9pt (+4%) on Grade-A runner — velocity pullback is noise, not structural peak."""
    s = _settings()
    mock_settings.return_value = s
    trade = _sep09_elite_runner_trade(pnl_pts=4.26)
    reason = peak_velocity_reversal_keep_reason(
        trade, best=9.35, pnl_pts=4.26, live_velocity_3s=-3.0,
    )
    assert reason is None


@patch("app.engines.explosion_profit.get_settings")
def test_reversal_keep_still_fires_sep08_after_runner_matures(mock_settings):
    """Sep08 +16pt (+10.6%) deep ITM — slow-bleed keep still books when leg has matured."""
    s = _settings()
    mock_settings.return_value = s
    trade = _sep08_deep_itm_trade(pnl_pts=11.0)
    trade.entryContext["eliteRunnerExitBundle"] = True
    trade.entryContext["vBaseFtvRunner"] = True
    trade.entryContext["rankScore"] = 95.0
    trade.entryContext["rankGrade"] = "A"
    trade.entryContext["projectedMaxTp"] = 200.0
    trade.entryContext["momentStageLadder"] = True
    reason = peak_velocity_reversal_keep_reason(
        trade, best=16.0, pnl_pts=11.0, live_velocity_3s=-0.5,
    )
    assert reason == "explosion_peak_velocity_reversal_keep"


@patch("app.engines.explosion_profit.get_settings")
def test_reversal_keep_holds_when_velocity_dips_but_momentum_still_hot(mock_settings):
    """Fast negative v3 alone is not enough — premium mom must also roll over."""
    s = _settings()
    mock_settings.return_value = s
    trade = _sep08_deep_itm_trade(pnl_pts=11.0)
    trade.entryContext["executionChart"] = {
        "premiumChart": {"momentum3Pct": 2.5, "momentum5Pct": 1.8},
    }
    reason = peak_velocity_reversal_keep_reason(
        trade, best=16.0, pnl_pts=11.0, live_velocity_3s=-3.5,
    )
    assert reason is None


@patch("app.engines.explosion_profit.get_settings")
def test_reversal_keep_fires_mature_peak_after_rollover_confirmed(mock_settings):
    """After defer window: observed peak + cold velocity + flat mom → book."""
    s = _settings()
    mock_settings.return_value = s
    entry = 230.65
    best = 45.0  # ~19.5% gain, 5.6% of 800pt runway — past defer bars
    pnl_pts = 32.0  # below 75% floor (33.75), giveback 13pt
    trade = _sep09_elite_runner_trade(pnl_pts=pnl_pts, best=best)
    trade.entryPremium = entry
    trade.currentPremium = entry + pnl_pts
    trade.entryContext["executionChart"] = {
        "premiumChart": {"momentum3Pct": 0.05, "momentum5Pct": 0.0},
    }
    reason = peak_velocity_reversal_keep_reason(
        trade, best=best, pnl_pts=pnl_pts, live_velocity_3s=-2.5,
    )
    assert reason == "explosion_peak_velocity_reversal_keep"


@patch("app.engines.explosion_profit.get_settings")
def test_reversal_keep_skips_still_hot_tape(mock_settings):
    s = _settings()
    mock_settings.return_value = s
    trade = _sep08_deep_itm_trade(pnl_pts=10.0)
    reason = peak_velocity_reversal_keep_reason(
        trade, best=16.0, pnl_pts=10.0, live_velocity_3s=3.0,
    )
    assert reason is None


@patch("app.engines.ict_breakout_monitor._ict_max_profit_trade", return_value=True)
@patch("app.engines.explosion_confidence.trade_is_high_conviction", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_evaluate_exit_books_sep08_on_fast_reversal(mock_ms, mock_s, _hc, _mp):
    """+16pt peak fading to +11 with v3=-3 exits; %-keep never armed at 10.6% gain."""
    s = _settings()
    mock_s.return_value = s
    mock_ms.return_value = s
    trade = _sep08_deep_itm_trade(pnl_pts=11.0)
    params = ExplosionExitParams(
        stop_points=27.0,
        target_points=60.0,
        trail_arm_points=19.0,
        trail_keep_ratio=0.54,
        micro_target_points=100.0,
        adaptive_stop=True,
    )
    reason, pnl = evaluate_explosion_exit(
        trade,
        161.80,
        "ELITE",
        65,
        params=params,
        live_velocity_3s=-3.0,
    )
    assert reason == "explosion_peak_velocity_reversal_keep"
    assert pnl > 0
