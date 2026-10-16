"""Top-signal session lift — close gaps that block ELITE / FTV / explosive trades."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.top_signal_session_lift import (
    candidate_qualifies_daily_cap_elite_bypass,
    candidate_qualifies_top_signal_session_lift,
    snapshots_have_top_signal_session_lift,
)
from app.models.schemas import AutoTraderState, Breadth, MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.top_signal_session_lift_enabled = True
    s.last_n_top_signal_bypass_enabled = True
    s.whipsaw_top_signal_bypass_enabled = True
    s.controlled_cap_top_signal_bypass_enabled = True
    s.controlled_trading_enabled = True
    s.last_n_trades_gate_enabled = True
    s.last_n_trades_min_count = 3
    s.last_n_trades_lookback = 5
    s.last_n_pause_after_losses = 4
    s.last_n_block_pf_below = 0.5
    s.last_n_block_net_inr_below = -5000.0
    s.whipsaw_guards_enabled = True
    s.flip_flop_lookback_trades = 6
    s.flip_flop_max_opposites = 3
    s.expiry_worst_day_elite_top_bypass_enabled = True
    s.expiry_worst_day_elite_top_bypasses_trade_cap = True
    s.worst_day_blocks_live = True
    s.enable_live_trading = True
    s.ftv_elite_top_only_enabled = True
    s.scalp_entries_enabled = False
    for key, value in overrides.items():
        setattr(s, key, value)
    return s


def _snap(**alert_overrides) -> SymbolSnapshot:
    alert = {
        "tier": "ELITE",
        "explosionScore": 88.0,
        "tradeable": True,
        "ictFirstLift": True,
        "ictArmedBaseLaunch": True,
        "localBaseMovePct": 21.0,
        "bullishLocalBaseActive": True,
        "side": "PUT",
        "symbol": "SENSEX",
        "strike": 77300,
    }
    alert.update(alert_overrides)
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime(2026, 8, 27, 12, 43, 41, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=77350.0,
        breadth=Breadth(bias="BEARISH", callPct=35.0, putPct=65.0),
        spotChart=SpotChart(candles=[]),
        explosionAlerts=[alert],
    )


def _candidate(**overrides):
    from app.models.schemas import StrategyType

    snap = _snap()
    base = SimpleNamespace(
        symbol="SENSEX",
        mode="explosion",
        side=Side.PUT,
        strike=77300.0,
        premium=83.95,
        score=88.0,
        tier="ELITE",
        strategy_type=StrategyType.EXPLOSIVE,
        snap=snap,
        alert=dict(snap.explosionAlerts[0]),
        explosion_event=SimpleNamespace(velocity_3s=2.5),
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


@patch("app.engines.top_signal_session_lift.get_settings")
def test_snapshots_have_top_signal_session_lift_bullish_pad(mock_settings):
    mock_settings.return_value = _settings()
    assert snapshots_have_top_signal_session_lift({"SENSEX": _snap()}) is True


@patch("app.engines.top_signal_session_lift.get_settings")
def test_snapshots_have_top_signal_session_lift_disabled(mock_settings):
    mock_settings.return_value = _settings(top_signal_session_lift_enabled=False)
    assert snapshots_have_top_signal_session_lift({"SENSEX": _snap()}) is False


@patch("app.engines.bullish_local_base.alert_is_bullish_local_base_pad_entry", return_value=True)
@patch("app.engines.top_signal_session_lift.get_settings")
def test_candidate_qualifies_bullish_pad(mock_lift, _mock_pad_entry):
    mock_lift.return_value = _settings()
    assert candidate_qualifies_top_signal_session_lift(_candidate()) is True
    assert candidate_qualifies_daily_cap_elite_bypass(_candidate()) is True


@patch("app.engines.bullish_local_base.alert_is_bullish_local_base_pad_entry", return_value=True)
@patch("app.engines.top_signal_session_lift.get_settings")
def test_worst_day_live_block_bypass_condition(mock_lift, _mock_pad_entry):
    """Mirror auto_trader live-block gate: top signals must not die at order time."""
    mock_lift.return_value = _settings()
    candidate = _candidate()
    snapshots = {"SENSEX": candidate.snap}
    live_blocked = True
    enable_live = True

    should_reject = live_blocked and enable_live and not (
        snapshots_have_top_signal_session_lift(snapshots)
        or candidate_qualifies_top_signal_session_lift(candidate)
    )
    assert should_reject is False


@patch("app.engines.pretrade_validator.get_settings")
@patch("app.engines.top_signal_session_lift.get_settings")
def test_last_n_pause_bypassed_with_top_signal(mock_lift, mock_pt):
    from app.engines.pretrade_validator import check_last_n_trades_pause
    from app.models.schemas import PaperTrade, StrategyType

    cfg = _settings()
    mock_lift.return_value = cfg
    mock_pt.return_value = cfg

    closed = [
        PaperTrade(
            id=f"t{i}",
            symbol="SENSEX",
            side=Side.PUT,
            strike=77300.0,
            entryPremium=80.0,
            currentPremium=70.0,
            lots=1,
            strategyType=StrategyType.EXPLOSIVE,
            openedAt=datetime.now(IST),
            closedAt=datetime.now(IST),
            pnlInr=-800.0,
        )
        for i in range(5)
    ]
    state = AutoTraderState(closedPaperTrades=closed)
    paused, reason, meta = check_last_n_trades_pause(state, {"SENSEX": _snap()})
    assert paused is False
    assert reason == "top_signal_session_lift_bypass"
    assert meta.get("topSignalSessionLiftBypass") is True


@patch("app.engines.whipsaw_guards.get_settings")
@patch("app.engines.top_signal_session_lift.get_settings")
def test_whipsaw_pause_bypassed_with_top_signal(mock_lift, mock_ws):
    from app.engines.whipsaw_guards import check_session_whipsaw_pause, trigger_whipsaw_pause

    cfg = _settings()
    mock_lift.return_value = cfg
    mock_ws.return_value = cfg

    trigger_whipsaw_pause(900, "flip_flop_churn")
    paused, reason, meta = check_session_whipsaw_pause(
        AutoTraderState(),
        {"SENSEX": _snap()},
    )
    assert paused is False
    assert reason == "top_signal_session_lift_bypass"
    assert meta.get("topSignalSessionLiftBypass") is True


@patch("app.engines.chop_day_guards.get_settings")
@patch("app.engines.top_signal_session_lift.get_settings")
def test_resolve_daily_trade_cap_lifts_for_top_ftv_pad(mock_lift, mock_chop):
    from app.engines.chop_day_guards import resolve_daily_trade_cap

    cfg = _settings()
    mock_lift.return_value = cfg
    mock_chop.return_value = cfg

    with patch(
        "app.engines.chop_day_guards.trades_cap_reached",
        return_value=(True, "daily_trade_cap_3>=3_expiry_worst"),
    ):
        blocked, reason, meta = resolve_daily_trade_cap(
            AutoTraderState(),
            {"SENSEX": _snap()},
        )
    assert blocked is False
    assert reason == "daily_trade_cap_elite_bypass"
    assert meta.get("dailyCapEliteOnly") is True


@patch("app.engines.pretrade_validator.get_settings")
@patch("app.engines.top_signal_session_lift.get_settings")
def test_resolve_controlled_cap_lifts_for_top_signal(mock_lift, mock_pt):
    from app.engines.pretrade_validator import resolve_controlled_daily_cap

    cfg = _settings(controlled_trading_enabled=True)
    mock_lift.return_value = cfg
    mock_pt.return_value = cfg

    with patch(
        "app.engines.pretrade_validator.resolve_effective_daily_trade_cap",
        return_value=(6, "controlled"),
    ), patch(
        "app.engines.pretrade_validator.collect_session_trades",
        return_value=[object()] * 6,
    ):
        blocked, reason, meta = resolve_controlled_daily_cap(
            AutoTraderState(),
            {"SENSEX": _snap()},
        )
    assert blocked is False
    assert reason == "controlled_cap_top_signal_bypass"
    assert meta.get("controlledCapEliteOnly") is True
