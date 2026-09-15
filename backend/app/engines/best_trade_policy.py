"""Sep-9-style best trades: near-base max lots, all day types / sessions.

One clean base entry (₹50→₹100+) at max lots = full-cap profit. Block deep ITM
chop traps; allow FTV/V/cheap-base cold entries across CHOP/EXPIRY/MOMENTUM days.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

VALID_BEST_BASE_SETUPS = frozenset({"FTV", "V"})


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
