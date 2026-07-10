"""Chart-confidence hold until target — no scratch exits when conf is high."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.confidence_hold import (
    hold_until_target_active,
    is_confidence_runner_hold,
    target_points_for_trade,
)
from app.engines.explosion_profit import _defer_adaptive_stop, evaluate_explosion_exit
from app.engines.explosion_profit import explosion_exit_params_from_plan
from app.engines.adaptive_exits import AdaptiveExitPlan
from app.models.schemas import PaperTrade, Side, StrategyType

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


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.confidence_hold.get_settings")
def test_adaptive_stop_deferred_until_target(mock_conf, mock_exp):
    s = MagicMock()
    s.chart_confidence_hold_enabled = True
    s.chart_confidence_hold_min_confidence = 62.0
    s.chart_confidence_hold_min_target_pct = 0.85
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
