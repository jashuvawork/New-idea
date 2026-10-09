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
