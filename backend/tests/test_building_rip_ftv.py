"""BUILDING sudden lift + helpers → FTV sleeve (no wait for ELITE)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.config import Settings
from app.engines.trade_ranking import ftv_authorization_policy, rank_trade_evidence


def _building_evidence(**overrides):
    evidence = {
        "mode": "explosion",
        "tier": "BUILDING",
        "explosionScore": 55.0,
        "tqs": 55.0,
        "chartConfidence": 60.0,
        "velocity3s": 2.1,
        "velocity9s": 1.4,
        "localBaseMovePct": 8.0,
        "buildingRipReady": True,
        "buildingRipHelpersOk": True,
        "flatThenVertical": True,
        "activeBreakout": True,
        "orderflowPositive": True,
        "volumeAwaken": True,
        "cvdBuying": True,
        "cvdAcceleration": False,
        "flatVerticalQuality": 60.0,
        "timingAssessment": "GOOD",
        "displacement": True,
    }
    evidence.update(overrides)
    return evidence


def test_building_rip_ftv_authorizes_helper_confirmed_lift():
    evidence = _building_evidence()
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
    assert decision.max_capital_pct == pytest.approx(0.90)


def test_building_rip_ftv_rank_one_gets_max_lots():
    from unittest.mock import patch

    from app.engines.auto_trader import _building_rip_ftv_policy_max_lots
    from app.engines.capital_allocator import RankedAllocation
    from app.engines.trade_ranking import FtvAuthorization

    decision = FtvAuthorization(
        "BUILDING_RIP_FTV", "ok", max_capital_pct=0.90,
    )
    allocation = RankedAllocation(
        rank=1,
        budgetInr=90_000,
        remainingBeforeInr=100_000,
        cashReserveInr=0,
        capitalBaseInr=100_000,
        committedInr=0,
        weight=0.90,
    )
    candidate = type(
        "Cand",
        (),
        {
            "alert": {
                "buildingLiftHelping": True,
                "buildingRipHelpersOk": True,
                "ictBuildingRipReady": True,
            },
            "pretrade_meta": {},
        },
    )()
    with patch(
        "app.engines.capital_allocator.max_lots_for_capital_pct",
        return_value=28,
    ) as max_lots:
        lots, authorized = _building_rip_ftv_policy_max_lots(
            lots=4,
            symbol="SENSEX",
            premium=131.0,
            policy_decision=decision,
            allocation=allocation,
            candidate=candidate,
            timing_meta={"assessment": "GOOD", "action": "allow"},
        )
    assert authorized is True
    assert lots == 28
    max_lots.assert_called_once()
    args = max_lots.call_args[0]
    assert args[0] == "SENSEX"
    assert args[1] == 131.0
    assert float(args[2]) >= 0.90


def test_building_rip_ftv_no_helpers_no_max_lots():
    from app.engines.auto_trader import _building_rip_ftv_policy_max_lots
    from app.engines.capital_allocator import RankedAllocation
    from app.engines.trade_ranking import FtvAuthorization

    decision = FtvAuthorization(
        "BUILDING_RIP_FTV", "ok", max_capital_pct=0.90,
    )
    allocation = RankedAllocation(
        rank=1,
        budgetInr=90_000,
        remainingBeforeInr=100_000,
        cashReserveInr=0,
        capitalBaseInr=100_000,
        committedInr=0,
        weight=0.90,
    )
    candidate = type("Cand", (), {"alert": {}, "pretrade_meta": {}})()
    lots, authorized = _building_rip_ftv_policy_max_lots(
        lots=4,
        symbol="SENSEX",
        premium=131.0,
        policy_decision=decision,
        allocation=allocation,
        candidate=candidate,
    )
    assert authorized is False
    assert lots == 4


def test_building_rip_ftv_allows_chase_timing_while_ripping():
    evidence = _building_evidence(timingAssessment="CHASE")
    ranking = rank_trade_evidence(evidence)
    decision = ftv_authorization_policy(
        ranking.get("evidence") or evidence,
        ranking,
        snapshot_available=True,
        atm_itm_allowed=True,
        building_rip_ftv_enabled=True,
    )
    assert decision.mode == "BUILDING_RIP_FTV"


def test_building_rip_ftv_blocks_without_helpers():
    evidence = _building_evidence(
        buildingRipHelpersOk=False,
        orderflowPositive=False,
        volumeAwaken=False,
        cvdBuying=False,
        cvdAcceleration=False,
        displacement=False,
    )
    ranking = rank_trade_evidence(evidence)
    # Without orderflow, ranking may still grade; policy must refuse.
    decision = ftv_authorization_policy(
        {
            **(ranking.get("evidence") or evidence),
            "buildingRipHelpersOk": False,
            "orderflowPositive": False,
            "volumeAwaken": False,
            "cvdBuying": False,
            "cvdAcceleration": False,
            "displacement": False,
            "buildingRipReady": True,
        },
        {**ranking, "grade": "A"},
        snapshot_available=True,
        atm_itm_allowed=True,
        building_rip_ftv_enabled=True,
        top_ftv_a_enabled=True,
    )
    assert decision.mode is None
    assert "blocked" in decision.reason or "requires" in decision.reason or decision.reason.startswith("top_ftv")


def test_building_rip_ftv_blocks_cold_negative_velocity():
    evidence = _building_evidence(velocity3s=-0.5, velocity9s=-0.2)
    ranking = rank_trade_evidence(evidence)
    decision = ftv_authorization_policy(
        ranking.get("evidence") or evidence,
        ranking,
        snapshot_available=True,
        atm_itm_allowed=True,
        building_rip_ftv_enabled=True,
    )
    assert decision.mode is None
    assert decision.reason == "ftv_elite_top_only_timing_blocked"


def test_building_rip_ftv_respects_disable_switch():
    evidence = _building_evidence()
    ranking = rank_trade_evidence(evidence)
    decision = ftv_authorization_policy(
        ranking.get("evidence") or evidence,
        ranking,
        snapshot_available=True,
        atm_itm_allowed=True,
        building_rip_ftv_enabled=False,
    )
    assert decision.mode is None


@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.engines.worst_day_itm_fade.worst_day_defensive_session_active", return_value=False)
@patch("app.engines.worst_day_guard.session_entry_policy", return_value=("NORMAL", {}))
@patch("app.engines.dual_mode_strategy.resolve_trading_session_mode", return_value=("NORMAL", {}))
def test_readiness_stamps_helpers_on_alert(_mode, _policy, _worst, mock_settings):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.engines.ict_breakout_monitor import building_rip_bullish_readiness
    from app.models.schemas import (
        Breadth,
        MarketPhase,
        Side,
        SpotChart,
        SymbolSnapshot,
    )

    mock_settings.return_value = Settings()
    IST = ZoneInfo("Asia/Kolkata")
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=55.0,
        spot=76900.0,
        atmStrike=76900.0,
        breadth=Breadth(bias="BEARISH", score=70.0, aligned=True),
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=-0.08,
            momentum10Pct=-0.04,
            momentum15Pct=-0.02,
        ),
    )
    alert = {
        "tier": "BUILDING",
        "side": "PUT",
        "strike": 76900.0,
        "velocity3s": 2.0,
        "velocity9s": 1.2,
        "volumeSurge": 2.2,
        "explosionScore": 55.0,
        "ictBaseRelativeMovePct": 6.0,
        "ictLocalSwingBase": True,
        "ictVolumeAwakening": True,
        "volume": 80_000,
        "cvdBuying": True,
    }
    ok, reason = building_rip_bullish_readiness(snap=snap, alert=alert)
    assert ok is True
    assert reason in {
        "building_local_base_lift_ready",
        "building_rip_bullish_ready",
    }
    assert alert.get("ictBuildingRipReady") is True
    assert alert.get("buildingRipHelpersOk") is True
    assert isinstance(alert.get("buildingRipHelpers"), list)
    assert len(alert["buildingRipHelpers"]) >= 1
