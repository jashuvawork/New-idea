"""Scalp entry gates — velocity fallback (66K profile)."""

from unittest.mock import patch

from app.engines.simple_profit import check_entry_gate, get_session_targets
from app.models.schemas import Breadth, Side, SuggestedTrade, StrategyType


def _trade(**kwargs) -> SuggestedTrade:
    base = dict(
        id="t1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24000.0,
        lastPremium=50.0,
        tqs=50.0,
        strategyType=StrategyType.SCALP,
        confidence=50.0,
    )
    base.update(kwargs)
    return SuggestedTrade(**base)


@patch("app.engines.simple_profit.get_settings")
def test_velocity_fallback_when_score_strong(mock_settings):
    settings = mock_settings.return_value
    settings.aggressive_lot_sizing = True
    settings.aggressive_min_tqs = 50
    settings.enhanced_velocity_threshold = 1.2

    trade = _trade(tqs=56.0, confidence=56.0)
    ok, reason = check_entry_gate(
        trade, Breadth(score=55, bias="BULLISH", aligned=True), 50.0, 0.3, False,
    )
    assert ok
    assert reason == "passed"


@patch("app.engines.simple_profit.get_settings")
@patch("app.engines.simple_profit.get_market_phase", return_value="LIVE_MARKET")
def test_midday_chop_targets(_phase, mock_settings):
    settings = mock_settings.return_value
    settings.enhanced_micro_target_points = 2.5

    with patch("app.engines.simple_profit.datetime") as mock_dt:
        mock_dt.now.return_value = type("T", (), {"hour": 12, "minute": 15})()
        profile = get_session_targets()
    assert profile.sessionLabel == "midday_chop"
    assert profile.microTargetPoints == 2.5
    assert profile.maxHoldSeconds == 150
