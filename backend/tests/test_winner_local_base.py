"""Admit historical ELITE/EXPLODING winner shapes at local base (ordinary sleeve)."""

from __future__ import annotations

from app.engines.trade_ranking import ftv_authorization_policy, rank_trade_evidence


def _winner_evidence(**overrides):
    evidence = {
        "mode": "explosion",
        "tier": "ELITE",
        "explosionScore": 82.0,
        "tqs": 55.0,
        "velocity3s": 2.4,
        "velocity9s": 1.8,
        "localBaseMovePct": 18.0,
        "firstLift": True,
        "armedBaseLaunch": False,
        "flatThenVertical": True,
        "activeBreakout": True,
        "orderflowPositive": True,
        "cvdBuying": False,
        "cvdAcceleration": False,
        "flatVerticalQuality": 78.0,
        "timingAssessment": "GOOD",
    }
    evidence.update(overrides)
    return evidence


def test_winner_like_elite_local_base_admits_without_cvd_acceleration():
    evidence = _winner_evidence()
    ranking = rank_trade_evidence(evidence)
    assert ranking["grade"] in {"A", "B"}
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        allocation_rank=1,
        require_allocation_rank_one=True,
    )
    assert decision.mode == "WINNER_LOCAL_BASE"
    assert decision.max_capital_pct == 0.35


def test_winner_local_base_still_blocks_aug18_mid_exploding():
    evidence = _winner_evidence(
        tier="EXPLODING",
        explosionScore=71.5,
        flatVerticalQuality=64.8,
        velocity3s=2.4,
        velocity9s=2.0,
        localBaseMovePct=9.4,
        firstLift=False,
        armedBaseLaunch=True,
    )
    ranking = rank_trade_evidence(evidence)
    decision = ftv_authorization_policy(evidence, ranking, snapshot_available=True)
    assert decision.allowed is False


def test_winner_exploding_at_base_with_heat_passes():
    evidence = _winner_evidence(
        tier="EXPLODING",
        explosionScore=88.0,
        flatVerticalQuality=80.0,
        velocity3s=2.8,
        velocity9s=2.0,
        localBaseMovePct=16.0,
        firstLift=True,
    )
    ranking = rank_trade_evidence(evidence)
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        allocation_rank=1,
        require_allocation_rank_one=True,
    )
    assert decision.allowed is True
    assert decision.mode in {"WINNER_LOCAL_BASE", "TOP_FTV_A", "S_STRICT"}
