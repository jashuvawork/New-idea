"""Balanced causal policy for strict S and winner-like top FTV A."""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.auto_trader import (
    _open_from_candidate,
    _top_ftv_a_policy_max_lots,
)
from app.engines.capital_allocator import (
    CapitalSnapshot,
    RankedAllocation,
    max_lots_for_capital_pct,
)
from app.engines.pretrade_validator import validate_candidate
from app.engines.trade_ranking import (
    ftv_authorization_policy,
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
        "cvdBuying": True,
        "cvdAcceleration": True,
        "flatVerticalQuality": 90.0,
        "timingAssessment": "GOOD",
    }
    evidence.update(overrides)
    return evidence


def _decision(
    evidence,
    *,
    ranking=None,
    atm_itm=True,
    rank=None,
    require_rank=False,
    fallback_enabled=True,
):
    ranking = ranking or rank_trade_evidence(evidence)
    return ftv_authorization_policy(
        ranking.get("evidence") or evidence,
        ranking,
        snapshot_available=True,
        atm_itm_allowed=atm_itm,
        allocation_rank=rank,
        require_allocation_rank_one=require_rank,
        top_ftv_a_enabled=fallback_enabled,
    )


def _reconstructed_ftv_a(**overrides):
    evidence = _s_evidence(
        tier="EXPLODING",
        explosionScore=96.0,
        tqs=58.0,
        velocity3s=3.11,
        velocity9s=2.5,
        localBaseMovePct=14.4,
        firstLift=True,
        armedBaseLaunch=False,
        eliteBaseReady=False,
        flatThenVertical=True,
        activeBreakout=True,
        flatVerticalQuality=82.0,
    )
    evidence.update(overrides)
    return evidence


def test_strict_s_rank_one_authorization_and_full_sleeve_path_are_unchanged():
    evidence = _s_evidence()
    ranking = rank_trade_evidence(evidence)
    assert ranking["grade"] == "S"
    assert ranking["topRankEligible"] is True
    assert ranking["fullSleeveEligible"] is True
    decision = _decision(
        evidence,
        ranking=ranking,
        rank=1,
        require_rank=True,
    )
    assert (decision.mode, decision.reason) == ("S_STRICT", "ok")
    assert decision.max_capital_pct is None


def test_reconstructed_aug6_winner_like_top_exploding_a_passes_ordinary_fallback():
    # Reconstructed current-data profile: historical rows do not prove v9/CVD.
    evidence = _reconstructed_ftv_a()
    ranking = rank_trade_evidence(evidence)
    decision = _decision(
        evidence, ranking=ranking, rank=1, require_rank=True
    )
    assert ranking["grade"] == "A"
    assert ranking["fullSleeveEligible"] is False
    assert decision.mode == "TOP_FTV_A"
    assert decision.max_capital_pct == pytest.approx(0.90)
    assert decision.exceptional_extension is False


def test_reconstructed_aug12_extended_elite_a_requires_extreme_acceleration():
    # Reconstructed current-data profile: v9/CVD are assumptions, not counterfactual proof.
    base = _reconstructed_ftv_a(
        tier="ELITE",
        localBaseMovePct=33.1,
        explosionScore=98.0,
        flatVerticalQuality=92.0,
        tqs=62.0,
    )
    weak = _decision({**base, "velocity3s": 4.9, "velocity9s": 2.5})
    strong = _decision({**base, "velocity3s": 33.06, "velocity9s": 3.0})
    assert weak.reason == "top_ftv_a_extended_requires_exceptional_acceleration"
    assert strong.mode == "TOP_FTV_A"
    assert strong.max_capital_pct == pytest.approx(0.90)
    assert strong.exceptional_extension is True


@pytest.mark.parametrize(
    "evidence",
    [
        _reconstructed_ftv_a(),
        _reconstructed_ftv_a(
            tier="ELITE",
            localBaseMovePct=33.1,
            explosionScore=98.0,
            flatVerticalQuality=92.0,
            tqs=62.0,
            velocity3s=8.0,
            velocity9s=3.0,
        ),
    ],
)
def test_top_ftv_a_rank_one_uses_policy_authorized_max_lots_and_exceptional_risk_context(
    evidence,
):
    ranking = rank_trade_evidence(evidence)
    decision = _decision(evidence, ranking=ranking, rank=1, require_rank=True)
    allocation = RankedAllocation(
        rank=1,
        budgetInr=90_000,
        remainingBeforeInr=100_000,
        cashReserveInr=0,
        capitalBaseInr=100_000,
        committedInr=0,
        weight=0.90,
    )

    # A causal grade is never itself a sizing token; only the final policy decision is.
    assert ranking["fullSleeveEligible"] is False
    with patch(
        "app.engines.capital_allocator.max_lots_for_capital_pct",
        return_value=31,
    ) as max_lots:
        lots, authorized = _top_ftv_a_policy_max_lots(
            lots=4,
            symbol="NIFTY",
            premium=44.0,
            policy_decision=decision,
            allocation=allocation,
        )

    assert authorized is True
    assert lots == 31
    max_lots.assert_called_once_with("NIFTY", 44.0, pytest.approx(0.90))
    assert Settings().explosion_exceptional_per_trade_max_loss_inr == 4_000


