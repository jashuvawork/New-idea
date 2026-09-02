"""Session-wide same-side cooldown after any explosion loss (Sep 2 cross-index PE)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.session_mode_feedback import session_same_side_loss_reentry_blocked
from app.models.schemas import AutoTraderState, Side

IST = ZoneInfo("Asia/Kolkata")


def _closed_loss(
    *,
    symbol: str = "SENSEX",
    side: Side = Side.PUT,
    minutes_ago: float = 6.0,
    pnl_inr: float = -78.0,
    strike: float = 76300.0,
    best_points: float = 42.0,
) -> MagicMock:
    t = MagicMock()
    t.id = f"loss-{symbol}-{side.value}"
    t.symbol = symbol
    t.side = side
    t.strike = strike
    t.strategyType = "EXPLOSIVE"
    t.exitReason = "explosion_stage_trail"
    t.pnlInr = pnl_inr
    t.bestPnlPoints = best_points
    t.closedAt = datetime.now(IST) - timedelta(minutes=minutes_ago)
    t.entryContext = {"selectionMode": "explosion"}
    return t


def _settings_mock(**overrides):
    s = MagicMock()
    s.session_same_side_loss_reentry_enabled = True
    s.session_same_side_loss_reentry_cooldown_seconds = 900
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@patch("app.engines.session_mode_feedback.get_settings")
def test_blocks_cross_symbol_pe_after_sensex_loss(mock_settings):
    """Sep 2: SENSEX PE loss → NIFTY PE within 15m must block."""
    mock_settings.return_value = _settings_mock()
    state = AutoTraderState()
    state.closedPaperTrades = [_closed_loss(symbol="SENSEX", side=Side.PUT, minutes_ago=6.0)]
    blocked, meta = session_same_side_loss_reentry_blocked(
        state, symbol="NIFTY", side=Side.PUT,
    )
    assert blocked is True
    assert meta["reason"] == "session_same_side_loss_reentry_cooldown"
    assert meta["crossSymbol"] is True
    assert meta["priorSymbol"] == "SENSEX"


@patch("app.engines.session_mode_feedback.get_settings")
def test_blocks_cross_symbol_ce_after_call_loss(mock_settings):
    mock_settings.return_value = _settings_mock()
    state = AutoTraderState()
    state.closedPaperTrades = [
        _closed_loss(symbol="NIFTY", side=Side.CALL, minutes_ago=5.0, strike=23950.0, pnl_inr=-500.0),
    ]
    blocked, meta = session_same_side_loss_reentry_blocked(
        state, symbol="SENSEX", side=Side.CALL,
    )
    assert blocked is True
    assert meta["crossSymbol"] is True


@patch("app.engines.session_mode_feedback.get_settings")
def test_allows_opposite_side_after_loss(mock_settings):
    mock_settings.return_value = _settings_mock()
    state = AutoTraderState()
    state.closedPaperTrades = [_closed_loss(side=Side.PUT, minutes_ago=5.0)]
    blocked, meta = session_same_side_loss_reentry_blocked(
        state, symbol="NIFTY", side=Side.CALL,
    )
    assert blocked is False
    assert meta.get("applied") is False


@patch("app.engines.session_mode_feedback.get_settings")
def test_allows_same_side_after_cooldown_expires(mock_settings):
    mock_settings.return_value = _settings_mock()
    state = AutoTraderState()
    state.closedPaperTrades = [_closed_loss(minutes_ago=20.0)]
    blocked, meta = session_same_side_loss_reentry_blocked(
        state, symbol="NIFTY", side=Side.PUT,
    )
    assert blocked is False
    assert meta.get("applied") is False


@patch("app.engines.session_mode_feedback.get_settings")
def test_allows_same_side_after_green_close(mock_settings):
    mock_settings.return_value = _settings_mock()
    state = AutoTraderState()
    prior = _closed_loss(minutes_ago=5.0)
    prior.pnlInr = 1200.0
    state.closedPaperTrades = [prior]
    blocked, meta = session_same_side_loss_reentry_blocked(
        state, symbol="NIFTY", side=Side.PUT,
    )
    assert blocked is False


@patch("app.engines.session_mode_feedback.get_settings")
def test_same_symbol_same_side_within_cooldown(mock_settings):
    mock_settings.return_value = _settings_mock()
    state = AutoTraderState()
    state.closedPaperTrades = [_closed_loss(symbol="NIFTY", strike=24250.0, minutes_ago=8.0)]
    blocked, meta = session_same_side_loss_reentry_blocked(
        state, symbol="NIFTY", side=Side.PUT,
    )
    assert blocked is True
    assert meta["crossSymbol"] is False
