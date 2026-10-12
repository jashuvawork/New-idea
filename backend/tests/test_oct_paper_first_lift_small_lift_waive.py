"""Oct 1 paper — first-lift / small-lift waives chase blockers (not negative_velocity)."""

from __future__ import annotations

from unittest.mock import patch

from app.engines.elite_score_engine import (
    elite_entry_allowed,
    elite_fvq_chase_blocked,
    elite_perfect_score_blocked,
)
from app.engines.live_paper_parity import oct_paper_first_lift_small_lift_context
from app.engines.rally_capture import explosion_near_miss_waive
from app.engines.trade_ranking import rank_trade_evidence
from tests.mock_defaults import settings_mock


def _frozen_paper_settings(**kwargs):
    return settings_mock(
        october_frozen_profile_enabled=True,
        enable_live_trading=True,
        auto_trading_enabled=True,
        live_paper_parity_enabled=True,
        aggressive_min_explosion_score=45.0,
        **kwargs,
    )


def test_oct_first_lift_context_ce_armed_base_at_pad():
    s = _frozen_paper_settings()
    ev = {
        "side": "CALL",
        "tier": "ELITE",
        "momentType": "armed_base_launch",
        "armedBaseLaunch": True,
        "firstLift": True,
        "localBaseMovePct": 11.0,
        "offLowMovePct": 8.0,
        "moneyness": "ATM",
        "strikeStepsFromAtm": 1,
    }
    assert oct_paper_first_lift_small_lift_context(ev, settings=s)


def test_oct_first_lift_context_afternoon_ce_local_base_not_open_window():
    """Oct 12 ~12:40 — CE first_lift off local base, mid session range, not open chase."""
    s = _frozen_paper_settings()
    ev = {
        "side": "CALL",
        "tier": "ELITE",
        "momentType": "first_lift_local_base",
        "firstLift": True,
        "localBaseMovePct": 4.0,
        "offLowMovePct": 3.0,
        "sessionRangePosition": 0.62,
        "drawdownFromHighPct": -18.0,
        "moneyness": "ITM",
        "strikeStepsFromAtm": 2,
        "explosionScore": 92.4,
    }
    assert oct_paper_first_lift_small_lift_context(ev, settings=s)


def test_oct_first_lift_context_put_afternoon_slide_pad():
    s = _frozen_paper_settings()
    ev = {
        "side": "PUT",
        "tier": "ELITE",
        "momentType": "first_lift_local_base",
        "firstLift": True,
        "localBaseMovePct": 6.0,
        "offHighMovePct": 4.0,
        "sessionRangePosition": 0.58,
        "drawdownFromHighPct": -15.0,
        "moneyness": "ITM",
        "strikeStepsFromAtm": 1,
        "explosionScore": 100.0,
    }
    assert oct_paper_first_lift_small_lift_context(ev, settings=s)


def test_oct_first_lift_rejects_put_session_low_dump_chase():
    s = _frozen_paper_settings()
    ev = {
        "side": "PUT",
        "tier": "ELITE",
        "momentType": "armed_base_launch",
        "armedBaseLaunch": True,
        "localBaseMovePct": 14.0,
        "offHighMovePct": 0.5,
        "sessionRangePosition": 0.03,
        "drawdownFromHighPct": -40.0,
        "moneyness": "ATM",
        "explosionScore": 100.0,
    }
    assert not oct_paper_first_lift_small_lift_context(ev, settings=s)


def test_oct_first_lift_context_put_slide_symmetric():
    s = _frozen_paper_settings()
    ev = {
        "side": "PUT",
        "tier": "ELITE",
        "momentType": "v_rip_session_high",
        "vRipReady": True,
        "localBaseMovePct": 10.0,
        "offHighMovePct": 5.0,
        "moneyness": "ITM",
        "strikeStepsFromAtm": 1,
    }
    assert oct_paper_first_lift_small_lift_context(ev, settings=s)


@patch("app.engines.elite_score_engine.resolve_elite_session_day_type", return_value=("BULLISH DAY", "BULLISH"))
def test_first_lift_waives_fvq_and_perfect_score_chase(_day):
    s = _frozen_paper_settings()
    ev = {
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 22450.0,
        "tier": "ELITE",
        "momentType": "armed_base_launch",
        "armedBaseLaunch": True,
        "firstLift": True,
        "localBaseMovePct": 12.0,
        "offLowMovePct": 10.0,
        "flatVerticalQuality": 92.0,
        "explosionScore": 100.0,
        "velocity3s": 2.0,
        "velocity9s": 1.5,
        "timingAssessment": "OK",
        "timingAction": "allow",
        "moneyness": "ATM",
        "strikeStepsFromAtm": 1,
        "mode": "explosion",
        "tqs": 55.0,
        "chartConfidence": 50.0,
    }
    blocked, reason = elite_fvq_chase_blocked(ev, settings=s)
    assert blocked is False, reason
    blocked, reason = elite_perfect_score_blocked(
        100.0, 18.0, settings=s, evidence=ev,
    )
    assert blocked is False, reason


@patch("app.engines.elite_score_engine.resolve_elite_session_day_type", return_value=("BULLISH DAY", "BULLISH"))
def test_first_lift_elite_entry_passes_high_fvq_score100(_day):
    s = _frozen_paper_settings(elite_trade_engine_enabled=True)
    ev = {
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 22450.0,
        "tier": "ELITE",
        "momentType": "armed_base_launch",
        "armedBaseLaunch": True,
        "firstLift": True,
        "localBaseMovePct": 12.0,
        "offLowMovePct": 10.0,
        "flatVerticalQuality": 88.0,
        "explosionScore": 100.0,
        "velocity3s": 2.5,
        "velocity9s": 2.0,
        "timingAssessment": "OK",
        "timingAction": "allow",
        "moneyness": "ATM",
        "strikeStepsFromAtm": 1,
        "mode": "explosion",
        "tqs": 55.0,
        "chartConfidence": 50.0,
        "ictArmedBaseLaunch": True,
    }
    ranking = rank_trade_evidence(ev)
    ok, reason, _ = elite_entry_allowed(
        ev, ranking, settings=s, side="CALL", readiness_reason="armed_base_launch_ready",
    )
    assert ok is True, reason