def test_top_ftv_a_rank_two_and_cached_a_ranking_cannot_trigger_max_lots():
    evidence = _reconstructed_ftv_a()
    cached_ranking = rank_trade_evidence(evidence)
    cached_ranking["fullSleeveEligible"] = True
    blocked = _decision(evidence, rank=2, require_rank=True)
    allocation = RankedAllocation(
        rank=2,
        budgetInr=25_000,
        remainingBeforeInr=100_000,
        cashReserveInr=0,
        capitalBaseInr=100_000,
        committedInr=0,
        weight=0.25,
    )

    lots, authorized = _top_ftv_a_policy_max_lots(
        lots=4,
        symbol="NIFTY",
        premium=44.0,
        policy_decision=blocked,
        allocation=allocation,
    )

    assert cached_ranking["fullSleeveEligible"] is True
    assert blocked.allowed is False
    assert (lots, authorized) == (4, False)


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_max_lots_never_exceed_ninety_percent_of_available_capital(side):
    premium = 44.0
    lot_size = 65
    available = 100_000.0
    with (
        patch(
            "app.engines.capital_allocator.get_capital_snapshot",
            return_value=CapitalSnapshot(availableMarginInr=available),
        ),
        patch("app.engines.capital_allocator._effective_capital_inr", side_effect=lambda value: value),
        patch("app.engines.capital_allocator.lot_multiplier", return_value=lot_size),
    ):
        lots = max_lots_for_capital_pct("NIFTY", premium, 0.90)

    assert side in {Side.CALL, Side.PUT}
    assert lots * premium * lot_size <= available * 0.90
    assert (lots + 1) * premium * lot_size > available * 0.90


AUG18_SIX_A_PATTERNS = [
    (
        "SENSEX77600 A84 armed",
        dict(localBaseMovePct=11.5, velocity3s=0.81, velocity9s=2.03,
             firstLift=False, armedBaseLaunch=True),
    ),
    (
        "NIFTY24250 A100 no armed base",
        dict(localBaseMovePct=32.7, velocity3s=1.98, velocity9s=0.59,
             firstLift=False, armedBaseLaunch=False),
    ),
    (
        "NIFTY24200 A100 armed",
        dict(localBaseMovePct=9.6, velocity3s=2.15, velocity9s=1.36,
             firstLift=False, armedBaseLaunch=True),
    ),
    (
        "SENSEX77400 A98 first lift",
        dict(localBaseMovePct=28.7, velocity3s=1.45, velocity9s=2.09),
    ),
    (
        "NIFTY24200 reentry A100",
        dict(localBaseMovePct=28.7, velocity3s=0.75, exhaustedReentry=True),
    ),
    (
        "NIFTY24200 A98.8 bare FTV",
        dict(localBaseMovePct=2.1, velocity3s=2.32, velocity9s=2.5,
             firstLift=False, armedBaseLaunch=False, eliteBaseReady=False),
    ),
]


@pytest.mark.parametrize(("name", "overrides"), AUG18_SIX_A_PATTERNS)
def test_all_six_supplied_aug18_loss_profiles_remain_blocked(name, overrides):
    decision = _decision(_reconstructed_ftv_a(**overrides))
    lots, max_sized = _top_ftv_a_policy_max_lots(
        lots=4,
        symbol="NIFTY",
        premium=44.0,
        policy_decision=decision,
        allocation=RankedAllocation(1, 90_000, 100_000, 0, 100_000, 0, 0.90),
    )
    assert decision.allowed is False, name
    assert (lots, max_sized) == (4, False), name


@pytest.mark.parametrize("side", ["CALL", "PUT"])
def test_top_ftv_a_is_ce_pe_symmetric(side):
    decision = _decision(
        _reconstructed_ftv_a(side=side), rank=1, require_rank=True
    )
    assert decision.mode == "TOP_FTV_A"


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"timingAssessment": "CHASE"}, "top_ftv_a_timing_blocked"),
        ({"timingAssessment": "FAILED_LAUNCH"}, "ftv_elite_top_only_timing_blocked"),
        ({"faded": True}, "ftv_elite_top_only_timing_blocked"),
        ({"exhaustedReentry": True}, "ftv_elite_top_only_timing_blocked"),
    ],
)
def test_fallback_requires_clean_timing(mutation, reason):
    assert _decision(_reconstructed_ftv_a(**mutation)).reason == reason


