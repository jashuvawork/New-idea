"""Sure-shot mode — fewer trades, higher conviction gates."""

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


def _sure_shot_settings() -> MagicMock:
    s = MagicMock()
    s.sure_shot_mode_enabled = True
    s.rapid_scalp_mode_enabled = False
    s.midday_chop_block_scalps = True
    s.sure_shot_scalp_min_score = 55
    s.aggressive_lot_sizing = True
    s.aggressive_min_tqs = 55
    s.enhanced_tqs_entry = 55
    s.enhanced_velocity_threshold = 1.8
    return s


@patch("app.engines.simple_profit.get_settings")
@patch("app.engines.simple_profit.in_midday_chop_window", return_value=False)
def test_low_velocity_blocked_no_fallback(_chop, mock_settings):
    mock_settings.return_value = _sure_shot_settings()
    trade = _trade()
    ok, reason = check_entry_gate(
        trade, Breadth(score=60, bias="BULLISH", aligned=True), 50.0, 0.5, False,
    )
    assert not ok
    assert "velocity_below" in reason


@patch("app.engines.simple_profit.get_settings")
@patch("app.engines.simple_profit.in_midday_chop_window", return_value=False)
def test_neutral_breadth_blocked_in_sure_shot(_chop, mock_settings):
    mock_settings.return_value = _sure_shot_settings()
    trade = _trade()
    ok, reason = check_entry_gate(
        trade, Breadth(score=50, bias="NEUTRAL", aligned=False), 50.0, 2.0, False,
    )
    assert not ok
    assert reason == "breadth_not_aligned"


@patch("app.engines.simple_profit.get_settings")
@patch("app.engines.simple_profit.in_midday_chop_window", return_value=False)
def test_aligned_bullish_call_passes(_chop, mock_settings):
    mock_settings.return_value = _sure_shot_settings()
    trade = _trade()
    ok, reason = check_entry_gate(
        trade, Breadth(score=65, bias="BULLISH", aligned=True), 50.0, 2.0, False,
    )
    assert ok
    assert reason == "passed"


@patch("app.engines.simple_profit.get_settings")
def test_midday_chop_blocks_without_conviction(mock_settings):
    mock_settings.return_value = _sure_shot_settings()
    trade = _trade(tqs=54.0, confidence=54.0)
    with patch("app.engines.simple_profit.in_midday_chop_window", return_value=True):
        ok, reason = check_entry_gate(
            trade, Breadth(score=50, bias="NEUTRAL", aligned=False), 50.0, 2.0, False,
        )
    assert not ok
    assert reason == "midday_chop_wait"
