"""Oct 1 small-lift CE at ATM/ITM base — paper parity without liveEntryScore stamp."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.engines.elite_score_engine import elite_entry_allowed
from app.engines.live_oct1_pad_entry_guard import live_oct1_pad_entry_blocked
from app.models.schemas import Side, SymbolSnapshot
from tests.mock_defaults import settings_mock


def _nifty_snap(*, spot: float = 22680.0, atm: float = 22700.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp="2026-10-07T12:15:00+05:30",
        marketPhase="LIVE_MARKET",
        spot=spot,
        atmStrike=atm,
        dataAvailable=True,
    )


def _oct1_ce_base_evidence(**kwargs):
    base = {
        "symbol": "NIFTY",
        "strike": 22700.0,
        "side": "CALL",
        "tier": "ELITE",
        "momentType": "v_rip_session_low",
        "ictBaseReadinessReason": "v_rip_session_low_ready",
        "localBaseMovePct": 9.0,
        "flatThenVertical": False,
        "vRipReady": True,
        "activeBreakout": True,
        "armedBaseLaunch": True,
        "firstLift": True,
        "velocity3s": 2.5,
        "velocity9s": 1.8,
        "flatVerticalQuality": 79.0,
        "explosionScore": 96.0,
        "volumeAwaken": True,
        "timingAssessment": "OK",
        "timingAction": "allow",
        "drawdownFromHighPct": -12.0,
        "sessionRangePosition": 0.35,
        "premium": 122.0,
        "sessionPeakPremium": 158.0,
        "sessionLowPremium": 95.0,
    }
    base.update(kwargs)
    return base


def _ranking(**kwargs):
    base = {"grade": "A", "rankScore": 82.0, "side": "CALL"}
    base.update(kwargs)
    return base


@patch("app.engines.elite_score_engine.resolve_elite_session_day_type", return_value=("CHOP DAY", "CHOP"))
def test_ce_small_lift_at_base_passes_elite_without_live_entry_score(_day):
    """Paper Oct 1: ATM CE at pad passes elite floor without rally-unlock or live stamp."""
    s = settings_mock(
        live_paper_parity_enabled=True,
        live_trade_selection_parity_with_paper=True,
        sep917_legacy_profile_enabled=True,
        symmetric_best_trade_capture_enabled=True,
    )
    snap = _nifty_snap()
    ev = _oct1_ce_base_evidence()
    snapshots = {"NIFTY": snap}
    ok, reason, assessment = elite_entry_allowed(
        ev,
        _ranking(),
        settings=s,
        side="CALL",
        snapshots=snapshots,
    )
    assert ok is True, reason
    assert reason == "ok"
    assert assessment.get("side") == "CALL"


@patch("app.engines.elite_score_engine.resolve_elite_session_day_type", return_value=("CHOP DAY", "CHOP"))
def test_ce_at_session_high_still_blocked_by_pad_guard(_day):
    s = settings_mock(
        live_paper_parity_enabled=True,
        live_trade_selection_parity_with_paper=True,
    )
    snap = _nifty_snap()
    ev = _oct1_ce_base_evidence(
        drawdownFromHighPct=0.0,
        sessionRangePosition=0.98,
        premium=158.0,
    )
    cand = SimpleNamespace(
        mode="explosion",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22700.0,
        premium=158.0,
        alert=ev,
        pretrade_meta={},
        snap=snap,
    )
    blocked, reason, _meta = live_oct1_pad_entry_blocked(cand, snap, settings=s)
    assert blocked is True
    assert reason in (
        "live_oct1_chase_at_session_high",
        "live_oct1_chase_session_range_high",
    )


@patch("app.engines.elite_score_engine.resolve_elite_session_day_type", return_value=("CHOP DAY", "CHOP"))
def test_ce_session_high_fails_elite_pad_waive_path(_day):
    """Near-base shape at session high must not get CE base waive (score/timing path)."""
    s = settings_mock(
        live_paper_parity_enabled=True,
        sep917_legacy_profile_enabled=True,
        symmetric_best_trade_capture_enabled=True,
    )
    snap = _nifty_snap()
    ev = _oct1_ce_base_evidence(
        drawdownFromHighPct=0.0,
        sessionRangePosition=0.95,
        premium=158.0,
        timingAssessment="BAD",
        timingAction="block",
    )
    ok, reason, _ = elite_entry_allowed(
        ev,
        _ranking(rankScore=70.0),
        settings=s,
        side="CALL",
        snapshots={"NIFTY": snap},
    )
    assert ok is False
    assert "elite_timing" in reason or "elite_score" in reason


@patch("app.engines.elite_score_engine.resolve_elite_session_day_type", return_value=("CHOP DAY", "CHOP"))
def test_legacy_require_explicit_live_blocks_same_fixture(_day):
    """Documents Oct 7 failure mode: best_capture with require_explicit_live=True."""
    from app.engines.live_entry_score import live_entry_best_trade_capture_active

    ev = _oct1_ce_base_evidence()
    assert live_entry_best_trade_capture_active(
        ev, settings=settings_mock(), require_explicit_live=True,
    ) is False
    assert live_entry_best_trade_capture_active(
        ev, settings=settings_mock(), require_explicit_live=False,
    ) is True