@pytest.mark.parametrize(
    "mutation",
    [
        {"cvdBuying": False},
        {"cvdAcceleration": False},
    ],
)
def test_missing_cvd_still_admits_winner_local_base_ordinary_sleeve(mutation):
    decision = _decision(_reconstructed_ftv_a(**mutation), rank=1, require_rank=True)
    assert decision.mode == "WINNER_LOCAL_BASE"
    assert decision.max_capital_pct == pytest.approx(0.35)


def test_bare_raw_elite_and_non_ftv_are_blocked():
    # No FTV structure and no armed/elite/first-lift → not auth-grade FTV.
    bare = _reconstructed_ftv_a(
        firstLift=False,
        armedBaseLaunch=False,
        eliteBaseReady=False,
        flatThenVertical=False,
        activeBreakout=False,
    )
    non_ftv = _reconstructed_ftv_a(
        flatThenVertical=False, activeBreakout=False
    )
    assert _decision(bare).reason == "ftv_elite_top_only_requires_ftv"
    assert _decision(non_ftv).reason == "ftv_elite_top_only_requires_ftv"


def test_early_ftv_without_flag_triggers_is_now_fresh():
    """FTV+heat in pad is fresh even when armed/first-lift flags are off."""
    early = _reconstructed_ftv_a(
        firstLift=False,
        armedBaseLaunch=False,
        eliteBaseReady=False,
        localBaseMovePct=13.5,
    )
    decision = _decision(early, rank=1, require_rank=True)
    assert decision.allowed is True
    assert decision.mode in {"TOP_FTV_A", "WINNER_LOCAL_BASE", "S_STRICT"}


def test_fallback_blocks_rank_two_and_more_than_40pct_extension():
    rank_two = _decision(
        _reconstructed_ftv_a(), rank=2, require_rank=True
    )
    too_extended = _decision(
        _reconstructed_ftv_a(
            localBaseMovePct=40.1,
            velocity3s=8.0,
            velocity9s=4.0,
            flatVerticalQuality=95.0,
        )
    )
    assert rank_two.reason == "winner_local_base_requires_allocation_rank_1"
    assert too_extended.reason == "top_ftv_a_extension_above_40pct"


def test_otm_top_ftv_a_is_blocked_and_never_max_sized():
    decision = _decision(
        _reconstructed_ftv_a(),
        atm_itm=False,
        rank=1,
        require_rank=True,
    )
    lots, max_sized = _top_ftv_a_policy_max_lots(
        lots=4,
        symbol="NIFTY",
        premium=44.0,
        policy_decision=decision,
        allocation=RankedAllocation(1, 90_000, 100_000, 0, 100_000, 0, 0.90),
    )

    assert decision.reason == "ftv_elite_top_only_requires_atm_itm"
    assert (lots, max_sized) == (4, False)


def test_disabling_fallback_restores_strict_s_only():
    decision = _decision(_reconstructed_ftv_a(), fallback_enabled=False)
    assert decision.mode is None
    assert decision.reason == "ftv_elite_top_only_requires_s"


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
            "flatVerticalQuality": 90.0,
            "orderflowConfirmed": True,
            "optionCvdBuying": True,
        },
    )


def test_pretrade_policy_is_default_enabled_and_disable_restores_legacy():
    candidate = _candidate()
    candidate.explosion_event.velocity_3s = 1.2
    candidate.alert["velocity3s"] = 1.2
    candidate.explosion_event.velocity_9s = 1.2
    candidate.alert["velocity9s"] = 1.2

    enabled = Settings(
        controlled_trading_enabled=False,
        top_ftv_a_enabled=False,
    )
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


def test_missing_live_cvd_is_blocked_on_preorder_execution_recompute():
    candidate = _candidate()
    candidate.tqs = 58.0
    candidate.explosion_event.explosion_score = 96.0
    candidate.explosion_event.velocity_3s = 3.11
    candidate.explosion_event.velocity_9s = 2.5
    candidate.alert.update(
        {
            "ictBaseRelativeMovePct": 14.4,
            "ictArmedBaseLaunch": False,
            "ictFirstLift": True,
            "flatVerticalQuality": 82.0,
        }
    )
    allocation = RankedAllocation(
        rank=1,
        budgetInr=25_000,
        remainingBeforeInr=100_000,
        cashReserveInr=0,
        capitalBaseInr=100_000,
        committedInr=0,
        weight=0.25,
    )
    settings = Settings(
        controlled_trading_enabled=False,
        winner_local_base_enabled=False,
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
        patch(
            "app.engines.advanced_indicators.option_cvd_confirms_buying",
            return_value=False,
        ),
        patch(
            "app.engines.advanced_indicators.option_cvd_acceleration_confirms_buying",
            return_value=True,
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
    assert reason == "top_ftv_a_requires_option_cvd_buying"


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