def test_near_miss_waives_except_negative_velocity():
    s = _frozen_paper_settings()
    alert = {
        "tier": "ELITE",
        "explosionScore": 100.0,
        "side": "CALL",
        "armedBaseLaunch": True,
        "firstLift": True,
        "localBaseMovePct": 10.0,
        "offLowMovePct": 8.0,
        "moneyness": "ATM",
        "strikeStepsFromAtm": 1,
    }
    assert explosion_near_miss_waive(
        alert, readiness_reason="explosion_score_below_min", settings=s,
    )
    assert not explosion_near_miss_waive(
        alert, readiness_reason="first_lift_live_velocity_negative", settings=s,
    )


def test_oct_first_lift_entry_window_lo_relax():
    from app.engines.explosion_entry_guards import explosion_entry_window_blocked
    from app.engines.live_paper_parity import oct_paper_first_lift_entry_window_lo_relax
    from types import SimpleNamespace

    s = _frozen_paper_settings()
    alert = {
        "side": "CALL",
        "tier": "ELITE",
        "momentType": "first_lift_local_base",
        "firstLift": True,
        "localBaseMovePct": 4.0,
        "offLowMovePct": 8.0,
        "sessionRangePosition": 0.35,
        "drawdownFromHighPct": -14.0,
        "moneyness": "ITM",
        "strikeStepsFromAtm": 2,
        "explosionScore": 100.0,
    }
    lo = oct_paper_first_lift_entry_window_lo_relax(alert, default_lo=15.0, settings=s)
    assert lo <= 2.0
    event = SimpleNamespace(
        local_base_move_pct=4.0,
        peak_move_pct=4.0,
        daily_move_pct=4.0,
        side="CALL",
        tier="ELITE",
    )
    with patch(
        "app.engines.explosion_entry_guards.effective_local_base_move_pct",
        return_value=4.0,
    ), patch("app.engines.explosion_entry_guards.get_settings", return_value=s):
        blocked, reason = explosion_entry_window_blocked(
            event,
            alert=alert,
            snap=None,
        )
    assert blocked is False, reason


def test_oct_first_lift_otm_all_session_not_open_only():
    from app.engines.live_paper_parity import oct_paper_first_lift_otm_entry_ok

    s = _frozen_paper_settings()
    alert = {
        "side": "CALL",
        "tier": "ELITE",
        "momentType": "armed_base_launch",
        "armedBaseLaunch": True,
        "firstLift": True,
        "localBaseMovePct": 8.0,
        "offLowMovePct": 10.0,
        "sessionRangePosition": 0.48,
        "drawdownFromHighPct": -20.0,
        "moneyness": "OTM",
        "strikeStepsFromAtm": 2,
        "explosionScore": 100.0,
    }
    assert oct_paper_first_lift_otm_entry_ok(alert, depth_steps=2, settings=s)
    assert not oct_paper_first_lift_otm_entry_ok(alert, depth_steps=5, settings=s)


def test_oct_elite_rip_put_uses_slide_pad_not_call_off_low():
    from app.engines.live_paper_parity import oct_paper_elite_rip_context

    s = _frozen_paper_settings()
    ev = {
        "side": "PUT",
        "tier": "ELITE",
        "explosionScore": 100.0,
        "velocity3s": -1.0,
        "momentType": "v_rip_session_high",
        "vRipReady": True,
        "localBaseMovePct": 10.0,
        "offHighMovePct": 4.0,
        "sessionRangePosition": 0.55,
        "drawdownFromHighPct": -12.0,
    }
    with patch("app.engines.session_timing.in_open_premium_window", return_value=False):
        assert oct_paper_elite_rip_context(ev, settings=s)


def test_counter_trend_allows_oct_first_lift_afternoon():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from app.engines.morning_premium_capture import counter_trend_entry_allowed
    from app.models.schemas import Side

    s = _frozen_paper_settings()
    alert = {
        "side": "CALL",
        "tier": "ELITE",
        "momentType": "first_lift_local_base",
        "firstLift": True,
        "localBaseMovePct": 4.0,
        "sessionRangePosition": 0.55,
        "drawdownFromHighPct": -12.0,
        "moneyness": "ITM",
        "strikeStepsFromAtm": 2,
        "explosionScore": 100.0,
    }
    event = SimpleNamespace(
        side=Side.CALL,
        tier="ELITE",
        explosion_score=100.0,
        symbol="NIFTY",
    )
    snap = MagicMock()
    snap.breadth = MagicMock(bias="BEARISH")
    snap.spotChart = MagicMock()
    with patch("app.engines.morning_premium_capture.get_settings", return_value=s):
        assert counter_trend_entry_allowed(
            Side.CALL, snap, explosion_event=event, alert=alert,
        )


@patch("app.config.get_settings")
def test_negative_velocity_still_rejects_without_launch(mock_settings):
    mock_settings.return_value = _frozen_paper_settings()
    ev = {
        "tier": "ELITE",
        "explosionScore": 100.0,
        "velocity3s": -2.0,
        "velocity9s": -1.0,
        "localBaseMovePct": 12.0,
        "mode": "explosion",
        "tqs": 55.0,
        "chartConfidence": 50.0,
    }
    ranking = rank_trade_evidence(ev)
    assert ranking["grade"] == "REJECT"
