"""Jun 25 scalp entry gates — relaxed breadth, velocity fallback."""

from unittest.mock import MagicMock, patch

from app.engines.simple_profit import check_entry_gate
from app.models.schemas import Breadth, Side, SuggestedTrade, StrategyType


def _trade(**kwargs) -> SuggestedTrade:
    base = dict(
        id="t1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24000.0,
        lastPremium=50.0,
        tqs=56.0,
        strategyType=StrategyType.SCALP,
        confidence=56.0,
    )
    base.update(kwargs)
    return SuggestedTrade(**base)


def _jun25_settings() -> MagicMock:
    s = MagicMock()
    s.sure_shot_mode_enabled = False
    s.aggressive_lot_sizing = True
    s.aggressive_min_tqs = 50
    s.enhanced_tqs_entry = 50
    s.enhanced_velocity_threshold = 1.2
    return s


@patch("app.engines.simple_profit.get_settings")
def test_low_velocity_blocked_when_score_low(mock_settings):
    mock_settings.return_value = _jun25_settings()
    trade = _trade(tqs=45.0, confidence=45.0)
    ok, reason = check_entry_gate(
        trade, Breadth(score=60, bias="BULLISH", aligned=True), 45.0, 0.5, False,
    )
    assert not ok
    assert "velocity_below" in reason


@patch("app.engines.simple_profit.get_settings")
def test_velocity_fallback_when_score_high(mock_settings):
    mock_settings.return_value = _jun25_settings()
    trade = _trade()
    ok, reason = check_entry_gate(
        trade, Breadth(score=60, bias="BULLISH", aligned=True), 50.0, 0.5, False,
    )
    assert ok
    assert reason == "passed"


@patch("app.engines.simple_profit.get_settings")
def test_aligned_bullish_call_passes(mock_settings):
    mock_settings.return_value = _jun25_settings()
    trade = _trade()
    ok, reason = check_entry_gate(
        trade, Breadth(score=65, bias="BULLISH", aligned=True), 50.0, 2.0, False,
    )
    assert ok
    assert reason == "passed"
