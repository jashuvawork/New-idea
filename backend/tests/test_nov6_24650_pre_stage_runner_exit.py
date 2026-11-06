"""Nov 6 NIFTY 24650 CE — pre-stage runner must not max-hold giveback trail_sl."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from zoneinfo import ZoneInfo

from app.engines.explosion_profit import ExplosionExitParams, evaluate_explosion_exit
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.moment_stage_trail_enabled = True
    s.explosion_trail_pre_stage_suppress_step = True
    s.explosion_trail_hot_defer_enabled = True
    s.explosion_trail_arm_points = 4.0
    s.explosion_trail_keep_ratio = 0.583
    s.explosion_trail_step_points = 2.0
    s.explosion_trail_tight_arm = 999.0
    s.explosion_trail_tight_points = 0.0
    s.moment_stage_hot_hold_velocity_3s = 2.5
    s.stage_runner_pre_stage_hot_defer_min_velocity_3s = 1.0
    s.stage_runner_defer_pre_stage_trail_min_projected_tp = 500.0
    s.stage_runner_defer_peak_keep_complete_frac = 1.0
    s.stage_runner_defer_unified_peak_keep_min_projected_tp = 1200.0
    s.moment_stage_giveback_ratio = 0.50
    s.moment_stage_late_giveback_ratio = 1.0
    s.moment_stage_late_progress = 0.70
    s.moment_stage_min_remain_points = 1.0
    s.moment_stage_near_complete_frac = 0.82
    s.ftv_runner_pct_trail_enabled = True
    s.ftv_runner_pct_trail_arm_pct = 25.0
    s.ftv_runner_pct_trail_arm_min_best_points = 20.0
    s.ftv_runner_pct_trail_keep_ratio = 0.75
    s.runner_min_best_points = 25.0
    s.runner_trail_keep_ratio = 0.55
    s.runner_micro_giveback_points = 4.0
    s.explosion_elite_max_hold_seconds = 1800
    s.explosion_stop_min_hold_seconds = 0
    s.emergency_stop_enabled = False
    s.explosion_no_progress_enabled = False
    s.explosion_peak_fade_lock_enabled = False
    s.explosion_peak_capture_enabled = False
    s.ict_max_profit_target_points = 180.0
    s.ict_max_profit_skip_hard_target = True
    s.ict_max_profit_trail_keep_ratio = 0.42
    s.unified_profit_ladder_enabled = True
    s.unified_profit_ladder_min_best_points = 4.0
    s.unified_profit_ladder_min_hold_seconds = 180.0
    s.unified_profit_ladder_min_seconds_after_peak = 180.0
    s.unified_profit_ladder_keep_arm_pct = 15.0
    s.unified_profit_ladder_keep_ratio = 0.75
    s.unified_profit_ladder_floor_touch_points = 2.0
    s.unified_profit_ladder_hot_defer_velocity_3s = 2.0
    s.unified_profit_ladder_fall_min_hold_seconds = 60.0
    s.unified_profit_ladder_fall_min_seconds_after_peak = 45.0
    s.stage_runner_pre_stage_fall_min_seconds_after_peak = 120.0
    s.tp_rung_ladder_exit_enabled = False
    s.peak_velocity_reversal_keep_enabled = False
    s.elite_runner_skip_time_stop_enabled = True
    s.explosion_target_standard = 12.0
    s.chart_confidence_half_tp_giveback_ratio = 0.40
    s.explosion_stage_trail_min_hold_seconds = 90.0
    s.stage_runner_defer_pct_keep_min_projected_tp = 400.0
    s.stage_runner_defer_pct_keep_min_best_points = 28.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _params():
    return ExplosionExitParams(
        stop_points=26.0,
        target_points=42.0,
        trail_arm_points=15.0,
        trail_keep_ratio=0.583,
        micro_target_points=500.0,
        adaptive_stop=False,
    )


def _nov6_trade(*, hold_seconds: float = 3200.0) -> PaperTrade:
    entry = 145.67
    best = 24.03
    current = entry + 15.37
    ctx = {
        "selectionMode": "explosion",
        "explosionTier": "ELITE",
        "momentStageLadder": True,
        "maxProfitCapture": True,
        "vBaseFtvRunner": True,
        "projectedMaxTp": 705.0,
        "stageSize": 75.0,
        "stageGivebackRatio": 0.50,
        "exitPlan": {
            "trailArmPoints": 14.98,
            "trailKeepRatio": 0.583,
            "projectedMaxTp": 705.0,
            "stageSize": 75.0,
            "momentStageLadder": True,
        },
    }
    return PaperTrade(
        id="nov6-24650",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24650.0,
        entryPremium=entry,
        currentPremium=current,
        lots=19,
        openedAt=datetime.now(IST) - timedelta(seconds=hold_seconds),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=best,
        maxLtp=entry + best,
        pnlPoints=15.37,
        entryContext=ctx,
    )


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_pre_stage_runner_skips_max_hold_giveback_trail_sl(mock_ms, mock_ep):
    mock_ep.return_value = _settings()
    mock_ms.return_value = _settings()
    trade = _nov6_trade(hold_seconds=3200.0)
    reason, pnl = evaluate_explosion_exit(
        trade,
        trade.currentPremium,
        "ELITE",
        65,
        params=_params(),
        live_velocity_3s=0.3,
    )
    assert reason != "explosion_trail_sl"
    assert pnl > 0


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_pre_stage_runner_defers_pct_peak_keep_during_pullback(mock_ms, mock_ep):
    mock_ep.return_value = _settings()
    mock_ms.return_value = _settings()
    trade = _nov6_trade(hold_seconds=600.0)
    trade.currentPremium = trade.entryPremium + 14.0
    trade.pnlPoints = 14.0
    reason, _ = evaluate_explosion_exit(
        trade,
        trade.currentPremium,
        "ELITE",
        65,
        params=_params(),
        live_velocity_3s=0.4,
    )
    assert reason != "explosion_peak_keep_trail"


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.moment_stage_trail.get_settings")
def test_pre_stage_runner_micro_trail_deferred_on_mild_dip(mock_ms, mock_ep):
    mock_ep.return_value = _settings()
    mock_ms.return_value = _settings()
    trade = _nov6_trade(hold_seconds=600.0)
    trade.currentPremium = trade.entryPremium + 14.0
    trade.pnlPoints = 14.0
    reason, _ = evaluate_explosion_exit(
        trade,
        trade.currentPremium,
        "ELITE",
        65,
        params=_params(),
        live_velocity_3s=1.2,
    )
    assert reason != "explosion_trail_sl"
