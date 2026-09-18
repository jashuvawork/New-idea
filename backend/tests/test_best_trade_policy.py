"""Sep-9-style best trade policy — near-base max lots, block deep chop chase."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.best_trade_policy import (
    best_trade_chop_deep_chase_blocked,
    best_trade_near_base_assessment,
    call_momentum_rally_pe_parity_fingerprint,
    cheap_base_strike_eligible,
    cheap_base_strike_rank_bonus,
    deep_itm_chase_strike,
    deprioritize_deep_itm_when_cheap_base_present,
    elite_base_setup_allowed,
    expiry_cheap_otm_entry_blocked,
    mid_rip_best_trade_candidate,
    timing_allows_best_trade_full_size,
)
from app.engines.elite_score_engine import build_elite_assessment
from app.models.schemas import Side, SymbolSnapshot
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


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


def _sep15_nifty_snap(*, expiry: str | None = None) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp="2026-09-15T10:05:00+05:30",
        marketPhase="LIVE_MARKET",
        spot=23118.0,
        atmStrike=23100.0,
        dataAvailable=True,
        optionExpiry=expiry,
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


def test_cheap_base_strike_eligible_non_expiry():
    s = settings_mock()
    snap = _sep15_nifty_snap(expiry="2026-09-22")
    alert = {
        "localBaseMovePct": 14.0,
        "offLowMovePct": 18.0,
        "premium": 24.0,
    }
    cand = _explosion_candidate(strike=23150.0, premium=24.0, snap=snap, alert=alert)
    assert cheap_base_strike_eligible(cand, alert, snap, settings=s) is True


@patch("app.engines.expiry_day_guards._today_str", return_value="2026-09-15")
def test_expiry_blocks_cheap_otm_entry(_mock_today):
    s = settings_mock()
    snap = _sep15_nifty_snap(expiry="2026-09-15")
    alert = {"premium": 24.0}
    # 23000 PE is OTM with spot 23118 / ATM 23100 — Sep15 chain decayed to ₹0.05.
    cand = _explosion_candidate(strike=23000.0, premium=24.0, snap=snap, alert=alert)
    blocked, reason = expiry_cheap_otm_entry_blocked(cand, snap, alert, settings=s)
    assert blocked is True
    assert reason == "best_trade_block_expiry_cheap_otm"
    assert cheap_base_strike_eligible(cand, alert, snap, settings=s) is False


@patch("app.engines.expiry_day_guards._today_str", return_value="2026-09-15")
def test_expiry_allows_itm_mid_rip_not_cheap_otm(_mock_today):
    s = settings_mock()
    snap = _sep15_nifty_snap(expiry="2026-09-15")
    alert = {"premium": 242.42, "fastVerticalBurst": True, "tier": "ELITE"}
    cand = _explosion_candidate(strike=23500.0, premium=242.42, snap=snap, alert=alert)
    blocked, reason = expiry_cheap_otm_entry_blocked(cand, snap, alert, settings=s)
    assert blocked is False
    assert reason == ""


def _sensex_expiry_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp="2026-09-17T10:05:00+05:30",
        marketPhase="LIVE_MARKET",
        spot=74003.0,
        atmStrike=74000.0,
        dataAvailable=True,
        optionExpiry="2026-09-17",
    )


def _sensex_candidate(
    *,
    strike: float,
    premium: float,
    snap: SymbolSnapshot,
    side: Side = Side.CALL,
    alert: dict | None = None,
) -> MagicMock:
    return MagicMock(
        mode="explosion",
        symbol="SENSEX",
        side=side,
        strike=strike,
        premium=premium,
        snap=snap,
        alert=alert or {},
    )


@patch("app.engines.expiry_day_guards._today_str", return_value="2026-09-17")
def test_sensex_expiry_blocks_all_otm_not_just_cheap_band(_mock_today):
    s = settings_mock()
    snap = _sensex_expiry_snap()
    # 74500 CE @ ₹192 — OTM 500pt, above NIFTY cheap band but still worthless on expiry.
    alert = {"premium": 192.0}
    cand = _sensex_candidate(strike=74500.0, premium=192.0, snap=snap, side=Side.CALL, alert=alert)
    blocked, reason = expiry_cheap_otm_entry_blocked(cand, snap, alert, settings=s)
    assert blocked is True
    assert reason == "best_trade_block_expiry_otm_itm_atm_only"


@patch("app.engines.pe_win_ce_mirror.call_rally_entry_unlock_expiry_otm_bypass", return_value=True)
@patch("app.engines.expiry_day_guards._today_str", return_value="2026-09-17")
def test_sensex_expiry_otm_waived_for_rally_unlock_ce(_mock_today, _mock_bypass):
    s = settings_mock()
    snap = _sensex_expiry_snap()
    alert = {"premium": 192.0, "tier": "ELITE", "fastVerticalBurst": True}
    cand = _sensex_candidate(
        strike=74600.0, premium=192.0, snap=snap, side=Side.CALL, alert=alert,
    )
    blocked, reason = expiry_cheap_otm_entry_blocked(
        cand, snap, alert, state=MagicMock(), settings=s,
    )
    assert blocked is False
    assert reason == ""


@patch("app.engines.expiry_day_guards._today_str", return_value="2026-09-17")
def test_sensex_expiry_allows_atm_itm(_mock_today):
    s = settings_mock()
    snap = _sensex_expiry_snap()
    atm_alert = {"premium": 409.45}
    atm_cand = _sensex_candidate(
        strike=74000.0, premium=409.45, snap=snap, side=Side.CALL, alert=atm_alert,
    )
    blocked, reason = expiry_cheap_otm_entry_blocked(atm_cand, snap, atm_alert, settings=s)
    assert blocked is False

    itm_alert = {"premium": 326.0}
    itm_cand = _sensex_candidate(
        strike=74100.0, premium=326.0, snap=snap, side=Side.PUT, alert=itm_alert,
    )
    blocked, reason = expiry_cheap_otm_entry_blocked(itm_cand, snap, itm_alert, settings=s)
    assert blocked is False


def test_deep_itm_chase_strike_sep15_23500_pe():
    s = settings_mock()
    snap = _sep15_nifty_snap()
    alert = {"premium": 242.42}
    cand = _explosion_candidate(strike=23500.0, premium=242.42, snap=snap, alert=alert)
    assert deep_itm_chase_strike(cand, alert, snap, settings=s) is True


def test_deprioritize_drops_deep_itm_when_cheap_pe_present():
    s = settings_mock()
    snap = _sep15_nifty_snap(expiry="2026-09-22")
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
    snap = _sep15_nifty_snap(expiry="2026-09-22")
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
    snap = _sep15_nifty_snap(expiry="2026-09-22")
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


def _pe_parity_call_evidence(**kwargs):
    base = {
        "tier": "ELITE",
        "side": "CALL",
        "vRipReady": True,
        "armedBaseLaunch": True,
        "firstLift": True,
        "velocity3s": 5.2,
        "localBaseMovePct": 14.0,
        "flatVerticalQuality": 79.0,
        "explosionScore": 100.0,
        "timingAssessment": "GOOD",
        "timingAction": "allow",
    }
    base.update(kwargs)
    return base


def test_call_pe_parity_fingerprint_matches_elite_v():
    s = settings_mock()
    evidence = _pe_parity_call_evidence()
    ranking = {"grade": "A", "rankScore": 95.0}
    assessment = build_elite_assessment(evidence, ranking)
    assert call_momentum_rally_pe_parity_fingerprint(
        evidence, ranking, assessment, settings=s,
    )


def test_call_pe_parity_fingerprint_rejects_building_tier():
    s = settings_mock()
    evidence = _pe_parity_call_evidence(tier="BUILDING")
    ranking = {"grade": "A", "rankScore": 95.0}
    assessment = build_elite_assessment(evidence, ranking)
    assert not call_momentum_rally_pe_parity_fingerprint(
        evidence, ranking, assessment, settings=s,
    )


def test_call_pe_parity_fingerprint_rejects_shallow_grade_c():
    s = settings_mock()
    evidence = _pe_parity_call_evidence()
    ranking = {"grade": "C", "rankScore": 40.0}
    assessment = build_elite_assessment(evidence, ranking)
    assert not call_momentum_rally_pe_parity_fingerprint(
        evidence, ranking, assessment, settings=s,
    )


def test_call_pe_parity_fingerprint_rejects_cold_v3():
    s = settings_mock()
    evidence = _pe_parity_call_evidence(velocity3s=0.5)
    ranking = {"grade": "A", "rankScore": 95.0}
    assessment = build_elite_assessment(evidence, ranking)
    assert not call_momentum_rally_pe_parity_fingerprint(
        evidence, ranking, assessment, settings=s,
    )
