"""Live-only exit/entry efficiency — velocity units, slow-bleed keep, near-strike block."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.explosion_profit import (
    ExplosionExitParams,
    evaluate_explosion_exit,
    peak_velocity_reversal_keep_reason,
    premium_velocity_pct_to_points,
)
from app.engines.session_mode_feedback import session_near_strike_loss_reentry_blocked
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def test_premium_velocity_pct_to_points():
    assert premium_velocity_pct_to_points(-2.0, 150.0) == pytest.approx(-3.0)
    assert premium_velocity_pct_to_points(-10.0, 100.0) == pytest.approx(-10.0)


def _settings(**overrides):
    s = MagicMock()
    s.peak_velocity_reversal_keep_enabled = True
    s.peak_velocity_reversal_min_best_points = 8.0
    s.peak_velocity_reversal_keep_ratio = 0.75
    s.peak_velocity_reversal_min_velocity_3s = 2.0
    s.peak_velocity_reversal_min_giveback_points = 2.0
    s.peak_velocity_reversal_skip_hot_velocity_3s = 2.0
    s.peak_velocity_reversal_slow_bleed_enabled = True
    s.peak_velocity_reversal_slow_bleed_min_giveback_points = 5.0
    s.peak_keep_block_adaptive_stop_defer = True
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@patch("app.engines.explosion_profit.get_settings")
def test_slow_bleed_keep_without_fast_velocity(mock_settings):
    """Sep08 23800: +16 peak fading to +11 with flat v3 — still books at 75% floor."""
    mock_settings.return_value = _settings()
    trade = PaperTrade(
        id="t1",
        symbol="NIFTY",
        side=Side.PUT,
        strike=23800.0,
        entryPremium=150.8,
        lots=18,
        openedAt=datetime.now(tz=IST),
        strategyType=StrategyType.EXPLOSIVE,
        entryContext={"maxProfitCapture": True},
    )
    reason = peak_velocity_reversal_keep_reason(
        trade, best=16.0, pnl_pts=11.0, live_velocity_3s=-0.5,
    )
    assert reason == "explosion_peak_velocity_reversal_keep"


@patch("app.engines.explosion_profit.get_settings")
def test_slow_bleed_requires_min_giveback(mock_settings):
    mock_settings.return_value = _settings()
    trade = PaperTrade(
        id="t2",
        symbol="NIFTY",
        side=Side.PUT,
        strike=23800.0,
        entryPremium=150.8,
        lots=18,
        openedAt=datetime.now(tz=IST),
        strategyType=StrategyType.EXPLOSIVE,
    )
    reason = peak_velocity_reversal_keep_reason(
        trade, best=16.0, pnl_pts=14.0, live_velocity_3s=-0.5,
    )
    assert reason is None


@patch("app.engines.session_mode_feedback.get_settings")
def test_near_strike_block_after_loss(mock_settings):
    mock_settings.return_value = MagicMock(
        session_near_strike_loss_reentry_enabled=True,
        session_near_strike_loss_reentry_min_loss_inr=500.0,
        session_near_strike_loss_reentry_max_steps=3,
    )
    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id="loss1",
            symbol="NIFTY",
            side=Side.PUT,
            strike=23650.0,
            entryPremium=33.0,
            lots=6,
            pnlInr=-2704.0,
            openedAt=datetime.now(tz=IST),
            closedAt=datetime.now(tz=IST),
            exitReason="adaptive_stop_loss",
            strategyType=StrategyType.EXPLOSIVE,
            entryContext={"selectionMode": "explosion"},
        )
    ]
    blocked, meta = session_near_strike_loss_reentry_blocked(
        state, symbol="NIFTY", side=Side.PUT, strike=23800.0,
    )
    assert blocked is True
    assert meta["reason"] == "session_near_strike_loss_reentry_blocked"
    assert meta["priorStrike"] == 23650.0


@patch("app.engines.session_mode_feedback.get_settings")
def test_near_strike_allows_far_strike(mock_settings):
    mock_settings.return_value = MagicMock(
        session_near_strike_loss_reentry_enabled=True,
        session_near_strike_loss_reentry_min_loss_inr=500.0,
        session_near_strike_loss_reentry_max_steps=3,
    )
    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id="loss1",
            symbol="NIFTY",
            side=Side.PUT,
            strike=23650.0,
            entryPremium=33.0,
            lots=6,
            pnlInr=-2704.0,
            openedAt=datetime.now(tz=IST),
            closedAt=datetime.now(tz=IST),
            exitReason="adaptive_stop_loss",
            strategyType=StrategyType.EXPLOSIVE,
            entryContext={"selectionMode": "explosion"},
        )
    ]
    blocked, _ = session_near_strike_loss_reentry_blocked(
        state, symbol="NIFTY", side=Side.PUT, strike=24000.0,
    )
    assert blocked is False


@patch("app.engines.session_mode_feedback.get_settings")
def test_near_strike_ce_symmetric(mock_settings):
    mock_settings.return_value = MagicMock(
        session_near_strike_loss_reentry_enabled=True,
        session_near_strike_loss_reentry_min_loss_inr=500.0,
        session_near_strike_loss_reentry_max_steps=3,
    )
    state = AutoTraderState()
    state.closedPaperTrades = [
        PaperTrade(
            id="loss-ce",
            symbol="NIFTY",
            side=Side.CALL,
            strike=24000.0,
            entryPremium=80.0,
            lots=6,
            pnlInr=-1200.0,
            openedAt=datetime.now(tz=IST),
            closedAt=datetime.now(tz=IST),
            exitReason="adaptive_stop_loss",
            strategyType=StrategyType.EXPLOSIVE,
            entryContext={"selectionMode": "explosion"},
        )
    ]
    blocked, meta = session_near_strike_loss_reentry_blocked(
        state, symbol="NIFTY", side=Side.CALL, strike=24050.0,
    )
    assert blocked is True
    assert meta["priorStrike"] == 24000.0
