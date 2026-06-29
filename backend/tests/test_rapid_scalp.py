"""Scalp entry gates — sure-shot profile requires real velocity."""

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
        tqs=56.0,
        strategyType=StrategyType.SCALP,
        confidence=56.0,
    )
    base.update(kwargs)
    return SuggestedTrade(**base)


@patch("app.engines.simple_profit.get_settings")
def test_sure_shot_requires_velocity(mock_settings):
    settings = mock_settings.return_value
    settings.sure_shot_mode_enabled = True
    settings.sure_shot_scalp_min_score = 55
    settings.aggressive_lot_sizing = True
    settings.aggressive_min_tqs = 52
    settings.enhanced_velocity_threshold = 1.4
    settings.enhanced_tqs_entry = 55
    settings.midday_chop_block_scalps = False

    trade = _trade(tqs=48.0, confidence=48.0)
    ok, reason = check_entry_gate(
        trade, Breadth(score=65, bias="BULLISH", aligned=True), 50.0, 0.5, False,
    )
    assert not ok
    assert "velocity_below" in reason


@patch("app.engines.simple_profit.get_settings")
@patch("app.engines.simple_profit.get_market_phase", return_value="LIVE_MARKET")
def test_midday_chop_targets(_phase, mock_settings):
    settings = mock_settings.return_value
    settings.scalp_stop_points = 2.5
    settings.enhanced_micro_target_points = 2.0

    with patch("app.engines.simple_profit.datetime") as mock_dt:
        mock_dt.now.return_value = type("T", (), {"hour": 12, "minute": 15})()
        profile = get_session_targets()
    assert profile.sessionLabel == "midday_chop"
    assert profile.microTargetPoints == 2.0
    assert profile.maxHoldSeconds == 150
