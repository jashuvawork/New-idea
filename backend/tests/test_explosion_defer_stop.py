"""Defer early adaptive SL on aligned high-confidence explosions."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_profit import _defer_adaptive_stop
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.confidence_hold.get_settings")
def test_defer_adaptive_stop_aligned_high_chart(mock_conf, mock_exp):
    s = MagicMock()
    s.chart_confidence_hold_enabled = True
    s.chart_confidence_hold_min_confidence = 62.0
    s.chart_confidence_hold_min_target_pct = 0.85
    s.high_confidence_min_score = 72.0
    s.all_day_min_chart_confidence = 62.0
    s.explosion_stop_min_hold_seconds = 15
    s.runner_min_best_points = 5.0
    mock_conf.return_value = s
    mock_exp.return_value = s

    trade = PaperTrade(
        id="t1",
        symbol="SENSEX",
        side=Side.CALL,
        strike=78000.0,
        entryPremium=200.0,
        currentPremium=195.0,
        lots=5,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST),
        entryContext={
            "chartConfidence": 95.0,
            "breadth": "BULLISH",
            "selectionScore": 80.0,
            "exitPlan": {"targetPoints": 50.0},
        },
    )
    assert _defer_adaptive_stop(trade, best=1.1, hold=27.0, settings=s) is True


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.confidence_hold.get_settings")
def test_no_defer_when_best_already_extended(mock_conf, mock_exp):
    s = MagicMock()
    s.chart_confidence_hold_enabled = True
    s.chart_confidence_hold_min_confidence = 62.0
    s.chart_confidence_hold_min_target_pct = 0.85
    s.high_confidence_min_score = 72.0
    s.all_day_min_chart_confidence = 62.0
    s.runner_min_best_points = 5.0
    mock_conf.return_value = s
    mock_exp.return_value = s

    trade = PaperTrade(
        id="t2",
        symbol="SENSEX",
        side=Side.CALL,
        strike=78000.0,
        entryPremium=200.0,
        currentPremium=210.0,
        lots=5,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST),
        entryContext={
            "chartConfidence": 95.0,
            "breadth": "BULLISH",
            "exitPlan": {"targetPoints": 12.0},
        },
    )
    assert _defer_adaptive_stop(trade, best=11.0, hold=30.0, settings=s) is False
