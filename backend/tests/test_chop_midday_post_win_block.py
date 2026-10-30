"""Midday chop + post-win + different strike — block explosion ladder; waive sudden lift."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.chop_day_guards import (
    chop_midday_post_win_different_strike_explosion_blocked,
)
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _closed_win_trade(*, strike: float = 22950.0, pnl: float = 16000.0):
    return SimpleNamespace(
        status="CLOSED",
        symbol="NIFTY",
        side="CALL",
        strike=strike,
        pnl_inr=pnl,
        exit_reason="explosion_profit_ladder_peak_keep",
        closedAt=datetime(2026, 10, 30, 9, 35, tzinfo=IST),
    )


def _candidate(*, strike: float = 23150.0, velocity_3s: float = 0.87):
    return SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side="CALL",
        strike=strike,
        premium=94.0,
        velocity_3s=velocity_3s,
        explosion_event={"localBaseMovePct": 5.4},
        alert={
            "momentType": "stealth_cvd_coil",
            "ictBaseReadinessReason": "stealth_cvd_coil_ready",
        },
    )


def _snap():
    return MagicMock()


@patch("app.engines.session_timing.in_midday_chop_window", return_value=True)
@patch("app.engines.pretrade_validator.collect_session_trades")
@patch("app.engines.explosion_entry_guards._post_session_win")
def test_blocks_oct30_style_coil_ladder(
    mock_post_win, mock_trades, _mock_chop_window,
):
    mock_post_win.return_value = (True, {"lastPnlInr": 16387.0, "postSessionWin": True})
    mock_trades.return_value = [_closed_win_trade()]
    settings = settings_mock()
    settings.chop_midday_post_win_different_strike_block_enabled = True

    with patch("app.config.get_settings", return_value=settings), patch(
        "app.engines.chop_day_guards.get_settings", return_value=settings,
    ), patch(
        "app.engines.session_mode_feedback.adjacent_strike_post_peak_keep_continuation",
        return_value=(False, {"reason": "no_parent_win"}),
    ), patch(
        "app.engines.session_mode_feedback.same_strike_post_win_fresh_base_reentry",
        return_value=(False, {"reason": "no_same_strike_win"}),
    ), patch(
        "app.engines.explosion_entry_guards.fresh_near_local_base",
        return_value=(True, {"freshNearLocalBase": True}),
    ):
        blocked, reason, meta = chop_midday_post_win_different_strike_explosion_blocked(
            _candidate(strike=23150.0),
            _snap(),
            state=MagicMock(),
            ict=SimpleNamespace(first_lift=False),
            settings=settings,
        )

    assert blocked is True
    assert reason == "chop_midday_post_win_explosion_ladder"
    assert meta.get("winStrike") == 22950.0
    assert meta.get("candidateStrike") == 23150.0


@patch("app.engines.session_timing.in_midday_chop_window", return_value=True)
@patch("app.engines.pretrade_validator.collect_session_trades")
@patch("app.engines.explosion_entry_guards._post_session_win")
def test_waives_fresh_v_rip_sudden_lift(
    mock_post_win, mock_trades, _mock_chop_window,
):
    mock_post_win.return_value = (True, {"lastPnlInr": 16387.0})
    mock_trades.return_value = [_closed_win_trade()]
    settings = settings_mock()

    cand = _candidate(strike=23000.0, velocity_3s=0.9)
    cand.alert = {
        "momentType": "v_rip_session_low",
        "readinessReason": "v_rip_ready",
    }
    cand.explosion_event = {"localBaseMovePct": 6.0}

    with patch("app.config.get_settings", return_value=settings), patch(
        "app.engines.chop_day_guards.get_settings", return_value=settings,
    ), patch(
        "app.engines.session_mode_feedback.adjacent_strike_post_peak_keep_continuation",
        return_value=(False, {}),
    ), patch(
        "app.engines.session_mode_feedback.same_strike_post_win_fresh_base_reentry",
        return_value=(False, {}),
    ), patch(
        "app.engines.explosion_entry_guards.fresh_near_local_base",
        return_value=(True, {}),
    ):
        blocked, reason, meta = chop_midday_post_win_different_strike_explosion_blocked(
            cand,
            _snap(),
            state=MagicMock(),
            ict=SimpleNamespace(first_lift=False),
            settings=settings,
        )

    assert blocked is False
    assert meta.get("waiver") == "v_rip_sudden_lift"


@patch("app.engines.session_timing.in_midday_chop_window", return_value=False)
@patch("app.engines.explosion_entry_guards._post_session_win")
def test_idle_outside_chop_window(mock_post_win, _mock_chop):
    mock_post_win.return_value = (True, {"lastPnlInr": 5000.0})
    settings = settings_mock()
    blocked, _, _ = chop_midday_post_win_different_strike_explosion_blocked(
        _candidate(),
        _snap(),
        state=MagicMock(),
        settings=settings,
    )
    assert blocked is False
