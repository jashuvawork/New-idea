"""Structural pad lane waives chop-live on replica — CE/PE symmetric; extended chase still on."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.engines.chop_live_guards import chop_live_entry_blocked
from app.models.schemas import AutoTraderState, Side
from tests.mock_defaults import settings_mock


def _replica_settings(**kwargs):
    return settings_mock(
        october_frozen_profile_enabled=True,
        oct_paper_replica_enabled=True,
        live_paper_parity_enabled=True,
        enable_live_trading=True,
        auto_trading_enabled=True,
        chop_live_guards_enabled=True,
        structural_pad_chop_live_waiver_enabled=True,
        **kwargs,
    )


def _candidate(side: str, alert: dict) -> SimpleNamespace:
    event = SimpleNamespace(
        side=Side.CALL if side == "CALL" else Side.PUT,
        tier="ELITE",
        explosion_score=float(alert.get("explosionScore", 100)),
        local_base_move_pct=float(alert.get("localBaseMovePct", 8)),
    )
    return SimpleNamespace(
        mode="explosion",
        side=Side.CALL if side == "CALL" else Side.PUT,
        symbol="NIFTY",
        tier="ELITE",
        explosion_event=event,
        alert=alert,
    )


@patch("app.engines.chop_live_guards.chop_live_guard_day_active", return_value=True)
@patch("app.engines.chop_live_guards._extended_chase_hard_block", return_value=(True, "chop_live_extended_chase"))
def test_structural_pad_waives_chop_before_extended_chase_ce(_ext, _day):
    s = _replica_settings()
    alert = {
        "side": "CALL",
        "tier": "ELITE",
        "momentType": "first_lift_local_base",
        "firstLift": True,
        "explosionScore": 100.0,
        "localBaseMovePct": 8.0,
        "offLowMovePct": 10.0,
        "sessionRangePosition": 0.35,
        "drawdownFromHighPct": -12.0,
        "moneyness": "ITM",
        "strikeStepsFromAtm": 1,
    }
    cand = _candidate("CALL", alert)
    snap = MagicMock()
    state = AutoTraderState()
    with patch("app.engines.chop_live_guards.get_settings", return_value=s):
        blocked, reason, meta = chop_live_entry_blocked(
            cand, snap, state, snapshots={"NIFTY": snap},
        )
    assert blocked is False
    assert (
        meta.get("chopLiveStructuralPadWaive")
        or meta.get("chopLiveNearBaseWaive")
        or meta.get("octPaperChopWireSkipped")
    )


@patch("app.engines.chop_live_guards.chop_live_guard_day_active", return_value=True)
@patch("app.engines.chop_live_guards._extended_chase_hard_block", return_value=(True, "chop_live_extended_chase"))
def test_structural_pad_waives_chop_before_extended_chase_pe(_ext, _day):
    s = _replica_settings()
    alert = {
        "side": "PUT",
        "tier": "ELITE",
        "momentType": "v_rip_session_high",
        "vRipReady": True,
        "explosionScore": 100.0,
        "localBaseMovePct": 10.0,
        "offHighMovePct": 6.0,
        "sessionRangePosition": 0.58,
        "drawdownFromHighPct": -14.0,
        "moneyness": "ITM",
        "strikeStepsFromAtm": 1,
    }
    cand = _candidate("PUT", alert)
    snap = MagicMock()
    state = AutoTraderState()
    with patch("app.engines.chop_live_guards.get_settings", return_value=s):
        blocked, reason, meta = chop_live_entry_blocked(
            cand, snap, state, snapshots={"NIFTY": snap},
        )
    assert blocked is False
    assert (
        meta.get("chopLiveStructuralPadWaive")
        or meta.get("chopLiveNearBaseWaive")
        or meta.get("octPaperChopWireSkipped")
    )


@patch("app.engines.chop_live_guards.chop_live_guard_day_active", return_value=True)
def test_no_structural_waive_without_pad_context(_day):
    s = settings_mock(
        october_frozen_profile_enabled=False,
        enable_live_trading=True,
        live_paper_parity_enabled=False,
        live_trade_selection_parity_with_paper=False,
        chop_live_guards_enabled=True,
        structural_pad_chop_live_waiver_enabled=True,
    )
    alert = {
        "side": "CALL",
        "tier": "ELITE",
        "explosionScore": 100.0,
        "localBaseMovePct": 45.0,
        "offLowMovePct": 1.0,
        "sessionRangePosition": 0.92,
        "drawdownFromHighPct": -2.0,
    }
    cand = _candidate("CALL", alert)
    snap = MagicMock()
    state = AutoTraderState()
    with patch("app.engines.chop_live_guards.get_settings", return_value=s):
        with patch(
            "app.engines.chop_worst_flip_capture.chop_worst_flip_chop_live_waive_ok",
            return_value=(False, ""),
        ), patch(
            "app.engines.chop_live_guards._candidate_structural_pad_lane",
            return_value=False,
        ), patch(
            "app.engines.chop_live_guards._immature_local_base_hard_block",
            return_value=(False, ""),
        ), patch(
            "app.engines.chop_live_guards._faded_rip_hard_block",
            return_value=(False, ""),
        ), patch(
            "app.engines.chop_live_guards._armed_base_chop_block",
            return_value=(False, ""),
        ), patch(
            "app.engines.chop_live_guards._extended_chase_hard_block",
            return_value=(True, "chop_live_extended_chase"),
        ):
            blocked, reason, _meta = chop_live_entry_blocked(
                cand, snap, state, snapshots={"NIFTY": snap},
            )
    assert blocked is True
    assert "extended_chase" in reason


@patch("app.engines.session_mode_feedback.get_settings")
def test_structural_pad_waives_failed_launch_reentry_on_new_strike_ce(mock_settings):
    from datetime import datetime, timedelta

    from app.engines.session_mode_feedback import failed_launch_reentry_blocked
    from app.models.schemas import Side

    s = _replica_settings(
        structural_pad_failed_launch_reentry_waiver_enabled=True,
    )
    mock_settings.return_value = s
    prior = SimpleNamespace(
        id="p1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=72000.0,
        strategyType="EXPLOSIVE",
        exitReason="explosion_failed_launch",
        pnlInr=-500.0,
        bestPnlPoints=0.0,
        closedAt=datetime.now() - timedelta(minutes=5),
        openedAt=datetime.now() - timedelta(minutes=6),
        entryContext={"selectionMode": "explosion"},
    )
    state = AutoTraderState()
    state.closedPaperTrades = [prior]
    alert = {
        "side": "CALL",
        "tier": "ELITE",
        "momentType": "first_lift_local_base",
        "firstLift": True,
        "explosionScore": 100.0,
        "localBaseMovePct": 8.0,
        "offLowMovePct": 10.0,
        "sessionRangePosition": 0.35,
        "drawdownFromHighPct": -12.0,
        "moneyness": "ITM",
    }
    blocked, meta = failed_launch_reentry_blocked(
        state, symbol="NIFTY", side=Side.CALL, strike=72050.0, alert=alert,
    )
    assert blocked is False
    assert meta.get("structuralPadFailedLaunchReentryWaived") is True
