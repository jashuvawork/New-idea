"""Defer early adaptive SL on aligned high-confidence explosions."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_profit import _defer_adaptive_stop
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


@patch("app.engines.explosion_profit.get_settings")
def test_defer_adaptive_stop_aligned_high_chart(mock_settings):
    s = MagicMock()
    s.all_day_min_chart_confidence = 62.0
    mock_settings.return_value = s

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
        entryContext={"chartConfidence": 95.0, "breadth": "BULLISH"},
    )
    assert _defer_adaptive_stop(trade, best=1.1, hold=27.0, settings=s) is True


@patch("app.engines.explosion_profit.get_settings")
def test_no_defer_when_best_already_extended(mock_settings):
    s = MagicMock()
    s.all_day_min_chart_confidence = 62.0
    mock_settings.return_value = s

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
        entryContext={"chartConfidence": 95.0, "breadth": "BULLISH"},
    )
    assert _defer_adaptive_stop(trade, best=6.0, hold=30.0, settings=s) is False
