"""Helper-confirmed BUILDING rip boost — Nifty ATM vertical thrust capture."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.config import Settings
from app.engines.building_rip_capture import (
    apply_helper_confirmed_building_rip_boost,
    building_rip_ftv_local_move_pct,
    helper_confirmed_building_rip_active,
)
from app.engines.trade_ranking import ftv_authorization_policy, rank_trade_evidence


def _nifty23100_ce_chase_alert(**overrides):
    """Shape seen on prod Sep 25 ~10:36 — index rip, CE +38% chart, bot mid-rip baseline."""
    alert = {
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 23100.0,
        "tier": "BUILDING",
        "tradeable": False,
        "explosionScore": 41.0,
        "velocity3s": -1.67,
        "peakVelocity3s": 2.4,
        "velocity9s": 0.4,
        "localBaseMovePct": 66.6,
        "ictBuildingRipReady": True,
        "indexHelpersConfirm": True,
        "buildingHelperBonus": 40.0,
        "buildingRipHelpersOk": True,
        "orderflowPositive": True,
        "volumeAwaken": True,
        "cvdBuying": True,
        "flatThenVertical": True,
        "activeBreakout": True,
        "timingAssessment": "GOOD",
    }
    alert.update(overrides)
    return alert


def test_helper_confirmed_building_rip_active_requires_bonus():
    alert = _nifty23100_ce_chase_alert(buildingHelperBonus=20.0)
    assert helper_confirmed_building_rip_active(alert) is False
    assert helper_confirmed_building_rip_active(_nifty23100_ce_chase_alert()) is True


def test_rank_evidence_building_rip_from_alert_stamp():
    from app.engines.trade_ranking import rank_trade_evidence

    evidence = rank_trade_evidence(
        {
            "mode": "explosion",
            "tier": "EXPLODING",
            "explosionScore": 88.0,
            "buildingRipReady": True,
            "buildingRipHelpersOk": True,
            "indexHelpersConfirm": True,
            "velocity3s": 2.0,
            "localBaseMovePct": 12.0,
        }
    )
    ev = evidence.get("evidence") or {}
    assert ev.get("buildingRipReady") is True


def test_building_rip_ftv_local_move_caps_chase_misread():
    move = building_rip_ftv_local_move_pct(
        {
            "localBaseMovePct": 66.6,
            "buildingRipReady": True,
            "indexHelpersConfirm": True,
            "buildingRipHelpersOk": True,
        },
        settings=Settings(),
    )
    assert move == pytest.approx(28.0)


@patch(
    "app.engines.explosion_detector.retained_peak_velocity_3s",
    return_value=2.4,
)
def test_apply_boost_promotes_tradeable_exploding(_peak):
    boosted = apply_helper_confirmed_building_rip_boost(_nifty23100_ce_chase_alert())
    assert boosted["tier"] == "EXPLODING"
    assert boosted["tradeable"] is True
    assert float(boosted["explosionScore"]) >= 85.0
    assert float(boosted["velocity3s"]) >= 2.4
    assert float(boosted["localBaseMovePct"]) <= 28.0
    assert boosted.get("ictBuildingRipReady") is True


@patch(
    "app.engines.explosion_detector.retained_peak_velocity_3s",
    return_value=2.4,
)
def test_boosted_alert_authorizes_building_rip_ftv(_peak):
    boosted = apply_helper_confirmed_building_rip_boost(_nifty23100_ce_chase_alert())
    evidence = {
        **boosted,
        "mode": "explosion",
        "tqs": boosted["explosionScore"],
        "chartConfidence": 55.0,
        "buildingRipReady": True,
        "flatVerticalQuality": 55.0,
        "displacement": True,
    }
    ranking = rank_trade_evidence(evidence)
    decision = ftv_authorization_policy(
        ranking.get("evidence") or evidence,
        ranking,
        snapshot_available=True,
        atm_itm_allowed=True,
        building_rip_ftv_enabled=True,
    )
    assert ranking["grade"] in {"A", "B", "S"}
    assert decision.mode == "BUILDING_RIP_FTV"
    assert decision.reason == "ok"


@patch(
    "app.engines.explosion_detector.retained_peak_velocity_3s",
    return_value=2.4,
)
def test_helper_building_rip_elite_entry_allowed(_peak):
    from unittest.mock import MagicMock
    from types import SimpleNamespace

    from app.engines.elite_score_engine import elite_entry_allowed
    from app.engines.trade_ranking import rank_entry_candidate

    boosted = apply_helper_confirmed_building_rip_boost(_nifty23100_ce_chase_alert())
    event = SimpleNamespace(tier="EXPLODING", explosion_score=88.0, velocity_3s=2.4, velocity_9s=0.4)
    cand = SimpleNamespace(
        side="CALL",
        symbol="NIFTY",
        strike=23100,
        alert=boosted,
        explosion_event=event,
        mode="explosion",
        confidence=88.0,
    )
    snap = MagicMock()
    snap.symbol = "NIFTY"
    snap.breadth = MagicMock(bias="BULLISH")
    snap.spotChart = MagicMock(direction="BULLISH", rsi=55.0, macdBias="BULLISH", momentum5Pct=0.1)
    state = MagicMock()
    state.closedPaperTrades = []
    state.dailyStrategy = {"dayMode": "MOMENTUM RALLY"}
    ranking = rank_entry_candidate(cand, snapshot=snap)
    evidence = {**boosted, **dict(ranking.get("evidence") or {})}
    ok, reason, _ass = elite_entry_allowed(
        evidence,
        ranking,
        state=state,
        snapshots={"NIFTY": snap},
    )
    assert ok, reason


@patch(
    "app.engines.explosion_detector.retained_peak_velocity_3s",
    return_value=2.4,
)
def test_helper_building_rip_top_moment_gate(_peak):
    from app.engines.building_ftv_gates import helper_building_rip_top_moment_ok
    from app.engines.trade_ranking import rank_entry_candidate
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    boosted = apply_helper_confirmed_building_rip_boost(_nifty23100_ce_chase_alert())
    event = SimpleNamespace(tier="EXPLODING", explosion_score=88.0, velocity_3s=2.4)
    cand = SimpleNamespace(
        side="CALL",
        symbol="NIFTY",
        strike=23100,
        alert=boosted,
        explosion_event=event,
        mode="explosion",
    )
    snap = MagicMock()
    snap.symbol = "NIFTY"
    ranking = rank_entry_candidate(cand, snapshot=snap)
    evidence = {**boosted, **dict(ranking.get("evidence") or {})}
    assert helper_building_rip_top_moment_ok(evidence, ranking)
