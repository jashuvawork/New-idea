"""Live Oct 1 / Sep917 — v_rip pad-lane near-base fills under paper parity profile."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.engines.best_trade_policy import (
    best_trade_chop_deep_chase_blocked,
    call_atm_itm_base_capture_eligible,
    symmetric_best_trade_at_base_capture,
    symmetric_near_base_premium_fade_bypass,
    symmetric_new_base_moment_evidence,
    symmetric_structural_base_evidence,
)
from app.engines.winner_entry_guards import premium_fading_blocks_entry
from app.models.schemas import Side, SymbolSnapshot
from tests.mock_defaults import settings_mock


def _nifty_snap(*, spot: float = 22680.0, atm: float = 22700.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp="2026-10-07T09:20:00+05:30",
        marketPhase="LIVE_MARKET",
        spot=spot,
        atmStrike=atm,
        dataAvailable=True,
    )


def test_v_rip_session_low_counts_as_structural_base():
    s = settings_mock()
    alert = {
        "tier": "ELITE",
        "momentType": "v_rip_session_low",
        "ictBaseReadinessReason": "v_rip_session_low_ready",
        "localBaseMovePct": 8.5,
    }
    assert symmetric_structural_base_evidence(alert, settings=s) is True
    with patch(
        "app.engines.best_trade_policy.symmetric_best_trade_capture_active",
        return_value=True,
    ):
        assert symmetric_near_base_premium_fade_bypass(alert, settings=s) is True


def test_v_rip_atm_call_eligible_for_base_capture():
    s = settings_mock()
    snap = _nifty_snap()
    alert = {
        "tier": "ELITE",
        "momentType": "v_rip_session_low",
        "ictBaseReadinessReason": "v_rip_session_low_ready",
        "localBaseMovePct": 7.0,
        "setup": "V",
    }
    cand = SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22700.0,
        premium=122.0,
        alert=alert,
        pretrade_meta={},
        snap=snap,
    )
    ok, meta = call_atm_itm_base_capture_eligible(cand, snap, settings=s)
    assert ok is True
    assert meta["moneyness"] in ("ATM", "ITM")


def test_live_parity_waives_chop_deep_chase_for_v_rip_atm_base():
    s = settings_mock(
        live_paper_parity_enabled=True,
        live_trade_selection_parity_with_paper=True,
    )
    snap = _nifty_snap()
    alert = {
        "tier": "ELITE",
        "momentType": "v_rip_session_low",
        "ictBaseReadinessReason": "v_rip_session_low_ready",
        "localBaseMovePct": 9.0,
        "setup": "V",
    }
    cand = SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22700.0,
        premium=158.0,
        alert=alert,
        pretrade_meta={},
        snap=snap,
    )
    blocked, reason = best_trade_chop_deep_chase_blocked(
        cand,
        {"fakeExplosionTrap": True},
        {
            "dayMode": "CHOP DAY",
            "localBasePct": 9.0,
            "setup": "V",
            "eliteScore": 92.0,
        },
        day_mode="CHOP DAY",
        settings=s,
    )
    assert blocked is False
    assert reason == ""


def test_v_rip_counts_as_new_base_moment_token():
    s = settings_mock()
    ev = {
        "localBaseMovePct": 9.0,
        "momentType": "v_rip_session_low",
        "ictBaseReadinessReason": "v_rip_session_low_ready",
    }
    assert symmetric_new_base_moment_evidence(ev, settings=s) is True
    ok, reason = symmetric_best_trade_at_base_capture(ev, settings=s)
    assert ok is True


def test_v_rip_premium_fade_shallow_retest_ok():
    s = settings_mock()
    alert = {
        "tier": "ELITE",
        "momentType": "v_rip_session_low",
        "localBaseMovePct": 6.0,
    }
    with patch(
        "app.engines.best_trade_policy.symmetric_best_trade_capture_active",
        return_value=True,
    ):
        assert symmetric_near_base_premium_fade_bypass(alert, settings=s) is True
    blocked, reason = premium_fading_blocks_entry(
        premium_momentum_3s=-0.5,
        premium_momentum_5s=-0.4,
        explosion_event=type("E", (), {"tier": "ELITE", "daily_move_pct": 8.0})(),
        symmetric_near_base_bypass=True,
    )
    assert blocked is False
    assert reason == "symmetric_near_base_shallow_fade_ok"
