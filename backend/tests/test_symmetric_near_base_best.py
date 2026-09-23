"""Symmetric CE/PE near-base best-trade bar (Sep 9–17 profile)."""

from app.config import Settings
from app.engines.best_trade_policy import symmetric_near_base_best_ok


def test_symmetric_structural_base_counts_for_ce_and_put():
    s = Settings()
    assessment = {
        "eliteScore": 92.0,
        "localBasePct": 12.0,
        "setup": "FTV",
        "side": "CALL",
    }
    evidence = {
        "tier": "ELITE",
        "localBaseMovePct": 18.0,
        "ictBaseRelativeMovePct": 18.0,
        "flatQualityScore": 70.0,
    }
    assert symmetric_near_base_best_ok(assessment, evidence, settings=s) is True
    assessment["side"] = "PUT"
    assert symmetric_near_base_best_ok(assessment, evidence, settings=s) is True


def test_symmetric_off_falls_back_to_elite_near_base_only():
    s = Settings(symmetric_best_trade_capture_enabled=False)
    assessment = {
        "eliteScore": 92.0,
        "localBasePct": 12.0,
        "setup": "FTV",
    }
    evidence = {"localBaseMovePct": 18.0}
    assert symmetric_near_base_best_ok(assessment, evidence, settings=s) is True
    assessment["eliteScore"] = 80.0
    assert symmetric_near_base_best_ok(assessment, evidence, settings=s) is False
