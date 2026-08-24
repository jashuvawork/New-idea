"""First-lift local base with flat v3 snapshot — Aug24 NIFTY PUT 24200 miss."""

from __future__ import annotations

from app.engines.trade_ranking import ftv_authorization_policy, rank_trade_evidence


def _aug24_put_24200_miss(**overrides):
    """Live miss profile: ELITE first_lift_local_base, v3=0, lb=22.4%, peak 224%."""
    evidence = {
        "mode": "explosion",
        "tier": "ELITE",
        "explosionScore": 70.0,
        "tqs": 59.0,
        "chartConfidence": 84.0,
        "velocity3s": 0.0,
        "velocity9s": 0.0,
        "localBaseMovePct": 22.4,
        "firstLift": True,
        "armedBaseLaunch": False,
        "eliteBaseReady": False,
        "flatThenVertical": True,
        "activeBreakout": True,
        "orderflowPositive": True,
        "volumeAwaken": True,
        "flatVerticalQuality": 55.0,
        "timingAssessment": "GOOD",
    }
    evidence.update(overrides)
    return evidence


def test_flat_v3_first_lift_gets_grade_a():
    evidence = _aug24_put_24200_miss()
    ranking = rank_trade_evidence(evidence)
    assert ranking["grade"] == "A"
    assert ranking["evidence"]["firstLiftLocalBaseFlatVelocity"] is True


def test_flat_v3_first_lift_admits_first_lift_local_base_sleeve():
    evidence = _aug24_put_24200_miss()
    ranking = rank_trade_evidence(evidence)
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        allocation_rank=1,
        require_allocation_rank_one=True,
        day_mode="WORST DAY · BREAKOUT_ONLY",
    )
    assert decision.allowed is True
    assert decision.mode == "FIRST_LIFT_LOCAL_BASE"
    assert decision.reason == "ok_flat_velocity_lag"
    assert decision.max_capital_pct == 0.35


def test_flat_v3_first_lift_still_blocks_without_volume_awaken():
    evidence = _aug24_put_24200_miss(volumeAwaken=False, orderflowPositive=False)
    ranking = rank_trade_evidence(evidence)
    assert ranking["evidence"]["firstLiftLocalBaseFlatVelocity"] is False
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        allocation_rank=1,
        require_allocation_rank_one=True,
    )
    assert decision.allowed is False
    assert decision.reason == "top_ftv_a_requires_a_grade"


def test_flat_v3_first_lift_still_blocks_extended_local_base():
    evidence = _aug24_put_24200_miss(localBaseMovePct=28.0)
    ranking = rank_trade_evidence(evidence)
    assert ranking["evidence"]["firstLiftLocalBaseFlatVelocity"] is False
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        allocation_rank=1,
        require_allocation_rank_one=True,
    )
    assert decision.allowed is False


def test_positive_v3_does_not_use_flat_velocity_stamp():
    evidence = _aug24_put_24200_miss(velocity3s=2.5, velocity9s=1.8)
    ranking = rank_trade_evidence(evidence)
    assert ranking["evidence"]["firstLiftLocalBaseFlatVelocity"] is False

