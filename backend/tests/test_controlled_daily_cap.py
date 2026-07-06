"""Tests for dynamic controlled daily trade cap."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from app.engines.daily_18pct_strategy import TradingLimits
from app.engines.pretrade_validator import (
    controlled_daily_cap_reached,
    resolve_effective_daily_trade_cap,
)
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType

RALLY_PATCH = "app.engines.chop_day_guards.in_momentum_rally_window"
CHOP_PATCH = "app.engines.chop_day_guards.is_chop_session"
IST = __import__("zoneinfo").ZoneInfo("Asia/Kolkata")
_SNAPS = {"NIFTY": MagicMock(dataAvailable=True)}


def _limits(max_trades: int = 7) -> TradingLimits:
    return TradingLimits(maxTradesToday=max_trades)


def _closed_state(n: int) -> AutoTraderState:
    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id=str(i),
            symbol="NIFTY",
            side=Side.CALL,
            strike=23900,
            entryPremium=50,
            lots=10,
            openedAt=datetime.now(IST),
            pnlInr=100,
            strategyType=StrategyType.SCALP,
        )
        for i in range(n)
    ]
    return state


def test_base_cap_raised_to_10():
    with patch("app.engines.daily_18pct_strategy.get_session_limits", return_value=_limits(7)):
        with patch(RALLY_PATCH, return_value=False):
            with patch(CHOP_PATCH, return_value=False):
                cap, source = resolve_effective_daily_trade_cap({}, None)
    assert cap == 10
    assert source in ("controlled", "daily_strategy")


def test_momentum_rally_raises_cap():
    with patch("app.engines.daily_18pct_strategy.get_session_limits", return_value=_limits(7)):
        with patch(RALLY_PATCH, return_value=True):
            with patch(CHOP_PATCH, return_value=False):
                cap, source = resolve_effective_daily_trade_cap({}, _SNAPS)
    assert cap == 14
    assert source == "momentum_rally"


def test_chop_day_uses_chop_max():
    with patch("app.engines.daily_18pct_strategy.get_session_limits", return_value=_limits(7)):
        with patch(RALLY_PATCH, return_value=False):
            with patch(CHOP_PATCH, return_value=True):
                cap, _ = resolve_effective_daily_trade_cap({}, _SNAPS)
    assert cap == 10


def test_daily_18pct_expiry_cap_used_when_higher():
    with patch("app.engines.daily_18pct_strategy.get_session_limits", return_value=_limits(12)):
        with patch(RALLY_PATCH, return_value=False):
            with patch(CHOP_PATCH, return_value=False):
                cap, source = resolve_effective_daily_trade_cap({}, None)
    assert cap == 12
    assert source == "daily_strategy"


@patch("app.engines.pretrade_validator.collect_session_trades")
def test_cap_not_reached_at_six_trades(mock_collect):
    mock_collect.return_value = [MagicMock()] * 6
    with patch("app.engines.daily_18pct_strategy.get_session_limits", return_value=_limits(7)):
        with patch(RALLY_PATCH, return_value=True):
            reached, reason = controlled_daily_cap_reached(_closed_state(6), _SNAPS)
    assert reached is False
    assert reason == "ok"


@patch("app.engines.pretrade_validator.collect_session_trades")
def test_cap_reached_at_limit(mock_collect):
    mock_collect.return_value = [MagicMock()] * 14
    with patch("app.engines.daily_18pct_strategy.get_session_limits", return_value=_limits(7)):
        with patch(RALLY_PATCH, return_value=True):
            reached, reason = controlled_daily_cap_reached(_closed_state(14), _SNAPS)
    assert reached is True
    assert reason == "controlled_daily_cap_14"
