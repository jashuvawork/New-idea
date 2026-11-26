"""Post-close CE/PE must form base before same-side rotation."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.session_mode_feedback import (
    _alert_premium_already_fading,
    side_post_close_wait_base_blocked,
)
from app.models.schemas import Side

_IST = ZoneInfo("Asia/Kolkata")


def _state_with_close(*, symbol="SENSEX", side=Side.CALL, strike=84000.0, minutes_ago=8.0):
    closed = datetime.now(_IST) - timedelta(minutes=minutes_ago)
    trade = SimpleNamespace(
        id="t1",
        symbol=symbol,
        side=side,
        strike=strike,
        pnlInr=1452.0,
        closedAt=closed,
        entryContext={"selectionMode": "explosion"},
        strategyType="EXPLOSIVE",
    )
    return SimpleNamespace(closedPaperTrades=[trade])


def test_fading_alert_blocks_immediately():
    assert _alert_premium_already_fading({"premiumMomentum3Pct": -0.5}, 2.0) is True
    assert _alert_premium_already_fading({"premiumMomentum3Pct": 1.0}, -0.1) is True


def test_side_post_close_blocks_without_base_history():
    settings = Settings()
    settings.side_post_close_wait_base_enabled = True
    state = _state_with_close()
    blocked, reason, meta = side_post_close_wait_base_blocked(
        state,
        symbol="SENSEX",
        side=Side.CALL,
        strike=83900.0,
        premium=442.0,
        velocity_3s=2.5,
        alert={"premiumMomentum3Pct": 7.0, "premiumMomentum5Pct": 10.0},
    )
    assert blocked is True
    assert reason == "side_post_close_wait_for_base"
    assert meta["secondsSincePriorClose"] < 900


def test_side_post_close_blocks_falling_tape():
    state = _state_with_close(minutes_ago=5.0)
    blocked, reason, _ = side_post_close_wait_base_blocked(
        state,
        symbol="SENSEX",
        side=Side.CALL,
        strike=83900.0,
        premium=420.0,
        velocity_3s=0.5,
        alert={"premiumMomentum3Pct": -1.2, "premiumMomentum5Pct": -0.4},
    )
    assert blocked is True
    assert reason == "side_post_close_falling_premium"