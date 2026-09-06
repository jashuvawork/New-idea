"""Elite runner exit bundle — auto-stamp maxProfitCapture + vBaseFtvRunner near-base V/FTV.

Bridges entry-policy winners to exit-layer hold/trail semantics so theory MFE
can convert to realized PnL (hold through base pause, parabolic trail after +100%).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import Settings, get_settings

_VALID_SETUPS = frozenset({"V", "FTV", "EXPLOSIVE"})
_GRADE_RANK = {"S": 0, "A": 1, "B": 2, "C": 3}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def qualifies_elite_near_base_runner(
    ctx_extra: Mapping[str, Any],
    *,
    assessment: Mapping[str, Any] | None = None,
    base_rel_pct: float = 0.0,
    first_lift: bool = False,
    ict_flat_vertical: bool = False,
    tier: str = "",
    settings: Settings | None = None,
) -> tuple[bool, str]:
    """Return (qualifies, reason_code) for auto runner exit stamping."""
    s = settings or get_settings()
    if not bool(getattr(s, "elite_runner_exit_bundle_enabled", True)):
        return False, ""

    max_local = float(
        getattr(s, "elite_runner_exit_max_local_base_pct", 15.0) or 15.0
    )
    local = _num(
        (assessment or {}).get("localBasePct")
        or ctx_extra.get("localBaseBaseRelPct")
        or ctx_extra.get("localBaseMovePct")
        or base_rel_pct
    )
    if local <= 0 or local > max_local + 1e-6:
        return False, ""

    setup = str((assessment or {}).get("setup") or "").upper()
    if not setup:
        if ict_flat_vertical or first_lift:
            setup = "FTV" if ict_flat_vertical else "V"
        elif bool(ctx_extra.get("ictFlatThenVertical")):
            setup = "FTV"
        elif bool(ctx_extra.get("ictFirstLift") or ctx_extra.get("firstLiftCapture")):
            setup = "V"

    if setup and setup not in _VALID_SETUPS:
        return False, ""

    min_score = float(getattr(s, "elite_runner_exit_min_score", 90.0) or 90.0)
    min_grade = str(getattr(s, "elite_runner_exit_min_grade", "A") or "A").upper()
    tier_u = str(tier or ctx_extra.get("tier") or "").upper()

    if assessment:
        score = _num(assessment.get("eliteScore"))
        if score + 1e-6 < min_score:
            return False, ""
        grade = str(assessment.get("grade") or "").upper()
        if _GRADE_RANK.get(grade, 9) > _GRADE_RANK.get(min_grade, 1):
            return False, ""
        if not setup:
            setup = str(assessment.get("setup") or "").upper()
            if setup not in _VALID_SETUPS:
                return False, ""
        return True, f"elite_assessment_{setup.lower()}"

    # Fallback when assessment missing: ELITE tier + existing capture path + V/FTV shape.
    if tier_u != "ELITE":
        return False, ""
    if not (
        ict_flat_vertical
        or first_lift
        or bool(ctx_extra.get("maxProfitCapture"))
    ):
        return False, ""
    if not setup:
        setup = "FTV" if ict_flat_vertical else "V"
    if setup not in _VALID_SETUPS:
        return False, ""
    return True, f"elite_tier_{setup.lower()}"


def apply_elite_runner_exit_bundle(
    ctx_extra: dict[str, Any],
    *,
    assessment: Mapping[str, Any] | None = None,
    base_rel_pct: float = 0.0,
    first_lift: bool = False,
    ict_flat_vertical: bool = False,
    tier: str = "",
    settings: Settings | None = None,
) -> bool:
    """Stamp runner exit flags on ctx_extra. Returns True when stamped."""
    ok, reason = qualifies_elite_near_base_runner(
        ctx_extra,
        assessment=assessment,
        base_rel_pct=base_rel_pct,
        first_lift=first_lift,
        ict_flat_vertical=ict_flat_vertical,
        tier=tier,
        settings=settings,
    )
    if not ok:
        return False

    ctx_extra["maxProfitCapture"] = True
    ctx_extra["vBaseFtvRunner"] = True
    ctx_extra["eliteRunnerExitBundle"] = True
    ctx_extra["eliteRunnerExitReason"] = reason
    if not ctx_extra.get("momentType"):
        setup = str((assessment or {}).get("setup") or "").upper()
        if setup == "V" or first_lift:
            ctx_extra["momentType"] = "elite_vbase_runner"
        elif setup == "FTV" or ict_flat_vertical:
            ctx_extra["momentType"] = "elite_ftv_runner"
        else:
            ctx_extra["momentType"] = "elite_near_base_runner"
    return True


def clear_modest_peak_for_runner(ctx_extra: dict[str, Any]) -> None:
    """V-base runners must not inherit chop modest-peak caps."""
    if not (
        ctx_extra.get("vBaseFtvRunner") or ctx_extra.get("eliteRunnerExitBundle")
    ):
        return
    ctx_extra.pop("modestPeakMode", None)
    ctx_extra.pop("modestPeakReason", None)
    plan = dict(ctx_extra.get("exitPlan") or {})
    plan.pop("modestPeakMode", None)
    plan.pop("modestPeakReason", None)
    if str(plan.get("exitBias") or "").upper() == "PROTECT" and ctx_extra.get(
        "psychologyExitBias"
    ) != "PROTECT":
        plan["exitBias"] = "LET_RUNNERS"
    ctx_extra["exitPlan"] = plan


def refresh_runner_exit_plans(
    ctx_extra: dict[str, Any],
    *,
    entry_premium: float,
    base_premium: float = 0.0,
    exit_plan: dict[str, Any] | None = None,
    velocity_3s: float = 0.0,
    volume_surge: float = 1.0,
    session_move_pct: float = 0.0,
    premium_fvg: bool = False,
    flat_then_vertical: bool = False,
    mega_rip: bool = False,
    settings: Settings | None = None,
) -> None:
    """Rebuild stage ladder after runner bundle stamp; drop modest-peak caps."""
    if not (
        ctx_extra.get("vBaseFtvRunner") or ctx_extra.get("eliteRunnerExitBundle")
    ):
        return

    clear_modest_peak_for_runner(ctx_extra)

    from app.engines.moment_stage_trail import build_moment_stage_plan

    s = settings or get_settings()
    stage_plan = build_moment_stage_plan(
        entry_premium=float(entry_premium or 50),
        base_premium=float(base_premium or 0),
        exit_plan=exit_plan if isinstance(exit_plan, dict) else None,
        velocity_3s=float(velocity_3s or 0),
        volume_surge=float(volume_surge or 1.0),
        session_move_pct=float(session_move_pct or 0),
        premium_fvg=bool(premium_fvg),
        flat_then_vertical=bool(flat_then_vertical or ctx_extra.get("ictFlatThenVertical")),
        mega_rip=bool(mega_rip or ctx_extra.get("ictMegaRip")),
        max_profit=True,
        vbase_ftv_runner=True,
        settings=s,
    )
    if not stage_plan:
        return
    ctx_extra.update(stage_plan)
    plan = dict(ctx_extra.get("exitPlan") or {})
    plan.update(stage_plan)
    ctx_extra["exitPlan"] = plan


def elite_runner_failed_launch_relax(trade: Any, *, settings: Settings | None = None) -> bool:
    """Broader failed_launch relax: bundle-stamped near-base verticals with lift proof."""
    s = settings or get_settings()
    if not bool(getattr(s, "elite_failed_launch_relax_enabled", True)):
        return False
    ctx = getattr(trade, "entryContext", None) or {}
    if not (
        ctx.get("eliteRunnerExitBundle")
        or (ctx.get("vBaseFtvRunner") and ctx.get("maxProfitCapture"))
    ):
        return False

    max_local = float(
        getattr(s, "elite_failed_launch_relax_max_local_base_pct", 20.0) or 20.0
    )
    local = _num(
        ctx.get("localBaseBaseRelPct") or ctx.get("localBaseMovePct")
    )
    if local <= 0:
        base = _num(ctx.get("ictBasePremium"))
        entry = _num(getattr(trade, "entryPremium", 0))
        if base > 0 and entry > base:
            local = (entry - base) / base * 100.0
    if local <= 0:
        local = 999.0
    if local > max_local + 1e-6:
        return False

    min_v = float(
        getattr(s, "elite_failed_launch_relax_min_velocity_3s", 0.0) or 0.0
    )
    v3 = _num(ctx.get("velocity3s") or ctx.get("entryVelocity3s"))
    has_lift = bool(
        ctx.get("ictFirstLift")
        or ctx.get("firstLiftCapture")
        or ctx.get("armedBaseCapture")
        or ctx.get("ictFlatThenVertical")
    )
    if has_lift:
        return True
    if min_v <= 0:
        return v3 > 0
    return v3 + 1e-6 >= min_v
