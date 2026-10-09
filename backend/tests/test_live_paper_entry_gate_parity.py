"""Live ↔ paper entry gate parity — same allow/block at order boundary (CE + PE)."""

from __future__ import annotations

import pytest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.entry_timing import timing_blocks_entry
from app.engines.live_oct1_pad_entry_guard import (
    apply_oct1_pad_timing_block,
    live_oct1_pad_entry_blocked,
    live_oct1_pad_entry_order_gate,
)
from app.engines.live_paper_parity import entry_gates_match_paper
from app.models.schemas import MarketPhase, Side, SymbolSnapshot
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _paper_parity_settings(**kwargs):
    return settings_mock(
        live_paper_parity_enabled=True,
        live_trade_selection_parity_with_paper=True,
        enable_live_trading=False,
        auto_trading_enabled=True,
        october_frozen_profile_enabled=True,
        **kwargs,
    )


def _frozen_live_settings(**kwargs):
    defaults = dict(
        october_frozen_profile_enabled=True,
        enable_live_trading=True,
        auto_trading_enabled=True,
        live_paper_parity_enabled=False,
        live_trade_selection_parity_with_paper=False,
        sep917_legacy_profile_enabled=True,
        symmetric_best_trade_capture_enabled=True,
        best_trade_sep917_base_shape_align_enabled=True,
        best_trade_base_first_enabled=True,
    )
    defaults.update(kwargs)
    return settings_mock(**defaults)


def _frozen_live_parity_on(**kwargs):
    return _frozen_live_settings(
        live_paper_parity_enabled=True,
        live_trade_selection_parity_with_paper=True,
        **kwargs,
    )


def _snap(symbol: str = "NIFTY") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
    )


def _oct7_peak_ce_candidate() -> SimpleNamespace:
    alert = {
        "tier": "EXPLODING",
        "momentType": "armed_base_launch",
        "localBaseMovePct": 6.81,
        "premium": 158.11,
        "sessionLowPremium": 122.0,
        "sessionPeakPremium": 158.7,
        "side": "CALL",
        "velocity3s": 2.37,
        "velocity9s": 2.2,
        "armedBaseLaunch": True,
        "flatThenVertical": True,
        "activeBreakout": True,
        "vRipReady": True,
    }
    ev = SimpleNamespace(
        side=Side.CALL,
        strike=22700.0,
        tier="EXPLODING",
        explosion_score=68.4,
        velocity_3s=2.37,
        velocity_9s=2.2,
        daily_move_pct=5.35,
        peak_move_pct=5.35,
    )
    return SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22700.0,
        premium=158.11,
        alert=alert,
        pretrade_meta={},
        liveEntryScoreMeta={"drawdownFromHighPct": 0.0, "sessionRangePosition": 0.98},
        explosion_event=ev,
        snap=_snap(),
    )


def _oct7_pad_ce_candidate() -> SimpleNamespace:
    alert = {
        "tier": "ELITE",
        "momentType": "v_rip_session_low",
        "ictBaseReadinessReason": "v_rip_session_low_ready",
        "localBaseMovePct": 8.0,
        "premium": 122.0,
        "sessionLowPremium": 118.0,
        "sessionPeakPremium": 158.0,
        "side": "CALL",
    }
    return SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22700.0,
        premium=122.0,
        alert=alert,
        pretrade_meta={},
        liveEntryScoreMeta={"drawdownFromHighPct": -12.0, "sessionRangePosition": 0.35},
        snap=_snap(),
    )


def _oct7_peak_pe_candidate() -> SimpleNamespace:
    alert = {
        "tier": "EXPLODING",
        "momentType": "armed_base_launch",
        "localBaseMovePct": 7.0,
        "premium": 142.0,
        "sessionLowPremium": 95.0,
        "sessionPeakPremium": 142.5,
        "side": "PUT",
    }
    return SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.PUT,
        strike=22600.0,
        premium=142.0,
        alert=alert,
        pretrade_meta={},
        liveEntryScoreMeta={"drawdownFromHighPct": 0.0, "sessionRangePosition": 0.99},
        snap=_snap(),
    )


def _oct7_pad_pe_candidate() -> SimpleNamespace:
    alert = {
        "tier": "ELITE",
        "momentType": "v_rip_session_low",
        "ictBaseReadinessReason": "v_rip_session_low_ready",
        "localBaseMovePct": 8.5,
        "premium": 98.0,
        "sessionLowPremium": 88.0,
        "sessionPeakPremium": 142.0,
        "side": "PUT",
    }
    return SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.PUT,
        strike=22600.0,
        premium=98.0,
        alert=alert,
        pretrade_meta={},
        liveEntryScoreMeta={"drawdownFromHighPct": -14.0, "sessionRangePosition": 0.30},
        snap=_snap(),
    )


