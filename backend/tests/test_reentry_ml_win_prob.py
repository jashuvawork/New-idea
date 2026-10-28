"""ML win-probability gate for explosion re-entries (Aug28 24050)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.session_mode_feedback import reentry_ml_win_prob_blocked
from app.models.schemas import AutoTraderState, Side

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = MagicMock()
    s.explosion_reentry_ml_win_prob_gate_enabled = True
    s.explosion_reentry_ml_win_prob_min = 0.52
    s.explosion_reentry_ml_win_prob_same_strike_min = 0.55
    return s


def _closed(
    *,
    trade_id: str = "prior-1",
    strike: float = 24200.0,
    pnl_inr: float = 2346.0,
    exit_reason: str = "explosion_stage_trail",
    minutes_ago: float = 30.0,
) -> MagicMock:
    t = MagicMock()
    t.id = trade_id
    t.symbol = "NIFTY"
    t.side = Side.PUT
    t.strike = strike
    t.strategyType = "EXPLOSIVE"
    t.exitReason = exit_reason
    t.pnlInr = pnl_inr
    t.bestPnlPoints = 0.0
    t.closedAt = datetime.now(IST) - timedelta(minutes=minutes_ago)
    t.openedAt = t.closedAt - timedelta(minutes=20)
    t.entryContext = {"selectionMode": "explosion"}
    return t


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
@patch("app.engines.session_mode_feedback.get_settings")
def test_first_entry_not_gated(mock_settings, mock_ml):
    mock_settings.return_value = _settings()
    mock_ml.return_value = 0.41
    state = AutoTraderState()
    state.closedPaperTrades = []
    snap = MagicMock()
    blocked, meta = reentry_ml_win_prob_blocked(
        state,
        symbol="NIFTY",
        side=Side.PUT,
        strike=24050.0,
        snap=snap,
        confidence=210.0,
    )
    assert blocked is False
    assert meta.get("applied") is False
    mock_ml.assert_not_called()


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
@patch("app.engines.session_mode_feedback.get_settings")
def test_post_win_session_reentry_blocks_low_ml(mock_settings, mock_ml):
    """Aug28 first 24050 — post 24200 win, ML 41% must block at 52% floor."""
    mock_settings.return_value = _settings()
    mock_ml.return_value = 0.411
    state = AutoTraderState()
    state.closedPaperTrades = [_closed(strike=24200.0, pnl_inr=2346.0)]
    snap = MagicMock()
    blocked, meta = reentry_ml_win_prob_blocked(
        state,
        symbol="NIFTY",
        side=Side.PUT,
        strike=24050.0,
        snap=snap,
        confidence=210.84,
    )
    assert blocked is True
    assert meta["reentryKind"] == "session"
    assert meta["mlWinProb"] == 0.411
    assert meta["requiredMlWinProb"] == 0.52
    assert meta["reason"] == "reentry_ml_win_prob_low"


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
@patch("app.engines.session_mode_feedback.get_settings")
def test_same_strike_reentry_uses_stricter_floor(mock_settings, mock_ml):
    """Aug28 second 24050 — same strike after loss, ML 43% blocked at 55%."""
    mock_settings.return_value = _settings()
    mock_ml.return_value = 0.434
    state = AutoTraderState()
    state.closedPaperTrades = [
        _closed(
            trade_id="ca829ece",
            strike=24050.0,
            pnl_inr=-3551.75,
            exit_reason="adaptive_stop_loss",
            minutes_ago=17.0,
        )
    ]
    snap = MagicMock()
    blocked, meta = reentry_ml_win_prob_blocked(
        state,
        symbol="NIFTY",
        side=Side.PUT,
        strike=24050.0,
        snap=snap,
        confidence=257.73,
    )
    assert blocked is True
    assert meta["reentryKind"] == "same_strike"
    assert meta["requiredMlWinProb"] == 0.55
    assert meta["priorExitReason"] == "adaptive_stop_loss"


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
@patch("app.engines.session_mode_feedback.get_settings")
def test_session_reentry_allows_high_ml(mock_settings, mock_ml):
    """Winners were ~56% ML — post-win re-entry at 56% passes session floor."""
    mock_settings.return_value = _settings()
    mock_ml.return_value = 0.556
    state = AutoTraderState()
    state.closedPaperTrades = [_closed(strike=24200.0, pnl_inr=2346.0)]
    snap = MagicMock()
    blocked, meta = reentry_ml_win_prob_blocked(
        state,
        symbol="NIFTY",
        side=Side.PUT,
        strike=24100.0,
        snap=snap,
        confidence=177.78,
    )
    assert blocked is False
    assert meta["reentryKind"] == "session"
    assert meta["mlWinProb"] == 0.556


@patch("app.engines.adaptive_exits.predict_entry_ml_win_prob")
@patch("app.engines.session_mode_feedback.get_settings")
def test_same_strike_reentry_allows_high_ml(mock_settings, mock_ml):
    mock_settings.return_value = _settings()
    mock_ml.return_value = 0.58
    state = AutoTraderState()
    state.closedPaperTrades = [
        _closed(
            strike=24050.0,
            pnl_inr=-3551.75,
            exit_reason="adaptive_stop_loss",
        )
    ]
    snap = MagicMock()
    blocked, meta = reentry_ml_win_prob_blocked(
        state,
        symbol="NIFTY",
        side=Side.PUT,
        strike=24050.0,
        snap=snap,
    )
    assert blocked is False
    assert meta["reentryKind"] == "same_strike"
