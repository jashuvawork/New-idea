"""Sep-9-style best trade policy — near-base max lots, block deep chop chase."""

from unittest.mock import MagicMock

from app.engines.best_trade_policy import (
    best_trade_chop_deep_chase_blocked,
    best_trade_near_base_assessment,
    cheap_base_strike_eligible,
    cheap_base_strike_rank_bonus,
    deep_itm_chase_strike,
    deprioritize_deep_itm_when_cheap_base_present,
    elite_base_setup_allowed,
    mid_rip_best_trade_candidate,
    timing_allows_best_trade_full_size,
)
from app.models.schemas import Side, SymbolSnapshot
from tests.mock_defaults import settings_mock


def test_near_base_ftv_allows_cold_base_max_lots():
    s = settings_mock()
    timing = {"assessment": "COLD_BASE", "structuredColdBase": True}
    assessment = {
        "eliteScore": 95.0,
        "localBasePct": 12.0,
        "setup": "FTV",
    }
    assert best_trade_near_base_assessment(assessment, settings=s)
    assert timing_allows_best_trade_full_size(timing, assessment, settings=s)


def test_deep_itm_chop_trap_blocked():
    s = settings_mock()
    cand = MagicMock(mode="explosion", premium=242.42, alert={}, tier="ELITE")
    assessment = {
        "eliteScore": 72.0,
        "localBasePct": 16.4,
        "setup": "EXPLOSIVE",
        "dayMode": "EXPIRY WORST",
    }
    blocked, reason = best_trade_chop_deep_chase_blocked(
        cand,
        {"fakeExplosionTrap": True},
        assessment,
        day_mode="EXPIRY WORST",
        settings=s,
    )
    assert blocked is True
    assert reason == "best_trade_block_chop_deep_itm_chase"


def test_cheap_near_base_not_deep_chase_blocked():
    s = settings_mock()
    cand = MagicMock(mode="explosion", premium=52.0)
    assessment = {
        "eliteScore": 92.0,
        "localBasePct": 11.0,
        "setup": "FTV",
        "dayMode": "EXPIRY WORST",
    }
    blocked, _ = best_trade_chop_deep_chase_blocked(
        cand,
        {"fakeExplosionTrap": True},
        assessment,
        day_mode="EXPIRY WORST",
        settings=s,
    )
    assert blocked is False


def test_elite_base_setup_allows_ftv_not_explosive_chase():
    s = settings_mock(elite_trade_v_rip_only_enabled=False)
    assert elite_base_setup_allowed("FTV", settings=s) is True
    assert elite_base_setup_allowed("V", settings=s) is True
    assert elite_base_setup_allowed("EXPLOSIVE", settings=s) is False


def _sep15_nifty_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp="2026-09-15T10:05:00+05:30",
        marketPhase="LIVE_MARKET",
        spot=23350.0,
        atmStrike=23350.0,
        dataAvailable=True,
    )


def _explosion_candidate(
    *,
    strike: float,
    premium: float,
    snap: SymbolSnapshot,
    side: Side = Side.PUT,
    alert: dict | None = None,
) -> MagicMock:
    cand = MagicMock(
        mode="explosion",
        symbol="NIFTY",
        side=side,
        strike=strike,
        premium=premium,
        snap=snap,
        alert=alert or {},
    )
    return cand


def test_cheap_base_strike_eligible_sep15_23150_pe():
    s = settings_mock()
    snap = _sep15_nifty_snap()
    alert = {
        "localBaseMovePct": 14.0,
        "offLowMovePct": 18.0,
        "premium": 24.0,
    }
    cand = _explosion_candidate(strike=23150.0, premium=24.0, snap=snap, alert=alert)
    assert cheap_base_strike_eligible(cand, alert, snap, settings=s) is True


