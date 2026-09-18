"""Sep-9-style best trades: near-base max lots, all day types / sessions.

One clean base entry (₹50→₹100+) at max lots = full-cap profit. Block deep ITM
chop traps; allow FTV/V mid-rip ELITE on expiry; block ₹18–80 OTM on expiry days.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

VALID_BEST_BASE_SETUPS = frozenset({"FTV", "V"})
_GOOD_TIMING = frozenset({"GOOD", "OK"})


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def best_trade_near_base_assessment(
    elite_assessment: Mapping[str, Any] | None,
    *,
    settings: Any = None,
) -> bool:
    """True when elite pipeline marks a Sep-9-style near-base best trade."""
    from app.config import get_settings

    settings = settings or get_settings()
    if not bool(getattr(settings, "best_trade_near_base_max_lots_enabled", True)):
        return False
    if not elite_assessment:
        return False
    score = _number(elite_assessment.get("eliteScore"))
    local = _number(elite_assessment.get("localBasePct"))
    setup = str(elite_assessment.get("setup") or "").upper()
    min_score = float(getattr(settings, "best_trade_near_base_min_elite_score", 90.0) or 90.0)
    max_local = float(getattr(settings, "best_trade_near_base_max_local_pct", 20.0) or 20.0)
    if score < min_score - 1e-6:
        return False
    if local > max_local + 1e-6:
        return False
    return setup in VALID_BEST_BASE_SETUPS


def timing_allows_best_trade_full_size(
    timing: Mapping[str, Any] | None,
    elite_assessment: Mapping[str, Any] | None = None,
    *,
    settings: Any = None,
) -> bool:
    """Extend max-lot sizing to structured COLD_BASE on near-base FTV/V elites."""
    from app.config import get_settings

    settings = settings or get_settings()
    if not timing:
        return True
    assessment = str(timing.get("assessment") or "").upper()
    if assessment in ("GOOD", "OK"):
        return True
    if bool(getattr(settings, "entry_timing_structured_cold_max_lots", False)):
        return assessment == "COLD_BASE"
    if assessment == "COLD_BASE" and best_trade_near_base_assessment(
        elite_assessment, settings=settings,
    ):
        return True
    return False


def _mid_rip_best_trade_signals(
    alert: Mapping[str, Any] | None,
    elite_assessment: Mapping[str, Any] | None,
    *,
    tier: str = "",
    settings: Any = None,
) -> bool:
    """Shared mid-rip ELITE signals for candidates and open trades."""
    from app.config import get_settings

    settings = settings or get_settings()
    if not bool(getattr(settings, "best_trade_mid_rip_entry_enabled", True)):
        return False

    alert = alert if isinstance(alert, Mapping) else {}
    if alert.get("fastVerticalBurst") or alert.get("buildingRipReady") or alert.get("buildingRip"):
        return True
    if alert.get("ictBuildingRip") or alert.get("ictFlatThenVertical"):
        return True

    assessment = elite_assessment or {}
    score = _number(assessment.get("eliteScore"))
    min_score = float(getattr(settings, "best_trade_mid_rip_min_elite_score", 88.0) or 88.0)
    setup = str(assessment.get("setup") or "").upper()
    tier_u = str(tier or alert.get("tier") or "").upper()
    if score >= min_score and setup in VALID_BEST_BASE_SETUPS | {"EXPLOSIVE"}:
        return True
    if tier_u in ("ELITE", "EXPLODING"):
        try:
            v3 = float(alert.get("velocity3s") or alert.get("liveVelocity3s") or 0)
        except (TypeError, ValueError):
            v3 = 0.0
        if v3 > 0:
            return True
    return False


def call_momentum_rally_pe_parity_fingerprint(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any] | None,
    elite_assessment: Mapping[str, Any] | None = None,
    *,
    settings: Any = None,
) -> bool:
    """True when CALL on MOMENTUM RALLY matches the morning PE winner entry bar.

    Narrow bypass — not a blanket CE unlock. Requires ELITE tier, FTV/V setup,
    grade A+, armed launch + first lift, hot v3, and near-base pad (~12–15%).
    """
    from app.config import get_settings
    from app.engines.rally_capture import _grade_meets_min

    settings = settings or get_settings()
    if not bool(
        getattr(settings, "elite_call_momentum_rally_pe_parity_bypass_enabled", True)
    ):
        return False

    evidence = evidence if isinstance(evidence, Mapping) else {}
    ranking = ranking if isinstance(ranking, Mapping) else {}
    assessment = elite_assessment if isinstance(elite_assessment, Mapping) else {}

    tier = str(evidence.get("tier") or "").upper()
    if tier != "ELITE":
        return False

    setup = str(assessment.get("setup") or "").upper()
    if setup not in VALID_BEST_BASE_SETUPS:
        return False

    grade = str(ranking.get("grade") or assessment.get("grade") or "").upper()
    min_grade = str(
        getattr(settings, "elite_call_momentum_rally_pe_parity_min_grade", "A") or "A"
    ).upper()
    if not _grade_meets_min(grade, min_grade):
        return False

    score = _number(assessment.get("eliteScore"))
    min_score = float(
        getattr(settings, "elite_call_momentum_rally_pe_parity_min_elite_score", 88.0)
        or 88.0
    )
    if score < min_score - 1e-6:
        return False

    local = _number(assessment.get("localBasePct") or evidence.get("localBaseMovePct"))
    max_local = float(
        getattr(settings, "elite_call_momentum_rally_pe_parity_max_local_pct", 15.0)
        or 15.0
    )
    if local > max_local + 1e-6:
        return False

    if not (
        evidence.get("armedBaseLaunch")
        and (
            evidence.get("firstLift")
            or evidence.get("activeBreakout")
            or evidence.get("displacement")
        )
    ):
        return False

    v3 = _number(evidence.get("velocity3s") or evidence.get("liveVelocity3s"))
    min_v3 = float(
        getattr(settings, "elite_call_momentum_rally_pe_parity_min_velocity3s", 1.2)
        or 1.2
    )
    if v3 < min_v3 - 1e-6:
        return False

    timing = str(evidence.get("timingAssessment") or assessment.get("timing") or "").upper()
    timing_action = str(evidence.get("timingAction") or "").lower()
    if timing_action in {"block", "reject"}:
        return False
    return timing in _GOOD_TIMING


def call_pe_parity_elite_fingerprint(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any] | None,
    elite_assessment: Mapping[str, Any] | None = None,
    *,
    settings: Any = None,
) -> bool:
    """Alias — ELITE CE matching the morning PE winner bar (any day mode)."""
    return call_momentum_rally_pe_parity_fingerprint(
        evidence, ranking, elite_assessment, settings=settings,
    )


def call_pe_parity_from_candidate(
    candidate: Any,
    snap: Any = None,
    *,
    settings: Any = None,
    state: Any = None,
) -> bool:
    """True when a live CALL candidate matches PE-parity or PE-win CE mirror."""
    side = str(
        getattr(getattr(candidate, "side", None), "value", getattr(candidate, "side", ""))
        or ""
    ).upper()
    if side != "CALL" or candidate is None:
        return False
    from app.engines.trade_ranking import rank_entry_candidate
    from app.engines.elite_score_engine import build_elite_assessment

    ranking = rank_entry_candidate(candidate, snapshot=snap)
    evidence = dict(ranking.get("evidence") or {})
    alert = getattr(candidate, "alert", None)
    if isinstance(alert, dict):
        evidence = {**alert, **evidence}
    ev = getattr(candidate, "explosion_event", None)
    if ev is not None:
        for key, attr in (
            ("tier", "tier"),
            ("velocity3s", "velocity_3s"),
            ("explosionScore", "explosion_score"),
        ):
            val = getattr(ev, attr, None)
            if val is not None and key not in evidence:
                evidence[key] = val
    assessment = build_elite_assessment(evidence, ranking)
    if call_pe_parity_elite_fingerprint(
        evidence, ranking, assessment, settings=settings,
    ):
        return True
    if state is not None and snap is not None:
        from app.engines.pe_win_ce_mirror import pe_win_ce_mirror_fingerprint

        symbol = str(
            getattr(candidate, "symbol", None)
            or evidence.get("symbol")
            or getattr(snap, "symbol", "")
            or ""
        ).upper()
        return pe_win_ce_mirror_fingerprint(
            evidence,
            ranking,
            assessment,
            state=state,
            snap=snap,
            symbol=symbol,
            settings=settings,
        )
    return False


def mid_rip_best_trade_candidate(
    candidate: Any,
    alert: Mapping[str, Any] | None = None,
    elite_assessment: Mapping[str, Any] | None = None,
    *,
    settings: Any = None,
) -> bool:
    """Live mid-rip ELITE expanding to top LTP — allow deep ITM when actively ripping."""
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False
    alert = alert if isinstance(alert, Mapping) else _alert_for_candidate(candidate)
    tier = str(getattr(candidate, "tier", "") or "")
    return _mid_rip_best_trade_signals(
        alert, elite_assessment, tier=tier, settings=settings,
    )


def _side_value(side: Any) -> str:
    return str(getattr(side, "value", side) or "").upper()


def _alert_for_candidate(candidate: Any) -> dict[str, Any]:
    alert = getattr(candidate, "alert", None)
    return alert if isinstance(alert, Mapping) else {}


def _classify_moneyness(candidate: Any, snap: Any) -> str:
    from app.engines.moneyness import classify_moneyness

    return classify_moneyness(
        getattr(candidate, "side", ""),
        float(getattr(candidate, "strike", 0) or 0),
        float(getattr(snap, "spot", 0) or 0),
        symbol=str(getattr(candidate, "symbol", "") or ""),
        atm=float(getattr(snap, "atmStrike", 0) or 0) or None,
    )


def _expiry_itm_atm_only_symbol(symbol: str, *, settings: Any = None) -> bool:
    """SENSEX/BANKNIFTY: ATM LTP ~₹300–500 — block all OTM on expiry, ITM+ATM only."""
    from app.config import get_settings

    settings = settings or get_settings()
    csv = str(
        getattr(settings, "best_trade_expiry_itm_atm_only_symbols_csv", "SENSEX,BANKNIFTY")
        or "SENSEX,BANKNIFTY"
    )
    allowed = {s.strip().upper() for s in csv.split(",") if s.strip()}
    return str(symbol or "").upper() in allowed


def expiry_cheap_otm_entry_blocked(
    candidate: Any,
    snap: Any,
    alert: Mapping[str, Any] | None = None,
    *,
    settings: Any = None,
) -> tuple[bool, str]:
    """Expiry OTM block — symbol-aware. NIFTY: ₹18–80 OTM; SENSEX: all OTM."""
    from app.config import get_settings
    from app.engines.expiry_day_guards import is_symbol_expiry_day

    settings = settings or get_settings()
    if not bool(getattr(settings, "best_trade_block_expiry_cheap_otm_enabled", True)):
        return False, ""
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False, ""
    if snap is None or not is_symbol_expiry_day(snap):
        return False, ""

    money = _classify_moneyness(candidate, snap)
    if money != "OTM":
        return False, ""

    symbol = str(getattr(candidate, "symbol", "") or "").upper()
    if _expiry_itm_atm_only_symbol(symbol, settings=settings):
        return True, "best_trade_block_expiry_otm_itm_atm_only"

    alert = alert if isinstance(alert, Mapping) else _alert_for_candidate(candidate)
    premium = _number(getattr(candidate, "premium", 0) or alert.get("premium"))
    prem_lo = float(
        getattr(settings, "best_trade_expiry_cheap_otm_min_premium_inr", 18.0) or 18.0
    )
    prem_hi = float(
        getattr(settings, "best_trade_expiry_cheap_otm_max_premium_inr", 80.0) or 80.0
    )
    if prem_lo <= premium <= prem_hi:
        return True, "best_trade_block_expiry_cheap_otm"
    return False, ""


def best_trade_chop_deep_chase_blocked(
    candidate: Any,
    trap_meta: Mapping[str, Any] | None,
    elite_assessment: Mapping[str, Any] | None,
    *,
    day_mode: str = "",
    settings: Any = None,
) -> tuple[bool, str]:
    """Block Sep15-style deep ITM chop/trap chase — prefer cheap near-base entries."""
    from app.config import get_settings

    settings = settings or get_settings()
    if not bool(getattr(settings, "best_trade_block_chop_deep_chase_enabled", True)):
        return False, ""
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False, ""

    alert = _alert_for_candidate(candidate)
    if mid_rip_best_trade_candidate(
        candidate, alert, elite_assessment, settings=settings,
    ):
        return False, ""

    mode_u = str(day_mode or (elite_assessment or {}).get("dayMode") or "").upper()
    chop_day = any(
        token in mode_u
        for token in ("CHOP", "WORST", "EXPIRY WORST")
    )
    if not chop_day and not (trap_meta or {}).get("fakeExplosionTrap"):
        return False, ""

    premium = _number(getattr(candidate, "premium", 0))
    min_premium = float(
        getattr(settings, "best_trade_deep_chase_min_premium_inr", 120.0) or 120.0
    )
    if premium < min_premium:
        return False, ""

    local = _number((elite_assessment or {}).get("localBasePct"))
    max_local = float(
        getattr(settings, "best_trade_deep_chase_max_local_pct", 18.0) or 18.0
    )
    cheap_max = float(
        getattr(settings, "best_trade_cheap_entry_max_premium_inr", 85.0) or 85.0
    )
    setup = str((elite_assessment or {}).get("setup") or "").upper()
    if (
        premium <= cheap_max
        and setup in VALID_BEST_BASE_SETUPS
        and local <= max_local + 1e-6
    ):
        return False, ""

    if (trap_meta or {}).get("fakeExplosionTrap") or chop_day:
        return True, "best_trade_block_chop_deep_itm_chase"
    return False, ""


def cheap_base_strike_eligible(
    candidate: Any,
    alert: Mapping[str, Any] | None,
    snap: Any,
    *,
    settings: Any = None,
) -> bool:
    """₹18–80 OTM/ATM near session extreme — non-expiry only (expiry OTM → 0.05)."""
    from app.config import get_settings
    from app.engines.expiry_day_guards import is_symbol_expiry_day

    settings = settings or get_settings()
    if not bool(getattr(settings, "best_trade_cheap_base_rank_priority_enabled", True)):
        return False
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False
    if snap is None:
        return False

    premium = _number(getattr(candidate, "premium", 0) or (alert or {}).get("premium"))
    prem_lo = float(getattr(settings, "best_trade_cheap_base_min_premium_inr", 18.0) or 18.0)
    prem_hi = float(getattr(settings, "best_trade_cheap_base_max_premium_inr", 80.0) or 80.0)
    if not (prem_lo <= premium <= prem_hi):
        return False

    money = _classify_moneyness(candidate, snap)
    if money == "OTM" and is_symbol_expiry_day(snap):
        return False

    pad = _number(
        (alert or {}).get("localBaseMovePct")
        or (alert or {}).get("ictBaseRelativeMovePct")
    )
    max_pad = float(getattr(settings, "best_trade_cheap_base_max_local_pct", 22.0) or 22.0)
    if pad > max_pad + 1e-6:
        return False

    off_low = _number((alert or {}).get("offLowMovePct"))
    max_off = float(
        getattr(settings, "best_trade_cheap_base_max_off_extreme_pct", 35.0) or 35.0
    )
    if off_low > max_off + 1e-6:
        return False

    if money == "ITM":
        return False
    return True


def deep_itm_chase_strike(
    candidate: Any,
    alert: Mapping[str, Any] | None,
    snap: Any,
    *,
    settings: Any = None,
) -> bool:
    """Deep ITM / expensive premium chase — Sep15 23500 PE @ ₹242."""
    from app.config import get_settings

    settings = settings or get_settings()
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False

    premium = _number(getattr(candidate, "premium", 0) or (alert or {}).get("premium"))
    deep_floor = float(getattr(settings, "best_trade_deep_itm_min_premium_inr", 120.0) or 120.0)
    if premium >= deep_floor:
        return True

    if snap is None:
        return False
    money = _classify_moneyness(candidate, snap)
    cheap_hi = float(getattr(settings, "best_trade_cheap_entry_max_premium_inr", 85.0) or 85.0)
    return money == "ITM" and premium > cheap_hi


def deprioritize_deep_itm_when_cheap_base_present(
    candidates: list[Any],
    *,
    settings: Any = None,
) -> list[Any]:
    """Drop deep ITM legs when a cheap-base peer exists on the same symbol+side."""
    from app.config import get_settings

    settings = settings or get_settings()
    if not bool(getattr(settings, "best_trade_cheap_base_rank_priority_enabled", True)):
        return candidates
    if len(candidates) <= 1:
        return candidates

    from collections import defaultdict

    groups: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for candidate in candidates:
        sym = str(getattr(candidate, "symbol", "") or "").upper()
        side = _side_value(getattr(candidate, "side", ""))
        groups[(sym, side)].append(candidate)

    kept: list[Any] = []
    for group in groups.values():
        cheap_present = any(
            cheap_base_strike_eligible(
                c, _alert_for_candidate(c), getattr(c, "snap", None), settings=settings,
            )
            for c in group
        )
        if not cheap_present:
            kept.extend(group)
            continue
        for candidate in group:
            alert = _alert_for_candidate(candidate)
            if deep_itm_chase_strike(
                candidate,
                alert,
                getattr(candidate, "snap", None),
                settings=settings,
            ):
                if mid_rip_best_trade_candidate(candidate, alert, settings=settings):
                    kept.append(candidate)
                continue
            kept.append(candidate)
    return kept if kept else candidates


def cheap_base_strike_rank_bonus(
    candidate: Any,
    *,
    alert: Mapping[str, Any] | None = None,
    elite_assessment: Mapping[str, Any] | None = None,
    settings: Any = None,
) -> float:
    """Selector sort_key boost for cheap-base rank-1; penalty for deep ITM."""
    from app.config import get_settings

    settings = settings or get_settings()
    if not bool(getattr(settings, "best_trade_cheap_base_rank_priority_enabled", True)):
        return 0.0

    alert = alert if isinstance(alert, Mapping) else _alert_for_candidate(candidate)
    snap = getattr(candidate, "snap", None)
    bonus = 0.0
    if cheap_base_strike_eligible(
        candidate, alert, snap, settings=settings,
    ):
        bonus += float(getattr(settings, "best_trade_cheap_base_rank_bonus", 45.0) or 45.0)
        setup = str((elite_assessment or {}).get("setup") or "").upper()
        if setup in VALID_BEST_BASE_SETUPS:
            bonus += float(
                getattr(settings, "best_trade_cheap_base_ftv_v_bonus", 12.0) or 12.0
            )
    elif deep_itm_chase_strike(candidate, alert, snap, settings=settings):
        bonus -= float(getattr(settings, "best_trade_deep_itm_rank_penalty", 60.0) or 60.0)
    return bonus


def elite_base_setup_allowed(
    setup: str,
    *,
    mega_ok: bool = False,
    settings: Any = None,
) -> bool:
    """FTV + V near-base setups allowed; generic EXPLOSIVE chase optional block."""
    from app.config import get_settings

    settings = settings or get_settings()
    setup_u = str(setup or "").upper()
    if mega_ok:
        return True
    if bool(getattr(settings, "elite_trade_v_rip_only_enabled", False)):
        return setup_u == "V"
    if setup_u in VALID_BEST_BASE_SETUPS:
        return True
    if bool(getattr(settings, "elite_trade_block_explosive_chase_enabled", True)):
        return setup_u != "EXPLOSIVE"
    return True
