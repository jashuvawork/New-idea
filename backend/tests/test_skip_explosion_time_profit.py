"""Jul29 SENSEX 77600 CE — don't time-profit scratch ELITE before the rip prints."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_profit import ExplosionExitParams, evaluate_explosion_exit
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    defaults = {
        "explosion_target_standard": 12.0,
        "explosion_target_elite": 25.0,
        "explosion_initial_stop_points": 6.0,
        "explosion_trail_arm_points": 4.0,
        "explosion_trail_keep_ratio": 0.65,
        "runner_trail_keep_ratio": 0.38,
        "runner_min_best_points": 5.0,
        "runner_micro_giveback_points": 4.0,
        "chart_confidence_half_tp_giveback_ratio": 0.40,
        "explosion_no_progress_enabled": True,
        "explosion_no_progress_seconds": 150,
        "explosion_no_progress_aligned_seconds": 420,
        "explosion_no_progress_skip_when_aligned": True,
        "chart_confidence_hold_enabled": True,
        "chart_confidence_hold_min_confidence": 62.0,
        "chart_confidence_half_tp_lock_pct": 0.50,
        "chart_confidence_hold_min_target_pct": 0.85,
        "chart_confidence_hold_max_seconds": 600,
        "chart_confidence_hold_stop_mult": 1.0,
        "chart_confidence_elevated_threshold": 56.9,
        "high_confidence_min_score": 72.0,
        "all_day_min_chart_confidence": 62.0,
        "scalp_micro_giveback_points": 3.0,
        "emergency_stop_enabled": False,
        "explosion_stop_min_hold_seconds": 15,
        "explosion_trail_step_points": 2.0,
        "explosion_trail_tight_arm": 999.0,
        "explosion_trail_tight_points": 0.0,
        "afternoon_capture_exit_max_hold_seconds": 480,
        "ict_max_profit_max_hold_seconds": 1200,
        "ict_max_profit_skip_hard_target": True,
        "ict_max_profit_target_points": 180.0,
        "ict_mega_rip_trail_arm_multiplier": 1.0,
        "ict_breakout_trail_arm_multiplier": 1.0,
        "high_conviction_defer_profit_lock": True,
        "high_conviction_trail_keep_ratio": 0.30,
        "explosion_skip_time_profit_enabled": True,
        "explosion_skip_time_profit_tiers_csv": "ELITE,EXPLODING",
        "explosion_skip_time_profit_until_target_frac": 0.85,
        "explosion_elite_max_hold_seconds": 1800,
        "chart_confidence_defer_tp_min": 60.6,
        "scalp_no_progress_skip_when_aligned": True,
        # Isolate time-profit hold — MagicMock would invent peak-fade flags.
        "explosion_peak_fade_lock_enabled": False,
        "explosion_peak_capture_enabled": False,
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def _params():
    return ExplosionExitParams(
        stop_points=17.14,
        target_points=36.92,
        trail_arm_points=14.86,
        trail_keep_ratio=0.65,
        micro_target_points=7.0,
        adaptive_stop=True,
    )


def _jul29_77600(*, hold_seconds: int = 800, pnl_pts: float = 0.30, best: float = 5.49):
    entry = 251.82
    return PaperTrade(
        id="5b899acf",
        symbol="SENSEX",
        side=Side.CALL,
        strike=77600.0,
        entryPremium=entry,
        currentPremium=entry + pnl_pts,
        lots=37,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST) - timedelta(seconds=hold_seconds),
        bestPnlPoints=best,
        entryContext={
            "selectionMode": "explosion",
            "explosionTier": "ELITE",
            "explosionScore": 100.0,
            "chartConfidence": 100.0,
            "entryChartConfidence": 100.0,
            "afternoonCapture": True,
            "topExplosionMaxLots": True,
            "breadth": {"bias": "BULLISH", "score": 80, "aligned": True},
            "exitPlan": {
                "stopPoints": 17.14,
                "targetPoints": 36.92,
                "entryTargetPoints": 36.92,
                "trailArmPoints": 14.86,
                "entryTrailArmPoints": 12.92,
                "microTargetPoints": 7.0,
                "chartConfidence": 100.0,
            },
        },
    )


@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.engines.bullish_hold.get_settings")
@patch("app.engines.confidence_hold.get_settings")
@patch("app.engines.explosion_profit.get_settings")
def test_jul29_77600_holds_past_time_profit(mock_ep, mock_ch, mock_bh, mock_ict):
    s = _settings()
    mock_ep.return_value = s
    mock_ch.return_value = s
    mock_bh.return_value = s
    mock_ict.return_value = s
    trade = _jul29_77600(hold_seconds=800, pnl_pts=0.30, best=5.49)
    reason, _ = evaluate_explosion_exit(
        trade, 252.12, "ELITE", 20, params=_params(),
    )
    assert reason != "explosion_time_profit", f"must hold toward TP, got {reason}"
        assert reason == "explosion_early_green_breakeven"


@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.engines.bullish_hold.get_settings")
@patch("app.engines.confidence_hold.get_settings")
@patch("app.engines.explosion_profit.get_settings")
def test_watch_first_lift_holds_past_generic_time_profit(
    mock_ep, mock_ch, mock_bh, mock_ict,
):
    s = _settings()
    mock_ep.return_value = s
    mock_ch.return_value = s
    mock_bh.return_value = s
    mock_ict.return_value = s
    trade = _jul29_77600(hold_seconds=800, pnl_pts=3.0, best=5.5)
    trade.entryContext.update({
        "explosionTier": "WATCH",
        "topExplosionMaxLots": False,
        "ictFirstLift": True,
        "firstLiftCapture": True,
        "momentType": "first_lift_local_base",
    })
    reason, _ = evaluate_explosion_exit(
        trade, trade.entryPremium + 3.0, "WATCH", 20, params=_params(),
    )
    assert reason is None


@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.engines.bullish_hold.get_settings")
@patch("app.engines.confidence_hold.get_settings")
@patch("app.engines.explosion_profit.get_settings")
def test_time_profit_allowed_after_near_target(mock_ep, mock_ch, mock_bh, mock_ict):
    s = _settings()
    mock_ep.return_value = s
    mock_ch.return_value = s
    mock_bh.return_value = s
    mock_ict.return_value = s
    trade = _jul29_77600(hold_seconds=2500, pnl_pts=28.0, best=32.0)
    reason, pnl = evaluate_explosion_exit(
        trade, 251.82 + 28.0, "ELITE", 20, params=_params(),
    )
    assert reason is not None
    assert pnl > 0
