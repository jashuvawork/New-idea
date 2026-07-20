"""Chart-confidence hold until target — no scratch exits when conf is high."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.confidence_hold import (
    half_tp_giveback_exit,
    half_tp_reached,
    hold_until_target_active,
    is_confidence_runner_hold,
    should_defer_no_progress_exit,
    should_defer_profit_lock,
    target_points_for_trade,
)
from app.engines.explosion_profit import _defer_adaptive_stop, evaluate_explosion_exit
from app.engines.explosion_profit import explosion_exit_params_from_plan
from app.engines.adaptive_exits import AdaptiveExitPlan
from app.engines.simple_profit import evaluate_exit
from app.models.schemas import OptimizedProfile, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _trade(**ctx) -> PaperTrade:
    base = {
        "chartConfidence": 95.0,
        "entryChartConfidence": 95.0,
        "breadth": "BULLISH",
        "selectionScore": 100.0,
        "exitPlan": {"targetPoints": 120.0, "stopPoints": 8.0, "chartConfidence": 95.0},
    }
    base.update(ctx)
    return PaperTrade(
        id="h1",
        symbol="SENSEX",
        side=Side.CALL,
        strike=78000.0,
        entryPremium=273.0,
        currentPremium=268.0,
        lots=7,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST),
        bestPnlPoints=1.1,
        entryContext=base,
    )


@patch("app.engines.confidence_hold.get_settings")
def test_confidence_runner_hold_detected(mock_settings):
    s = MagicMock()
    s.chart_confidence_hold_enabled = True
    s.chart_confidence_hold_min_confidence = 62.0
    s.high_confidence_min_score = 72.0
    s.all_day_min_chart_confidence = 62.0
    s.runner_min_best_points = 5.0
    s.chart_confidence_hold_min_target_pct = 0.85
    mock_settings.return_value = s
    assert is_confidence_runner_hold(_trade()) is True
    assert target_points_for_trade(_trade()) == 120.0
    assert hold_until_target_active(_trade(), best=1.1) is True
    assert hold_until_target_active(_trade(), best=110.0) is False


@patch("app.engines.confidence_hold.get_settings")
def test_half_tp_unlocks_profit_lock_before_full_target(mock_settings):
    s = MagicMock()
    s.chart_confidence_hold_enabled = True
    s.chart_confidence_hold_min_confidence = 62.0
    s.chart_confidence_hold_min_target_pct = 0.85
    s.chart_confidence_half_tp_lock_pct = 0.50
    s.chart_confidence_half_tp_giveback_ratio = 0.40
    s.high_confidence_min_score = 72.0
    s.all_day_min_chart_confidence = 62.0
    s.runner_min_best_points = 5.0
    s.scalp_micro_giveback_points = 3.0
    mock_settings.return_value = s
    trade = _trade()
    trade.entryContext["exitPlan"] = {"targetPoints": 20.4, "targetPoints2": 36.5}
    # 12pt best = past half-TP (10.2) but below full hold floor (17.3)
    assert half_tp_reached(trade, best=12.0) is True
    assert hold_until_target_active(trade, best=12.0) is True
    assert should_defer_profit_lock(trade, best=12.0) is False
    assert half_tp_giveback_exit(trade, best=12.0, pnl_pts=1.3) is True


@patch("app.engines.psychology_hold.get_settings")
@patch("app.engines.bullish_hold.get_settings")
@patch("app.engines.simple_profit.get_settings")
@patch("app.engines.confidence_hold.get_settings")
def test_armed_trail_exits_when_confidence_hold_would_defer_into_loss(
    mock_ch, mock_sp, mock_bh, mock_psy,
):
    """Jul20 NIFTY 23950 CE: best +16pt, floor 14.2, then red — must trail out."""
    s = _scalp_settings()
    s.chart_confidence_half_tp_lock_pct = 0.50
    s.chart_confidence_half_tp_giveback_ratio = 0.40
    s.scalp_trail_arm_points = 1.2
    s.scalp_trail_keep_ratio = 0.82
    s.scalp_trail_step_points = 2.0
    s.scalp_trail_tight_arm = 8.0
    s.scalp_trail_tight_points = 3.0
    s.bullish_hold_enabled = True
    s.bullish_hold_trail_keep_ratio = 0.85
    s.bullish_hold_max_hold_multiplier = 1.5
    s.psychology_hold_enabled = False
    s.scalp_micro_lock_min_best_points = 4.5
    s.scalp_min_hold_before_micro_lock_seconds = 90
    mock_ch.return_value = s
    mock_sp.return_value = s
    mock_bh.return_value = s
    mock_psy.return_value = s

    trade = _nifty_call_trade(
        breadth="BULLISH",
        chartConfidence=71.0,
        entryChartConfidence=89.2,
        selectionScore=84.42,
        exitPlan={
            "targetPoints": 47.59,
            "entryTargetPoints": 43.85,
            "stopPoints": 2.5,
            "trailArmPoints": 1.2,
            "trailKeepRatio": 0.819,
            "trailStepPoints": 2.0,
            "trailTightArm": 8.0,
            "trailTightPoints": 3.0,
            "microTargetPoints": 7.4,
            "chartConfidence": 71.0,
            "promoteToTrailing": True,
        },
        scalpTrailFloorPts=14.2,
        scalpTrailBestPts=16.2,
    )
    trade.entryPremium = 242.05
    trade.bestPnlPoints = 16.2
    trade.lots = 8
    trade.openedAt = datetime.now(IST) - timedelta(seconds=600)

    # Still green but below trail floor — trail must fire (was deferred before).
    reason, pnl = evaluate_exit(trade, 255.0, OptimizedProfile(
        targetPoints=47.59, stopPoints=2.5, microTargetPoints=7.4,
        maxHoldSeconds=480, sessionLabel="momentum_rally",
    ), lot_multiplier=65)
    assert reason == "scalp_trail_sl"
    assert pnl > 0

    # Red after +16pt peak — hard trail / SL safety, never hold for distant chart TP.
    trade2 = _nifty_call_trade(
        breadth="BULLISH",
        chartConfidence=71.0,
        entryChartConfidence=89.2,
        selectionScore=84.42,
        exitPlan={
            "targetPoints": 47.59,
            "entryTargetPoints": 43.85,
            "stopPoints": 2.5,
            "trailArmPoints": 1.2,
            "trailKeepRatio": 0.819,
            "trailStepPoints": 2.0,
            "trailTightArm": 8.0,
            "trailTightPoints": 3.0,
            "microTargetPoints": 7.4,
            "chartConfidence": 71.0,
        },
        scalpTrailFloorPts=14.2,
        scalpTrailBestPts=16.2,
    )
    trade2.entryPremium = 242.05
    trade2.bestPnlPoints = 16.2
    trade2.lots = 8
    trade2.openedAt = datetime.now(IST) - timedelta(seconds=600)
    reason2, pnl2 = evaluate_exit(trade2, 235.3, OptimizedProfile(
        targetPoints=47.59, stopPoints=2.5, microTargetPoints=7.4,
        maxHoldSeconds=480, sessionLabel="momentum_rally",
    ), lot_multiplier=65)
    assert reason2 == "scalp_trail_sl"
    assert pnl2 < 0
    assert should_defer_profit_lock(trade2, 16.2, target_points=47.59, pnl_pts=-6.75) is False


@patch("app.engines.psychology_hold.get_settings")
@patch("app.engines.bullish_hold.get_settings")
@patch("app.engines.simple_profit.get_settings")
@patch("app.engines.confidence_hold.get_settings")
def test_nifty_scalp_half_tp_lock_on_giveback(mock_ch, mock_sp, mock_bh, mock_psy):
    s = _scalp_settings()
    s.chart_confidence_half_tp_lock_pct = 0.50
    s.chart_confidence_half_tp_giveback_ratio = 0.40
    mock_ch.return_value = s
    mock_sp.return_value = s
    mock_bh.return_value.bullish_hold_enabled = False
    mock_psy.return_value.psychology_hold_enabled = False

    trade = _nifty_call_trade()
    trade.bestPnlPoints = 11.0
    trade.openedAt = datetime.now(IST) - timedelta(seconds=200)
    profile = OptimizedProfile(
        targetPoints=8.0,
        stopPoints=3.0,
        microTargetPoints=2.5,
        maxHoldSeconds=300,
        sessionLabel="normal",
    )
    # Entry 120, current 121.3 → +1.3pt; best was 11pt
    reason, pnl = evaluate_exit(trade, 121.3, profile, lot_multiplier=25)
    assert reason == "simple_half_tp_profit_lock"
    assert pnl > 0


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.confidence_hold.get_settings")
def test_adaptive_stop_deferred_until_target(mock_conf, mock_exp):
    s = MagicMock()
    s.chart_confidence_hold_enabled = True
    s.chart_confidence_hold_min_confidence = 62.0
    s.chart_confidence_hold_min_target_pct = 0.85
    s.chart_confidence_half_tp_lock_pct = 0.50
    s.chart_confidence_half_tp_giveback_ratio = 0.40
    s.high_confidence_min_score = 72.0
    s.all_day_min_chart_confidence = 62.0
    s.explosion_stop_min_hold_seconds = 15
    s.chart_confidence_hold_stop_mult = 1.35
    s.explosion_no_progress_enabled = True
    s.explosion_no_progress_skip_when_aligned = True
    s.explosion_no_progress_aligned_seconds = 420
    s.explosion_no_progress_seconds = 150
    s.runner_min_best_points = 5.0
    s.runner_trail_keep_ratio = 0.38
    s.runner_micro_giveback_points = 4.0
    s.emergency_stop_enabled = False
    mock_conf.return_value = s
    mock_exp.return_value = s

    trade = _trade()
    assert _defer_adaptive_stop(trade, best=1.1, hold=30.0, settings=s) is True

    plan = AdaptiveExitPlan(stopPoints=8.0, targetPoints=120.0, trailArmPoints=4.0, trailKeepRatio=0.65)
    params = explosion_exit_params_from_plan(plan, "EXPLODING")
    reason, _ = evaluate_explosion_exit(trade, 268.0, "EXPLODING", 20, params=params)
    assert reason is None


def _scalp_settings() -> MagicMock:
    s = MagicMock()
    s.chart_confidence_hold_enabled = True
    s.chart_confidence_hold_min_confidence = 62.0
    s.chart_confidence_hold_min_target_pct = 0.85
    s.chart_confidence_hold_max_seconds = 600
    s.high_confidence_min_score = 72.0
    s.high_confidence_hold_enabled = True
    s.high_confidence_max_hold_multiplier = 1.8
    s.high_confidence_micro_min_best_points = 6.0
    s.high_confidence_min_hold_before_micro_seconds = 180
    s.high_confidence_micro_giveback_points = 4.5
    s.high_confidence_trail_keep_ratio = 0.55
    s.all_day_min_chart_confidence = 62.0
    s.runner_min_best_points = 5.0
    s.scalp_no_progress_seconds = 150
    s.scalp_no_progress_aligned_seconds = 420
    s.scalp_no_progress_skip_when_aligned = True
    s.scalp_trail_arm_points = 4.5
    s.scalp_trail_keep_ratio = 0.65
    s.scalp_trail_step_points = 2.0
    s.scalp_trail_tight_arm = 10.0
    s.scalp_trail_tight_points = 4.0
    s.scalp_stop_min_hold_seconds = 30
    s.scalp_micro_lock_min_best_points = 4.5
    s.scalp_min_hold_before_micro_lock_seconds = 90
    s.scalp_micro_giveback_points = 3.0
    s.runner_micro_giveback_points = 3.5
    s.runner_trail_keep_ratio = 0.7
    s.bullish_hold_enabled = False
    s.emergency_stop_enabled = False
    return s


def _nifty_call_trade(**ctx) -> PaperTrade:
    base = {
        "chartConfidence": 88.0,
        "entryChartConfidence": 88.0,
        "breadth": "BULLISH",
        "selectionScore": 82.0,
        "exitPlan": {"targetPoints": 20.4, "stopPoints": 6.0, "chartConfidence": 88.0, "targetPoints2": 36.5},
    }
    base.update(ctx)
    return PaperTrade(
        id="n1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24200.0,
        entryPremium=120.0,
        currentPremium=109.0,
        lots=18,
        strategyType=StrategyType.SCALP,
        openedAt=datetime.now(IST),
        bestPnlPoints=0.0,
        entryContext=base,
    )


@patch("app.engines.confidence_hold.get_settings")
def test_aligned_scalp_defers_no_progress_scratch(mock_settings):
    s = _scalp_settings()
    mock_settings.return_value = s
    trade = _nifty_call_trade()
    assert should_defer_no_progress_exit(trade, best=0.0) is True


@patch("app.engines.psychology_hold.get_settings")
@patch("app.engines.bullish_hold.get_settings")
@patch("app.engines.simple_profit.get_settings")
@patch("app.engines.confidence_hold.get_settings")
def test_no_progress_scratch_skipped_for_high_conf_nifty_call(mock_ch, mock_sp, mock_bh, mock_psy):
    s = _scalp_settings()
    mock_ch.return_value = s
    mock_sp.return_value = s
    mock_bh.return_value.bullish_hold_enabled = False
    mock_psy.return_value.psychology_hold_enabled = False

    trade = _nifty_call_trade()
    trade.openedAt = datetime.now(IST) - timedelta(seconds=200)
    profile = OptimizedProfile(
        targetPoints=8.0,
        stopPoints=3.0,
        microTargetPoints=2.5,
        maxHoldSeconds=300,
        sessionLabel="normal",
    )
    reason, _ = evaluate_exit(trade, 109.0, profile, lot_multiplier=25)
    assert reason is None
