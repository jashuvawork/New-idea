"""Hard execution policy for causal S-grade flat-to-vertical launches."""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.auto_trader import _open_from_candidate
from app.engines.capital_allocator import RankedAllocation
from app.engines.pretrade_validator import validate_candidate
from app.engines.trade_ranking import (
    ftv_elite_top_policy,
    rank_trade_evidence,
)
from app.engines.trade_selector import EntryCandidate
from app.models.schemas import (
    AutoTraderState,
    MarketPhase,
    Side,
    StrategyType,
    SymbolSnapshot,
)
from app.services.radar_archive import read_archive_entries, record_top_radars

IST = ZoneInfo("Asia/Kolkata")


def _s_evidence(**overrides):
    evidence = {
        "mode": "explosion",
        "tier": "EXPLODING",
        "explosionScore": 100.0,
        "tqs": 55.6,
        "velocity3s": 3.69,
        "velocity9s": 4.13,
        "localBaseMovePct": 24.4,
        "armedBaseLaunch": True,
        "flatThenVertical": True,
        "activeBreakout": True,
        "orderflowPositive": True,
        "timingAssessment": "GOOD",
    }
    evidence.update(overrides)
    return evidence


def _decision(evidence, *, ranking=None, atm_itm=True, rank=None, require_rank=False):
    ranking = ranking or rank_trade_evidence(evidence)
    return ftv_elite_top_policy(
        ranking.get("evidence") or evidence,
        ranking,
        snapshot_available=True,
        atm_itm_allowed=atm_itm,
        allocation_rank=rank,
        require_allocation_rank_one=require_rank,
    )


AUG18_SIX_A_PATTERNS = [
    ("NIFTY 24200 PE", 100.0, 1.20, 1.10, 18.0),
    ("NIFTY 24250 PE", 96.0, 1.25, 1.20, 19.0),
    ("NIFTY 24300 PE", 92.0, 1.30, 1.25, 20.0),
    ("NIFTY 24200 CE", 94.0, 1.10, 1.05, 17.0),
    ("NIFTY 24250 CE", 90.0, 1.35, 1.30, 21.0),
    ("NIFTY 24300 CE", 88.0, 1.40, 1.35, 22.0),
]


@pytest.mark.parametrize(
    ("name", "score", "v3", "v9", "base_move"),
    AUG18_SIX_A_PATTERNS,
)
def test_aug18_six_a_grade_patterns_are_rejected(name, score, v3, v9, base_move):
    evidence = _s_evidence(
        explosionScore=score,
        velocity3s=v3,
        velocity9s=v9,
        localBaseMovePct=base_move,
    )
    ranking = rank_trade_evidence(evidence)

    assert ranking["grade"] == "A", name
    assert _decision(evidence, ranking=ranking) == (
        False,
        "ftv_elite_top_only_requires_s",
    )


def test_raw_elite_score_100_without_s_ranking_is_rejected():
    evidence = _s_evidence(tier="ELITE", velocity3s=1.2, velocity9s=1.2)
    ranking = rank_trade_evidence(evidence)

    assert evidence["explosionScore"] == 100.0
    assert ranking["signalTier"] == "ELITE"
    assert ranking["grade"] == "A"
    assert _decision(evidence, ranking=ranking)[1] == "ftv_elite_top_only_requires_s"


@pytest.mark.parametrize("side", ["CALL", "PUT"])
def test_24350_style_s_armed_ftv_is_symmetric_and_requires_rank_one(side):
    evidence = _s_evidence(side=side)
    ranking = rank_trade_evidence(evidence)

    assert ranking["grade"] == "S"
    assert ranking["topRankEligible"] is True
    assert _decision(
        evidence,
        ranking=ranking,
        rank=1,
        require_rank=True,
    ) == (True, "ok")
    assert _decision(
        evidence,
        ranking=ranking,
        rank=2,
        require_rank=True,
    )[1] == "ftv_elite_top_only_requires_allocation_rank_1"


def test_s_without_actual_ftv_is_rejected():
    evidence = _s_evidence(
        armedBaseLaunch=False,
        eliteBaseReady=False,
        flatThenVertical=False,
        activeBreakout=False,
    )
    ranking = {"grade": "S", "topRankEligible": True}

    assert _decision(evidence, ranking=ranking)[1] == "ftv_elite_top_only_requires_ftv"


def test_a_grade_ftv_and_otm_are_rejected():
    a_evidence = _s_evidence(velocity3s=1.2, velocity9s=1.2)
    assert _decision(a_evidence)[1] == "ftv_elite_top_only_requires_s"
    assert _decision(_s_evidence(), atm_itm=False)[1] == (
        "ftv_elite_top_only_requires_atm_itm"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"faded": True},
        {"exhaustedReentry": True},
        {"timingAssessment": "FAILED_LAUNCH", "timingAction": "block"},
        {"velocity3s": -0.1},
        {"velocity9s": -0.1},
    ],
)
def test_faded_exhausted_or_failed_launch_is_rejected(mutation):
    evidence = _s_evidence(**mutation)
    ranking = {"grade": "S", "topRankEligible": True}

    assert _decision(evidence, ranking=ranking)[1] == (
        "ftv_elite_top_only_timing_blocked"
    )


