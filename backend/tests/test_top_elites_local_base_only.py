"""Top ELITE/EXPLODING only, entered at local base — not every mid FTV print."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.engines.ict_breakout_monitor import _defensive_base_rip_top_allowed
from app.engines.trade_ranking import ftv_authorization_policy, rank_trade_evidence


def _top_local_base(**overrides):
    evidence = {
        "mode": "explosion",
        "tier": "EXPLODING",
        "explosionScore": 92.0,
        "tqs": 58.0,
        "velocity3s": 3.2,
        "velocity9s": 2.4,
        "localBaseMovePct": 11.0,
        "armedBaseLaunch": True,
        "firstLift": False,
        "flatThenVertical": True,
        "activeBreakout": True,
        "orderflowPositive": True,
        "cvdBuying": True,
        "cvdAcceleration": True,
        "flatVerticalQuality": 82.0,
        "timingAssessment": "GOOD",
    }
    evidence.update(overrides)
    return evidence


def test_mid_armed_exploding_cannot_mint_grade_s():
    """Aug18-style mid EXPLODING (score ~71, quality B) must not become S_STRICT."""
    evidence = _top_local_base(
        explosionScore=71.5,
        flatVerticalQuality=64.8,
        velocity3s=2.4,
        velocity9s=2.0,
        localBaseMovePct=9.4,
        orderflowPositive=True,
    )
    ranking = rank_trade_evidence(evidence)
    assert ranking["grade"] != "S"
    assert ranking["topRankEligible"] is False
    decision = ftv_authorization_policy(evidence, ranking, snapshot_available=True)
    assert decision.allowed is False


def test_top_armed_exploding_at_local_base_gets_s_strict():
    evidence = _top_local_base()
    ranking = rank_trade_evidence(evidence)
    assert ranking["grade"] == "S"
    assert ranking["topRankEligible"] is True
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        allocation_rank=1,
        require_allocation_rank_one=True,
    )
    assert (decision.mode, decision.reason) == ("S_STRICT", "ok")


def test_s_strict_rejects_chase_past_local_base_pad():
    evidence = _top_local_base(localBaseMovePct=32.0)
    ranking = rank_trade_evidence(evidence)
    # Ranking itself refuses armed_top when pad > 25%.
    assert ranking["grade"] != "S"
    decision = ftv_authorization_policy(evidence, ranking, snapshot_available=True)
    assert decision.allowed is False


def test_defensive_rip_top_rejects_mid_exploding():
    settings = MagicMock()
    settings.ict_defensive_base_rip_require_top_quality = True
    settings.ict_defensive_base_rip_min_score = 80.0
    settings.ict_defensive_base_rip_min_quality = 70.0
    settings.ict_defensive_base_rip_min_velocity_3s = 2.5
    ok, reason = _defensive_base_rip_top_allowed(
        tier="EXPLODING",
        quality=64.8,
        score=71.5,
        velocity_3s=2.4,
        settings=settings,
    )
    assert ok is False
    assert reason.startswith("defensive_rip_top_")


def test_defensive_rip_top_allows_strong_exploding_at_base():
    settings = MagicMock()
    settings.ict_defensive_base_rip_require_top_quality = True
    settings.ict_defensive_base_rip_min_score = 80.0
    settings.ict_defensive_base_rip_min_quality = 70.0
    settings.ict_defensive_base_rip_min_velocity_3s = 2.5
    ok, reason = _defensive_base_rip_top_allowed(
        tier="EXPLODING",
        quality=82.0,
        score=92.0,
        velocity_3s=3.2,
        settings=settings,
    )
    assert ok is True
    assert reason == "ok"
