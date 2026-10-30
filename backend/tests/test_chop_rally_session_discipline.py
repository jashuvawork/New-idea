"""CHOP + RALLY session discipline — #676 bottom line (CE/PE symmetric)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.models.schemas import PaperTrade, Side, StrategyType
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _state(*, closed=None, open_trades=None):
    return SimpleNamespace(
        closedPaperTrades=closed or [],
        openPaperTrades=open_trades or [],
        dailyStrategy={"dayMode": "CHOP + RALLY"},
    )


def _closed_loss(*, strike=23150.0, symbol="NIFTY", side="CALL"):
    return SimpleNamespace(
        id="loss1",
        status="CLOSED",
        symbol=symbol,
        side=side,
        strike=strike,
        pnlInr=-32000.0,
        pnl_inr=-32000.0,
        closedAt=datetime(2026, 10, 30, 13, 22, tzinfo=IST),
        entryContext={"selectionMode": "explosion"},
        strategyType="EXPLOSIVE",
    )


def _closed_win(*, strike=22950.0, entry=94.0):
    return SimpleNamespace(
        id="win1",
        status="CLOSED",
        symbol="NIFTY",
        side="CALL",
        strike=strike,
        entryPremium=entry,
        pnlInr=16000.0,
        pnl_inr=16000.0,
        closedAt=datetime(2026, 10, 30, 9, 35, tzinfo=IST),
        entryContext={"selectionMode": "explosion"},
        strategyType="EXPLOSIVE",
    )


def _open_leg(*, strike=22950.0):
    return PaperTrade(
        id="open1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=strike,
        entryPremium=100.0,
        lots=25,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
    )


@patch("app.engines.chop_rally_session_discipline.get_settings")
@patch("app.engines.chop_rally_session_discipline.is_session_repeat_discipline_day", return_value=True)
def test_open_cap_blocks_second_ce_strike(_day, mock_gs):
    mock_gs.return_value = settings_mock(
        chop_rally_session_discipline_enabled=True,
        chop_rally_max_open_legs_per_symbol_side=1,
    )
    from app.engines.chop_rally_session_discipline import (
        chop_rally_symbol_side_open_cap_blocked,
    )

    state = _state(open_trades=[_open_leg(strike=22950.0)])
    blocked, reason, _ = chop_rally_symbol_side_open_cap_blocked(
        state, symbol="NIFTY", side=Side.CALL,
    )
    assert blocked is True
    assert reason == "session_one_open_leg_per_symbol_side"


@patch("app.engines.chop_rally_session_discipline.get_settings")
@patch("app.engines.chop_rally_session_discipline.is_session_repeat_discipline_day", return_value=True)
def test_same_strike_loss_no_restack(_day, mock_gs):
    mock_gs.return_value = settings_mock(
        chop_rally_block_same_strike_after_loss=True,
    )
    from app.engines.chop_rally_session_discipline import (
        chop_rally_same_strike_reentry_discipline_blocked,
    )

    state = _state(closed=[_closed_loss()])
    blocked, reason, _ = chop_rally_same_strike_reentry_discipline_blocked(
        state,
        symbol="NIFTY",
        side=Side.CALL,
        strike=23150.0,
        premium=80.0,
    )
    assert blocked is True
    assert reason == "session_same_strike_loss_no_restack"


@patch("app.engines.chop_rally_session_discipline.get_settings")
@patch("app.engines.chop_rally_session_discipline.is_session_repeat_discipline_day", return_value=True)
@patch(
    "app.engines.session_mode_feedback.same_strike_post_win_fresh_base_reentry",
    return_value=(False, {"reason": "no_fresh_base"}),
)
def test_same_strike_win_requires_fresh_base(_fresh, _day, mock_gs):
    mock_gs.return_value = settings_mock(
        chop_rally_same_strike_post_win_requires_fresh_base=True,
    )
    from app.engines.chop_rally_session_discipline import (
        chop_rally_same_strike_reentry_discipline_blocked,
    )

    state = _state(closed=[_closed_win()])
    blocked, reason, _ = chop_rally_same_strike_reentry_discipline_blocked(
        state,
        symbol="NIFTY",
        side=Side.CALL,
        strike=22950.0,
        premium=170.0,
    )
    assert blocked is True
    assert reason == "session_same_strike_requires_fresh_base"


@patch("app.engines.chop_rally_session_discipline.get_settings")
@patch("app.engines.chop_rally_session_discipline.is_session_repeat_discipline_day", return_value=True)
@patch(
    "app.engines.session_mode_feedback.same_strike_post_win_fresh_base_reentry",
    return_value=(True, {"reason": "fresh_base_reentry"}),
)
@patch(
    "app.engines.session_mode_feedback.same_strike_post_win_premium_blowout_blocked",
    return_value=(True, "same_strike_post_win_premium_blowout", {}),
)
def test_chop_rally_blowout_uses_22pct_pad(_blow, _fresh, _day, mock_gs):
    mock_gs.return_value = settings_mock(
        chop_rally_same_strike_post_win_max_premium_above_win_entry_pct=22.0,
    )
    from app.engines.chop_rally_session_discipline import (
        chop_rally_same_strike_reentry_discipline_blocked,
    )

    state = _state(closed=[_closed_win(entry=94.0)])
    blocked, reason, meta = chop_rally_same_strike_reentry_discipline_blocked(
        state,
        symbol="NIFTY",
        side=Side.CALL,
        strike=22950.0,
        premium=120.0,
    )
    assert blocked is True
    assert reason == "same_strike_post_win_premium_blowout"
    _blow.assert_called_once()
    assert _blow.call_args.kwargs["max_premium_above_win_entry_pct"] == 22.0


@patch("app.engines.chop_rally_session_discipline.is_session_repeat_discipline_day", return_value=False)
def test_inactive_off_chop_rally_day(_day):
    from app.engines.chop_rally_session_discipline import (
        chop_rally_symbol_side_open_cap_blocked,
    )

    state = _state(open_trades=[_open_leg(), _open_leg(strike=23050.0)])
    blocked, _, _ = chop_rally_symbol_side_open_cap_blocked(
        state, symbol="NIFTY", side=Side.CALL,
    )
    assert blocked is False


@patch("app.engines.chop_rally_session_discipline.get_settings")
def test_expiry_worst_excluded_from_default_modes(mock_gs):
    mock_gs.return_value = settings_mock()
    from app.engines.chop_rally_session_discipline import is_session_repeat_discipline_day

    state = SimpleNamespace(dailyStrategy={"dayMode": "EXPIRY WORST"})
    assert is_session_repeat_discipline_day(state, None) is False


@patch("app.engines.chop_rally_session_discipline.get_settings")
def test_bullish_day_in_default_modes(mock_gs):
    mock_gs.return_value = settings_mock()
    from app.engines.chop_rally_session_discipline import is_session_repeat_discipline_day

    state = SimpleNamespace(dailyStrategy={"dayMode": "BULLISH DAY"})
    assert is_session_repeat_discipline_day(state, None) is True


@patch("app.engines.chop_rally_session_discipline.get_settings")
@patch("app.engines.chop_rally_session_discipline.is_session_repeat_discipline_day", return_value=True)
def test_put_side_symmetric_open_cap(_day, mock_gs):
    mock_gs.return_value = settings_mock(chop_rally_max_open_legs_per_symbol_side=1)
    from app.engines.chop_rally_session_discipline import (
        chop_rally_symbol_side_open_cap_blocked,
    )

    open_put = PaperTrade(
        id="p1",
        symbol="NIFTY",
        side=Side.PUT,
        strike=23000.0,
        entryPremium=90.0,
        lots=25,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
    )
    state = _state(open_trades=[open_put])
    blocked, reason, _ = chop_rally_symbol_side_open_cap_blocked(
        state, symbol="NIFTY", side=Side.PUT,
    )
    assert blocked is True
    assert reason == "session_one_open_leg_per_symbol_side"
