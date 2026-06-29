"""Rapid scalp mode tests."""

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
def test_rapid_velocity_fallback(mock_settings):
    settings = mock_settings.return_value
    settings.sure_shot_mode_enabled = False
    settings.rapid_scalp_mode_enabled = True
    settings.midday_chop_block_scalps = False
    settings.aggressive_lot_sizing = True
    settings.aggressive_min_tqs = 48
    settings.enhanced_velocity_threshold = 1.25

    trade = _trade(tqs=53.0, confidence=53.0)
    ok, reason = check_entry_gate(
        trade, Breadth(score=55, bias="NEUTRAL", aligned=False), 50.0, 0.3, False,
    )
    assert ok
    assert reason == "passed"


@patch("app.engines.simple_profit.get_settings")
@patch("app.engines.simple_profit.get_market_phase", return_value="LIVE_MARKET")
def test_midday_rapid_targets(_phase, mock_settings):
    settings = mock_settings.return_value
    settings.rapid_scalp_mode_enabled = True
    settings.enhanced_micro_target_points = 1.5
    settings.scalp_stop_points = 2.5

    with patch("app.engines.simple_profit.datetime") as mock_dt:
        mock_dt.now.return_value = type("T", (), {"hour": 12, "minute": 15})()
        profile = get_session_targets()
    assert profile.sessionLabel == "midday_rapid"
    assert profile.microTargetPoints == 1.5
    assert profile.maxHoldSeconds == 120
