"""Parameter-dependent structural guards — enable flags and thresholds."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.explosion_entry_guards import (
    _regime_chopish,
    deep_itm_near_strike_substitute_blocked,
)
from app.engines.session_mode_feedback import session_same_strike_loss_reentry_blocked
from app.engines.structural_guard_settings import structural_guard_summary
from app.models.schemas import AutoTraderState, MarketPhase, PaperTrade, Regime, Side, SpotChart, StrategyType, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    defaults = {
        "session_same_strike_loss_reentry_enabled": True,
        "session_same_strike_loss_reentry_min_loss_inr": 500.0,
        "session_same_strike_loss_reentry_cooldown_seconds": 0,
        "explosion_deep_itm_substitute_block_enabled": True,
        "explosion_deep_itm_block_atm_radar_advantage_enabled": True,
        "explosion_deep_itm_block_atm_min_score_advantage": 20.0,
        "explosion_deep_itm_block_max_itm_steps_when_atm_on_radar": 1,
        "explosion_deep_itm_substitute_min_itm_steps": 1,
        "explosion_deep_itm_substitute_near_strike_max_steps": 2,
        "chopish_regime_detection_enabled": True,
        "chopish_regime_mom5_max_pct": 0.25,
        "chopish_regime_strength_max": 45.0,
        "chop_live_block_armed_base_launch": True,
        "chop_live_armed_base_max_local_pad_pct": 20.0,
        "armed_base_shallow_min_session_move_pct": 28.0,
        "fake_explosion_trap_block_chop_elite_armed_base": True,
        "fake_explosion_trap_min_session_move_pct": 28.0,
        "fake_explosion_trap_chop_elite_lot_cap": 6,
        "explosion_instrument_loss_cooldown_enabled": True,
        "explosion_instrument_loss_cooldown_seconds": 14400,
        "peak_velocity_reversal_keep_enabled": True,
        "peak_velocity_reversal_keep_ratio": 0.75,
        "peak_velocity_reversal_min_best_points": 8.0,
        "peak_velocity_reversal_min_velocity_3s": 2.0,
        "chopish_midday_union_enabled": True,
    }
    for k, v in defaults.items():
        setattr(s, k, v)
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _snap(*, atm: float = 23650.0, alerts: list | None = None) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        spot=atm - 20.0,
        atmStrike=atm,
        dataAvailable=True,
        spotChart=SpotChart(direction="BEARISH", momentum5Pct=0.1, trendStrength=30.0),
        explosionAlerts=alerts or [],
    )


@patch("app.engines.session_mode_feedback.get_settings")
def test_same_strike_respects_min_loss_inr(mock_settings):
    mock_settings.return_value = _settings(session_same_strike_loss_reentry_min_loss_inr=3000.0)
    state = AutoTraderState(
        closedPaperTrades=[
            PaperTrade(
                id="1",
                symbol="NIFTY",
                side=Side.PUT,
                strike=23650.0,
                entryPremium=33.0,
                currentPremium=30.0,
                lots=6,
                strategyType=StrategyType.EXPLOSIVE,
                openedAt=datetime.now(IST),
                closedAt=datetime.now(IST),
                pnlInr=-400.0,
                exitReason="adaptive_stop_loss",
                entryContext={"selectionMode": "explosion"},
            )
        ]
    )
    blocked, _ = session_same_strike_loss_reentry_blocked(
        state, symbol="NIFTY", side=Side.PUT, strike=23650.0,
    )
    assert blocked is False


@patch("app.engines.session_mode_feedback.get_settings")
def test_same_strike_disabled_via_flag(mock_settings):
    mock_settings.return_value = _settings(session_same_strike_loss_reentry_enabled=False)
    state = AutoTraderState(
        closedPaperTrades=[
            PaperTrade(
                id="1",
                symbol="NIFTY",
                side=Side.PUT,
                strike=23650.0,
                entryPremium=33.0,
                currentPremium=27.0,
                lots=6,
                strategyType=StrategyType.EXPLOSIVE,
                openedAt=datetime.now(IST),
                closedAt=datetime.now(IST),
                pnlInr=-2704.0,
                exitReason="adaptive_stop_loss",
                entryContext={"selectionMode": "explosion"},
            )
        ]
    )
    blocked, _ = session_same_strike_loss_reentry_blocked(
        state, symbol="NIFTY", side=Side.PUT, strike=23650.0,
    )
    assert blocked is False


def test_deep_itm_blocked_when_atm_radar_scores_higher():
    s = _settings()
    snap = _snap(
        alerts=[
            {"side": "PUT", "strike": 23650.0, "score": 90.2, "tier": "EXPLODING"},
            {"side": "PUT", "strike": 23800.0, "score": 50.0, "tier": "BUILDING"},
        ]
    )
    blocked, reason = deep_itm_near_strike_substitute_blocked(
        Side.PUT, 23800.0, snap, settings=s, candidate_score=50.0,
    )
    assert blocked is True
    assert reason == "explosion_deep_itm_atm_radar_advantage"


def test_deep_itm_atm_advantage_disabled_via_flag():
    s = _settings(explosion_deep_itm_block_atm_radar_advantage_enabled=False)
    snap = _snap(
        alerts=[
            {"side": "PUT", "strike": 23650.0, "score": 90.2},
            {"side": "PUT", "strike": 23800.0, "score": 50.0},
        ]
    )
    blocked, _ = deep_itm_near_strike_substitute_blocked(
        Side.PUT, 23800.0, snap, settings=s, candidate_score=50.0,
    )
    assert blocked is False


def test_regime_chopish_respects_thresholds():
    s = _settings(chopish_regime_mom5_max_pct=0.05)
    snap = _snap().model_copy(update={"regime": Regime.TREND_EXPANSION})
    assert _regime_chopish(snap, settings=s) is False


def test_structural_guard_summary_keys():
    summary = structural_guard_summary(_settings())
    assert "peakVelocityReversalKeep" in summary
    assert summary["sessionSameStrikeLossReentry"]["minLossInr"] == 500.0
