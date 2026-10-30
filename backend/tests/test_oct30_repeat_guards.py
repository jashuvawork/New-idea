"""Oct30 repeat guards — all-day post-win ladder, premium blowout, duplicate open leg."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.chop_day_guards import post_win_different_strike_explosion_blocked
from app.engines.session_mode_feedback import (
    open_duplicate_leg_blocked,
    same_strike_post_win_premium_blowout_blocked,
)
from app.models.schemas import PaperTrade, Side, StrategyType
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _win_trade(*, strike: float = 22950.0, entry: float = 94.0, pnl: float = 16000.0):
    return SimpleNamespace(
        id="win1",
        status="CLOSED",
        symbol="NIFTY",
        side="CALL",
        strike=strike,
        entryPremium=entry,
        pnlInr=pnl,
        pnl_inr=pnl,
        exit_reason="explosion_profit_ladder_peak_keep",
        closedAt=datetime.now(IST),
        entryContext={"selectionMode": "explosion"},
        strategyType="EXPLOSIVE",
    )


def _candidate(*, strike: float = 23150.0):
    return SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side="CALL",
        strike=strike,
        premium=120.0,
        velocity_3s=0.4,
        explosion_event={"localBaseMovePct": 8.0},
        alert={"momentType": "stealth_cvd_coil"},
    )


@patch("app.engines.chop_day_guards.get_settings")
@patch(
    "app.engines.explosion_entry_guards._post_session_win",
    return_value=(True, {"lastPnlInr": 16000.0}),
)
@patch(
    "app.engines.chop_day_guards._last_closed_same_side_win",
    return_value=(_win_trade(), {"lastWinStrike": 22950.0, "lastWinPnlInr": 16000.0}),
)
@patch("app.engines.session_timing.in_midday_chop_window", return_value=False)
@patch("app.engines.session_timing.in_regular_explosion_session_window", return_value=True)
@patch(
    "app.engines.session_mode_feedback.adjacent_strike_post_peak_keep_continuation",
    return_value=(False, {}),
)
@patch(
    "app.engines.session_mode_feedback.same_strike_post_win_fresh_base_reentry",
    return_value=(False, {}),
)
def test_all_day_post_win_blocks_different_strike_outside_midday(
    _fresh,
    _adj,
    _reg,
    _mid,
    _last_win,
    _post_win,
    mock_gs,
):
    mock_gs.return_value = settings_mock(
        session_post_win_different_strike_block_enabled=True,
        chop_midday_post_win_different_strike_block_enabled=True,
    )
    blocked, reason, _ = post_win_different_strike_explosion_blocked(
        _candidate(strike=23150.0),
        MagicMock(),
        SimpleNamespace(closedPaperTrades=[_win_trade()]),
    )
    assert blocked is True
    assert reason == "post_win_different_strike_explosion_ladder"


@patch("app.engines.session_mode_feedback.get_settings")
def test_same_strike_premium_blowout_blocks_expensive_reentry(mock_gs):
    mock_gs.return_value = settings_mock(
        same_strike_post_win_premium_blowout_block_enabled=True,
        same_strike_post_win_max_premium_above_win_entry_pct=28.0,
        same_strike_post_win_premium_blowout_min_velocity_3s=2.5,
    )
    state = SimpleNamespace(closedPaperTrades=[_win_trade(strike=22950.0, entry=94.0)])
    blocked, reason, meta = same_strike_post_win_premium_blowout_blocked(
        state,
        symbol="NIFTY",
        side=Side.CALL,
        strike=22950.0,
        premium=168.0,
        velocity_3s=0.5,
    )
    assert blocked is True
    assert reason == "same_strike_post_win_premium_blowout"
    assert meta["priorWinEntryPremium"] == 94.0


@patch("app.engines.session_mode_feedback.get_settings")
def test_same_strike_premium_blowout_waives_hot_velocity(mock_gs):
    mock_gs.return_value = settings_mock(
        same_strike_post_win_premium_blowout_block_enabled=True,
        same_strike_post_win_max_premium_above_win_entry_pct=28.0,
        same_strike_post_win_premium_blowout_min_velocity_3s=2.5,
    )
    state = SimpleNamespace(closedPaperTrades=[_win_trade(strike=22950.0, entry=94.0)])
    blocked, _, _ = same_strike_post_win_premium_blowout_blocked(
        state,
        symbol="NIFTY",
        side=Side.CALL,
        strike=22950.0,
        premium=168.0,
        velocity_3s=3.0,
    )
    assert blocked is False


def test_open_duplicate_leg_blocked():
    open_trade = PaperTrade(
        id="o1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=23050.0,
        entryPremium=110.0,
        lots=25,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
    )
    state = SimpleNamespace(openPaperTrades=[open_trade])
    with patch(
        "app.engines.session_mode_feedback.get_settings",
        return_value=settings_mock(block_duplicate_open_leg=True),
    ):
        blocked, reason, _ = open_duplicate_leg_blocked(
            state, symbol="NIFTY", side=Side.CALL, strike=23050.0,
        )
    assert blocked is True
    assert reason == "same_leg_already_open"
