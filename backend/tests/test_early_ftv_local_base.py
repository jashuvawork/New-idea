"""Early FTV at local base — authorize before chase, keep winner floors."""

from __future__ import annotations

from app.engines.trade_ranking import ftv_authorization_policy, rank_trade_evidence


def _early_ftv_gap(**overrides):
    """12–15% dead zone: FTV true, armed expired, first-lift not yet on."""
    evidence = {
        "mode": "explosion",
        "tier": "ELITE",
        "explosionScore": 88.0,
        "tqs": 55.0,
        "velocity3s": 2.6,
        "velocity9s": 2.0,
        "localBaseMovePct": 13.5,
        "firstLift": False,
        "armedBaseLaunch": False,
        "eliteBaseReady": False,
        "armedBaseSustainedLift": False,
        "flatThenVertical": True,
        "activeBreakout": True,
        "orderflowPositive": True,
        "volumeAwaken": True,
        "displacement": True,
        "cvdBuying": False,
        "cvdAcceleration": False,
        "flatVerticalQuality": 72.0,
        "timingAssessment": "GOOD",
    }
    evidence.update(overrides)
    return evidence


def test_early_ftv_in_pad_admits_winner_without_flag_fresh_trigger():
    """Radar already shows FTV+heat at ~13.5% — authorize WINNER before chase."""
    evidence = _early_ftv_gap()
    ranking = rank_trade_evidence(evidence)
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        allocation_rank=1,
        require_allocation_rank_one=True,
        day_mode="NORMAL",
    )
    assert decision.allowed is True
    assert decision.mode == "WINNER_LOCAL_BASE"
    assert decision.max_capital_pct == 0.35


def test_early_ftv_with_cvd_can_take_top_ftv_a():
    evidence = _early_ftv_gap(
        explosionScore=96.0,
        flatVerticalQuality=82.0,
        velocity3s=3.2,
        velocity9s=2.5,
        cvdBuying=True,
        cvdAcceleration=True,
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
    assert decision.mode in {"TOP_FTV_A", "WINNER_LOCAL_BASE", "S_STRICT"}


def test_early_ftv_still_blocks_aug18_mid_exploding():
    evidence = _early_ftv_gap(
        tier="EXPLODING",
        explosionScore=71.5,
        flatVerticalQuality=64.8,
        velocity3s=2.4,
        localBaseMovePct=9.4,
        armedBaseLaunch=True,
        firstLift=False,
    )
    ranking = rank_trade_evidence(evidence)
    decision = ftv_authorization_policy(evidence, ranking, snapshot_available=True)
    assert decision.allowed is False


def test_early_ftv_without_heat_does_not_count_as_fresh():
    evidence = _early_ftv_gap(
        orderflowPositive=False,
        volumeAwaken=False,
        displacement=False,
        armedBaseSustainedLift=False,
    )
    ranking = rank_trade_evidence(evidence)
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        allocation_rank=1,
        require_allocation_rank_one=True,
    )
    assert decision.allowed is False
    assert "fresh" in decision.reason or "ftv" in decision.reason.lower()


def test_prior_winner_first_lift_still_admits():
    """Keep the prior winner path (first-lift + floors) intact."""
    evidence = _early_ftv_gap(
        localBaseMovePct=18.0,
        firstLift=True,
        explosionScore=82.0,
        flatVerticalQuality=78.0,
        velocity3s=2.4,
        volumeAwaken=False,
        displacement=False,
        orderflowPositive=True,
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
