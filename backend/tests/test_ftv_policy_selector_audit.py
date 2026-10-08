"""FTV policy + selector gate observability (Frozen Oct has FTV off by default)."""

from app.config import Settings
from app.engines.trade_ranking import (
    ftv_authorization_policy,
    rank_trade_evidence,
    selector_rejection_reason,
)


def test_selector_rejection_reason_prefers_penalty_over_elite_tag():
    ranking = rank_trade_evidence(
        {
            "mode": "explosion",
            "tier": "ELITE",
            "explosionScore": 100.0,
            "tqs": 60.0,
            "velocity3s": -2.0,
            "velocity9s": 0.5,
            "localBaseMovePct": 18.0,
            "timingAssessment": "GOOD",
        }
    )
    assert ranking["grade"] == "REJECT"
    assert ranking["reasons"][0] == "elite_signal"
    assert selector_rejection_reason(ranking) == "negative_velocity"


def test_first_lift_counts_as_ftv_for_authorization():
    evidence = {
        "mode": "explosion",
        "tier": "ELITE",
        "explosionScore": 95.0,
        "tqs": 55.0,
        "velocity3s": 2.5,
        "velocity9s": 1.8,
        "localBaseMovePct": 20.0,
        "firstLift": True,
        "flatThenVertical": True,
        "activeBreakout": False,
        "orderflowPositive": True,
        "cvdBuying": True,
        "cvdAcceleration": True,
        "flatVerticalQuality": 72.0,
        "timingAssessment": "GOOD",
    }
    ranking = rank_trade_evidence(evidence)
    decision = ftv_authorization_policy(
        ranking.get("evidence") or evidence,
        ranking,
        snapshot_available=True,
        atm_itm_allowed=True,
        top_ftv_a_enabled=True,
    )
    assert decision.reason != "ftv_elite_top_only_requires_ftv"


def test_settings_default_ftv_elite_top_off():
    s = Settings()
    assert s.ftv_elite_top_only_enabled is False
