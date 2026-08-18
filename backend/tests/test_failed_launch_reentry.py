"""Block same-strike re-entry after explosion_failed_launch (Aug18 24250 PUT)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.session_mode_feedback import failed_launch_reentry_blocked
from app.models.schemas import AutoTraderState, Side

IST = ZoneInfo("Asia/Kolkata")


def _closed_failed(*, minutes_ago: float = 10.0) -> MagicMock:
    t = MagicMock()
    t.id = "fail-1"
    t.symbol = "NIFTY"
    t.side = Side.PUT
    t.strike = 24250.0
    t.strategyType = "EXPLOSIVE"
    t.exitReason = "explosion_failed_launch"
    t.pnlInr = -891.91
    t.bestPnlPoints = 0.0
    t.closedAt = datetime.now(IST) - timedelta(minutes=minutes_ago)
    t.openedAt = t.closedAt - timedelta(seconds=18)
    t.entryContext = {"selectionMode": "explosion", "ictArmedBaseLaunch": True}
    return t


@patch("app.engines.session_mode_feedback.get_settings")
def test_failed_launch_blocks_same_strike_reentry(mock_settings):
    s = MagicMock()
    s.explosion_failed_launch_reentry_block_enabled = True
    s.explosion_failed_launch_reentry_cooldown_seconds = 1800
    mock_settings.return_value = s
    state = AutoTraderState()
    state.closedPaperTrades = [_closed_failed(minutes_ago=21)]
    blocked, meta = failed_launch_reentry_blocked(
        state, symbol="NIFTY", side=Side.PUT, strike=24250.0,
    )
    assert blocked is True
    assert meta["reason"] == "failed_launch_reentry_cooldown"


@patch("app.engines.session_mode_feedback.get_settings")
def test_failed_launch_cooldown_expires(mock_settings):
    s = MagicMock()
    s.explosion_failed_launch_reentry_block_enabled = True
    s.explosion_failed_launch_reentry_cooldown_seconds = 1800
    mock_settings.return_value = s
    state = AutoTraderState()
    state.closedPaperTrades = [_closed_failed(minutes_ago=40)]
    blocked, meta = failed_launch_reentry_blocked(
        state, symbol="NIFTY", side=Side.PUT, strike=24250.0,
    )
    assert blocked is False
    assert meta.get("applied") is False
