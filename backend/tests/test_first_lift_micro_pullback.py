"""First-lift local-base micro pullback — Aug24 NIFTY PUT 24450 GOOD_MISS fix."""

from __future__ import annotations

from app.engines.trade_ranking import ftv_authorization_policy, rank_trade_evidence


def _nifty_put_24450_miss(**overrides):
    """Live miss profile: EXPLODING v_rip at 22.7% pad, v3 micro dip."""
    evidence = {
        "mode": "explosion",
        "tier": "EXPLODING",
        "explosionScore": 65.0,
        "tqs": 54.0,
        "velocity3s": -0.87,
        "velocity9s": 0.4,
        "localBaseMovePct": 22.7,
        "firstLift": True,
        "vRipReady": True,
        "flatThenVertical": True,
        "activeBreakout": True,
        "volumeAwaken": True,
        "orderflowPositive": True,
        "flatVerticalQuality": 58.0,
        "timingAssessment": "GOOD",
    }
    evidence.update(overrides)
    return evidence


def test_micro_pullback_admits_first_lift_local_base_sleeve():
    evidence = _nifty_put_24450_miss()
    ranking = rank_trade_evidence(evidence)
    assert ranking["grade"] != "REJECT"
    assert ranking["evidence"]["firstLiftLocalBaseMicroPullback"] is True

    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        allocation_rank=1,
        require_allocation_rank_one=True,
        day_mode="WORST",
    )
    assert decision.allowed is True
    assert decision.mode == "FIRST_LIFT_LOCAL_BASE"
    assert decision.reason == "ok_micro_pullback"
    assert decision.max_capital_pct == 0.35


def test_deep_negative_velocity_still_blocked():
    evidence = _nifty_put_24450_miss(velocity3s=-2.5)
    ranking = rank_trade_evidence(evidence)
    assert ranking["grade"] == "REJECT"
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        allocation_rank=1,
    )
    assert decision.allowed is False
    assert decision.reason == "ftv_elite_top_only_timing_blocked"


def test_extended_local_base_not_micro_pullback():
    evidence = _nifty_put_24450_miss(localBaseMovePct=30.0, velocity3s=-0.5)
    ranking = rank_trade_evidence(evidence)
    assert ranking["evidence"]["firstLiftLocalBaseMicroPullback"] is False
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        allocation_rank=1,
    )
    assert decision.allowed is False


def test_late_chase_low_local_base_not_micro_pullback():
    evidence = _nifty_put_24450_miss(
        localBaseMovePct=3.0,
        velocity3s=-0.5,
        firstLift=False,
        vRipReady=False,
    )
    ranking = rank_trade_evidence(evidence)
    assert ranking["evidence"]["firstLiftLocalBaseMicroPullback"] is False
