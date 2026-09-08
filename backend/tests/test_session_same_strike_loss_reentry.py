"""Session same-strike loss re-entry — Sep08 23650 PE twice."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.session_mode_feedback import session_same_strike_loss_reentry_blocked
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.session_same_strike_loss_reentry_enabled = True
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _closed_trade(*, pnl: float, strike: float = 23650.0) -> PaperTrade:
    return PaperTrade(
        id="loss1",
        symbol="NIFTY",
        side=Side.PUT,
        strike=strike,
        entryPremium=33.55,
        currentPremium=27.0,
        lots=6,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST),
        closedAt=datetime.now(IST),
        pnlInr=pnl,
        exitReason="adaptive_stop_loss",
        entryContext={"selectionMode": "explosion"},
    )


@patch("app.engines.session_mode_feedback.get_settings")
def test_blocks_same_strike_after_loss(mock_settings):
    mock_settings.return_value = _settings()
    state = AutoTraderState(closedPaperTrades=[_closed_trade(pnl=-2704.0)])

    blocked, meta = session_same_strike_loss_reentry_blocked(
        state,
        symbol="NIFTY",
        side=Side.PUT,
        strike=23650.0,
    )

    assert blocked is True
    assert meta["reason"] == "session_same_strike_loss_reentry_blocked"
    assert meta["priorPnlInr"] == -2704.0


@patch("app.engines.session_mode_feedback.get_settings")
def test_allows_same_strike_after_win(mock_settings):
    mock_settings.return_value = _settings()
    state = AutoTraderState(closedPaperTrades=[_closed_trade(pnl=5000.0)])

    blocked, meta = session_same_strike_loss_reentry_blocked(
        state,
        symbol="NIFTY",
        side=Side.PUT,
        strike=23650.0,
    )

    assert blocked is False
    assert meta.get("applied") is False


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
@patch("app.engines.session_mode_feedback.get_settings")
def test_allows_other_strike_after_loss(mock_settings, side):
    mock_settings.return_value = _settings()
    loss = _closed_trade(pnl=-1000.0, strike=23650.0 if side == Side.CALL else 23700.0)
    loss.side = Side.PUT if side == Side.CALL else Side.CALL
    state = AutoTraderState(closedPaperTrades=[loss])

    blocked, _ = session_same_strike_loss_reentry_blocked(
        state,
        symbol="NIFTY",
        side=Side.PUT,
        strike=23700.0 if side == Side.CALL else 23650.0,
    )

    assert blocked is False