def test_deep_itm_chase_strike_sep15_23500_pe():
    s = settings_mock()
    snap = _sep15_nifty_snap()
    alert = {"premium": 242.42}
    cand = _explosion_candidate(strike=23500.0, premium=242.42, snap=snap, alert=alert)
    assert deep_itm_chase_strike(cand, alert, snap, settings=s) is True


def test_deprioritize_drops_deep_itm_when_cheap_pe_present():
    s = settings_mock()
    snap = _sep15_nifty_snap()
    cheap = _explosion_candidate(
        strike=23150.0,
        premium=24.0,
        snap=snap,
        alert={"localBaseMovePct": 14.0, "offLowMovePct": 18.0},
    )
    deep = _explosion_candidate(
        strike=23500.0,
        premium=242.42,
        snap=snap,
        alert={"localBaseMovePct": 16.4},
    )
    kept = deprioritize_deep_itm_when_cheap_base_present([cheap, deep], settings=s)
    assert cheap in kept
    assert deep not in kept
    assert len(kept) == 1


def test_deprioritize_keeps_deep_itm_when_no_cheap_peer():
    s = settings_mock()
    snap = _sep15_nifty_snap()
    deep = _explosion_candidate(
        strike=23500.0,
        premium=242.42,
        snap=snap,
        alert={"localBaseMovePct": 16.4},
    )
    kept = deprioritize_deep_itm_when_cheap_base_present([deep], settings=s)
    assert kept == [deep]


def test_mid_rip_elite_bypasses_deep_chase_block():
    s = settings_mock()
    snap = _sep15_nifty_snap()
    alert = {"fastVerticalBurst": True, "tier": "ELITE"}
    cand = _explosion_candidate(
        strike=23500.0,
        premium=242.42,
        snap=snap,
        alert=alert,
    )
    assessment = {
        "eliteScore": 95.5,
        "localBasePct": 16.4,
        "setup": "V",
        "dayMode": "EXPIRY WORST",
    }
    assert mid_rip_best_trade_candidate(cand, alert, assessment, settings=s) is True
    blocked, reason = best_trade_chop_deep_chase_blocked(
        cand,
        {"fakeExplosionTrap": True},
        assessment,
        day_mode="EXPIRY WORST",
        settings=s,
    )
    assert blocked is False
    assert reason == ""


def test_deprioritize_keeps_mid_rip_deep_with_cheap_peer():
    s = settings_mock()
    snap = _sep15_nifty_snap()
    cheap = _explosion_candidate(
        strike=23150.0,
        premium=24.0,
        snap=snap,
        alert={"localBaseMovePct": 14.0, "offLowMovePct": 18.0},
    )
    deep = _explosion_candidate(
        strike=23500.0,
        premium=242.42,
        snap=snap,
        alert={"fastVerticalBurst": True, "localBaseMovePct": 16.4, "tier": "ELITE"},
    )
    kept = deprioritize_deep_itm_when_cheap_base_present([cheap, deep], settings=s)
    assert cheap in kept
    assert deep in kept
    assert len(kept) == 2


def test_cheap_base_rank_bonus_beats_deep_penalty():
    s = settings_mock()
    snap = _sep15_nifty_snap()
    cheap = _explosion_candidate(
        strike=23150.0,
        premium=24.0,
        snap=snap,
        alert={"localBaseMovePct": 14.0, "offLowMovePct": 18.0},
    )
    deep = _explosion_candidate(
        strike=23500.0,
        premium=242.42,
        snap=snap,
        alert={"localBaseMovePct": 16.4},
    )
    cheap_bonus = cheap_base_strike_rank_bonus(
        cheap,
        alert=cheap.alert,
        elite_assessment={"setup": "FTV"},
        settings=s,
    )
    deep_bonus = cheap_base_strike_rank_bonus(
        deep,
        alert=deep.alert,
        settings=s,
    )
    assert cheap_bonus == 45.0 + 12.0
    assert deep_bonus == -60.0
    assert cheap_bonus > deep_bonus
