"""Block same-side re-entry after peak-fade loss (Sep 2 SENSEX PE pattern)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.session_mode_feedback import peak_fade_same_side_reentry_blocked
from app.models.schemas import AutoTraderState, Side

IST = ZoneInfo("Asia/Kolkata")


def _closed_peak_fade(
    *,
    side: Side = Side.PUT,
    minutes_ago: float = 3.0,
    best_points: float = 42.0,
    pnl_inr: float = -78.0,
    strike: float = 81200.0,
) -> MagicMock:
    t = MagicMock()
    t.id = f"peak-fade-{side.value}"
    t.symbol = "SENSEX"
    t.side = side
    t.strike = strike
    t.strategyType = "EXPLOSIVE"
    t.exitReason = "trailing_stop"
    t.pnlInr = pnl_inr
    t.bestPnlPoints = best_points
    t.closedAt = datetime.now(IST) - timedelta(minutes=minutes_ago)
    t.openedAt = t.closedAt - timedelta(minutes=8)
    t.entryContext = {"selectionMode": "explosion"}
    return t


def _settings_mock(**overrides):
    s = MagicMock()
    s.peak_fade_same_side_reentry_enabled = True
    s.peak_fade_same_side_reentry_min_peak_points = 30.0
    s.peak_fade_same_side_reentry_cooldown_seconds = 900
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@patch("app.engines.session_mode_feedback.get_settings")
def test_peak_fade_blocks_same_side_pe_reentry(mock_settings):
    mock_settings.return_value = _settings_mock()
    state = AutoTraderState()
    state.closedPaperTrades = [_closed_peak_fade(side=Side.PUT, minutes_ago=3.0)]
    blocked, meta = peak_fade_same_side_reentry_blocked(
        state, symbol="SENSEX", side=Side.PUT,
    )
    assert blocked is True
    assert meta["reason"] == "peak_fade_same_side_reentry_cooldown"
    assert meta["priorBestPoints"] == 42.0


@patch("app.engines.session_mode_feedback.get_settings")
def test_peak_fade_blocks_same_side_ce_reentry(mock_settings):
    mock_settings.return_value = _settings_mock()
    state = AutoTraderState()
    state.closedPaperTrades = [
        _closed_peak_fade(side=Side.CALL, minutes_ago=5.0, strike=81500.0),
    ]
    blocked, meta = peak_fade_same_side_reentry_blocked(
        state, symbol="SENSEX", side=Side.CALL,
    )
    assert blocked is True
    assert meta["reason"] == "peak_fade_same_side_reentry_cooldown"


@patch("app.engines.session_mode_feedback.get_settings")
def test_peak_fade_allows_opposite_side(mock_settings):
    mock_settings.return_value = _settings_mock()
    state = AutoTraderState()
    state.closedPaperTrades = [_closed_peak_fade(side=Side.PUT, minutes_ago=3.0)]
    blocked, meta = peak_fade_same_side_reentry_blocked(
        state, symbol="SENSEX", side=Side.CALL,
    )
    assert blocked is False
    assert meta.get("applied") is False


@patch("app.engines.session_mode_feedback.get_settings")
def test_peak_fade_allows_different_strike_same_side_still_blocked(mock_settings):
    """Sep 2: PE loss on one strike should block another PE on same symbol."""
    mock_settings.return_value = _settings_mock()
    state = AutoTraderState()
    state.closedPaperTrades = [_closed_peak_fade(side=Side.PUT, strike=81200.0)]
    blocked, _ = peak_fade_same_side_reentry_blocked(
        state, symbol="SENSEX", side=Side.PUT,
    )
    assert blocked is True


@patch("app.engines.session_mode_feedback.get_settings")
def test_peak_fade_cooldown_expires(mock_settings):
    mock_settings.return_value = _settings_mock()
    state = AutoTraderState()
    state.closedPaperTrades = [_closed_peak_fade(side=Side.PUT, minutes_ago=20.0)]
    blocked, meta = peak_fade_same_side_reentry_blocked(
        state, symbol="SENSEX", side=Side.PUT,
    )
    assert blocked is False
    assert meta.get("applied") is False


@patch("app.engines.session_mode_feedback.get_settings")
def test_peak_fade_small_peak_allows_reentry(mock_settings):
    mock_settings.return_value = _settings_mock()
    state = AutoTraderState()
    state.closedPaperTrades = [
        _closed_peak_fade(side=Side.PUT, best_points=12.0, pnl_inr=-25.0),
    ]
    blocked, meta = peak_fade_same_side_reentry_blocked(
        state, symbol="SENSEX", side=Side.PUT,
    )
    assert blocked is False
    assert meta.get("applied") is False


@patch("app.engines.session_mode_feedback.get_settings")
def test_peak_fade_green_close_allows_reentry(mock_settings):
    mock_settings.return_value = _settings_mock()
    state = AutoTraderState()
    state.closedPaperTrades = [
        _closed_peak_fade(side=Side.PUT, best_points=45.0, pnl_inr=1200.0),
    ]
    blocked, meta = peak_fade_same_side_reentry_blocked(
        state, symbol="SENSEX", side=Side.PUT,
    )
    assert blocked is False
    assert meta.get("applied") is False