def _snapshot(side: Side = Side.PUT) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime(2026, 8, 18, 10, 40, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24201.7,
        atmStrike=24200.0,
        tradeQualityScore=55.6,
    )


def _candidate(side: Side = Side.PUT) -> EntryCandidate:
    strike = 24350.0 if side == Side.PUT else 24050.0
    event = SimpleNamespace(
        velocity_3s=3.69,
        velocity_9s=4.13,
        volume_surge=2.5,
        volume=27_127_300,
        explosion_score=100.0,
        tier="EXPLODING",
        daily_move_pct=35.0,
        peak_move_pct=42.0,
    )
    return EntryCandidate(
        symbol="NIFTY",
        snap=_snapshot(side),
        mode="explosion",
        score=120.0,
        side=side,
        strike=strike,
        premium=58.0,
        strategy_type=StrategyType.EXPLOSIVE,
        confidence=100.0,
        tqs=55.6,
        tier="EXPLODING",
        explosion_event=event,
        alert={
            "side": side.value,
            "strike": strike,
            "tier": "EXPLODING",
            "explosionScore": 100.0,
            "velocity3s": 3.69,
            "velocity9s": 4.13,
            "ictBaseRelativeMovePct": 24.4,
            "ictFlatThenVertical": True,
            "ictBreakout": True,
            "ictArmedBaseLaunch": True,
            "ictVolumeAwakening": True,
        },
    )


def test_pretrade_policy_is_default_enabled_and_disable_restores_legacy():
    candidate = _candidate()
    candidate.explosion_event.velocity_3s = 1.2
    candidate.alert["velocity3s"] = 1.2
    candidate.explosion_event.velocity_9s = 1.2
    candidate.alert["velocity9s"] = 1.2

    enabled = Settings(controlled_trading_enabled=False)
    disabled = Settings(
        controlled_trading_enabled=False,
        ftv_elite_top_only_enabled=False,
    )
    with patch("app.engines.pretrade_validator.get_settings", return_value=enabled):
        ok, reason, meta = validate_candidate(candidate, AutoTraderState())
    assert ok is False
    assert reason == "ftv_elite_top_only_requires_s"
    assert meta["ftvEliteTopPolicy"]["passed"] is False

    with patch("app.engines.pretrade_validator.get_settings", return_value=disabled):
        assert validate_candidate(candidate, AutoTraderState()) == (True, "ok", {})


def test_allocation_rank_two_is_rejected_before_order_path():
    candidate = _candidate()
    settings = Settings(
        controlled_trading_enabled=False,
        ftv_elite_top_only_enabled=True,
    )
    allocation = RankedAllocation(
        rank=2,
        budgetInr=25_000,
        remainingBeforeInr=100_000,
        cashReserveInr=0,
        capitalBaseInr=100_000,
        committedInr=60_000,
        weight=0.25,
    )
    with (
        patch("app.engines.auto_trader.get_settings", return_value=settings),
        patch(
            "app.engines.session_mode_feedback.exhausted_ftv_reentry_blocked",
            return_value=(False, "ok"),
        ),
        patch(
            "app.engines.explosion_entry_guards.detect_faded_vertical_rip",
            return_value=(False, {}),
        ),
    ):
        opened, reason = asyncio.run(
            _open_from_candidate(
                candidate,
                AutoTraderState(),
                snapshots={"NIFTY": candidate.snap},
                allocation=allocation,
            )
        )

    assert opened is False
    assert reason == "ftv_elite_top_only_requires_allocation_rank_1"


def test_radar_archive_visibility_remains_for_a_and_b_candidates(tmp_path):
    settings = SimpleNamespace(
        trade_store_dir=str(tmp_path),
        radar_archive_enabled=True,
        radar_archive_dir="",
        radar_archive_top_n_per_day=100,
        radar_archive_retention_days=365,
        ftv_elite_top_only_enabled=True,
    )
    alerts = [
        {
            "side": "CALL",
            "strike": 24200.0,
            "premium": 80.0,
            "tier": "ELITE",
            "explosionScore": 100.0,
            "tradeable": True,
        },
        {
            "side": "PUT",
            "strike": 24250.0,
            "premium": 75.0,
            "tier": "BUILDING",
            "explosionScore": 62.0,
            "tradeable": False,
        },
    ]
    snap = SimpleNamespace(
        dataAvailable=True,
        timestamp=datetime(2026, 8, 18, 10, 40, tzinfo=IST),
        marketPhase="LIVE_MARKET",
        spot=24201.7,
        atmStrike=24200.0,
        optionExpiry="2026-08-20",
        tradeQualityScore=55.6,
        regime="TREND_EXPANSION",
        breadth={"bias": "NEUTRAL"},
        spotChart={"direction": "NEUTRAL"},
        pcr=1.0,
        maxPain=24200.0,
        indiaVix=13.0,
        explosionAlerts=alerts,
    )

    with patch("app.services.radar_archive.get_settings", return_value=settings):
        assert record_top_radars(
            {"NIFTY": snap},
            now=datetime(2026, 8, 18, 10, 40, tzinfo=IST),
        ) == 2
        rows = read_archive_entries("2026-08-18")

    assert {row["tier"] for row in rows} == {"ELITE", "BUILDING"}