def _assert_peak_blocked(settings, cand):
    assert entry_gates_match_paper(settings) is True
    blocked, reason, _ = live_oct1_pad_entry_blocked(cand, _snap(), settings=settings)
    assert blocked is True
    assert reason in (
        "live_oct1_chase_at_session_high",
        "live_oct1_chase_session_range_high",
    )
    blocked_gate, gate_reason, _ = live_oct1_pad_entry_order_gate(cand, _snap(), settings=settings)
    assert blocked_gate is True
    timing = {"assessment": "GOOD", "action": "allow", "reasons": ["hot_v3"]}
    timing2 = apply_oct1_pad_timing_block(timing, cand, _snap(), settings=settings)
    assert timing2["action"] == "block"
    assert timing2["assessment"] == "CHASE"
    t_blocked, t_reason = timing_blocks_entry(timing2)
    assert t_blocked is True
    assert "live_oct1_chase" in t_reason


def _assert_pad_allowed(settings, cand):
    assert entry_gates_match_paper(settings) is True
    blocked, reason, _ = live_oct1_pad_entry_blocked(cand, _snap(), settings=settings)
    assert blocked is False
    assert reason == ""
    blocked_gate, gate_reason, _ = live_oct1_pad_entry_order_gate(cand, _snap(), settings=settings)
    assert blocked_gate is False
    assert gate_reason == ""


def test_entry_gates_match_paper_frozen_live_without_parity_flags():
    s = _frozen_live_settings()
    assert entry_gates_match_paper(s) is True


@pytest.mark.parametrize(
    "settings_factory",
    [_paper_parity_settings, _frozen_live_settings, _frozen_live_parity_on],
)
def test_oct7_peak_ce_blocked_all_parity_modes(settings_factory):
    _assert_peak_blocked(settings_factory(), _oct7_peak_ce_candidate())


@pytest.mark.parametrize(
    "settings_factory",
    [_paper_parity_settings, _frozen_live_settings, _frozen_live_parity_on],
)
def test_oct7_pad_ce_allowed_all_parity_modes(settings_factory):
    _assert_pad_allowed(settings_factory(), _oct7_pad_ce_candidate())


@pytest.mark.parametrize(
    "settings_factory",
    [_paper_parity_settings, _frozen_live_settings, _frozen_live_parity_on],
)
def test_oct7_peak_pe_blocked_symmetric(settings_factory):
    _assert_peak_blocked(settings_factory(), _oct7_peak_pe_candidate())


@pytest.mark.parametrize(
    "settings_factory",
    [_paper_parity_settings, _frozen_live_settings, _frozen_live_parity_on],
)
def test_oct7_pad_pe_allowed_symmetric(settings_factory):
    _assert_pad_allowed(settings_factory(), _oct7_pad_pe_candidate())


def _oct9_open_call_rip_at_option_high() -> SimpleNamespace:
    """Gap-up open: near-base shape but option premium already at its session high."""
    alert = {
        "tier": "ELITE",
        "momentType": "armed_base_launch",
        "localBaseMovePct": 12.0,
        "offLowMovePct": 15.0,
        "premium": 149.0,
        "sessionLowPremium": 60.0,
        "sessionPeakPremium": 170.0,
        "side": "CALL",
        "armedBaseLaunch": True,
        "firstLift": True,
        "explosionScore": 100.0,
        "moneyness": "ATM",
        "strikeStepsFromAtm": 1,
    }
    return SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22450.0,
        premium=149.0,
        alert=alert,
        pretrade_meta={},
        liveEntryScoreMeta={"drawdownFromHighPct": 0.0, "sessionRangePosition": 0.88},
        snap=_snap(),
    )


@patch("app.engines.session_timing.in_open_premium_window", return_value=True)
@pytest.mark.parametrize(
    "settings_factory",
    [_paper_parity_settings, _frozen_live_parity_on],
)
def test_oct9_open_call_rip_waives_option_session_high_block(_window, settings_factory):
    """Oct 9 NIFTY gap-up: do not treat fresh armed-base rip as Oct7 session-high chase."""
    _assert_pad_allowed(settings_factory(), _oct9_open_call_rip_at_option_high())
