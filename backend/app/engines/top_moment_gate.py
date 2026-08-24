"""Top-moment entry gate — only FTV, V-rip, ELITE, and EXPLODING trades.

Product focus: take the highest-quality explosion moments only. Blocks B/C-grade
sleeves, generic BUILDING without a causal FTV/V trigger, and non-explosion modes.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

TOP_MOMENT_TYPES = frozenset({"ELITE", "EXPLODING", "FTV", "V"})
TOP_MOMENT_GRADES = frozenset({"S", "A"})


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def classify_top_moment_type(evidence: Mapping[str, Any]) -> Optional[str]:
    """Return ELITE | EXPLODING | FTV | V when this is a focused top moment."""
    tier = str(evidence.get("tier") or "").upper()

    if bool(
        evidence.get("slowGrindSuddenLift") or evidence.get("fastBullishLocalBase")
    ):
        return "FTV"

    if bool(evidence.get("vRipReady")) and not bool(evidence.get("midRipCoil")):
        return "V"

    building_rip = bool(evidence.get("buildingRipReady")) and not bool(
        evidence.get("midRipCoil")
    )
    helpers_ok = bool(
        evidence.get("buildingRipHelpersOk")
        or evidence.get("buildingLiftHelping")
        or evidence.get("indexHelpersConfirm")
        or evidence.get("indexTickSpike")
    )
    if building_rip and helpers_ok:
        return "FTV"

    has_ftv_structure = bool(
        evidence.get("flatThenVertical") and evidence.get("activeBreakout")
    )
    has_base_trigger = bool(
        evidence.get("armedBaseLaunch")
        or evidence.get("eliteBaseReady")
        or evidence.get("firstLift")
        or evidence.get("armedBaseSustainedLift")
    )

    if has_ftv_structure or has_base_trigger:
        if tier == "ELITE":
            return "ELITE"
        if tier == "EXPLODING":
            return "EXPLODING"
        if tier == "BUILDING" and (building_rip or helpers_ok):
            return "FTV"
        if tier in ("ELITE", "EXPLODING"):
            return tier
        if has_ftv_structure:
            return "FTV"

    if tier == "ELITE" and (has_base_trigger or has_ftv_structure):
        return "ELITE"
    if tier == "EXPLODING" and (has_base_trigger or has_ftv_structure):
        return "EXPLODING"

    return None


def top_moment_entry_allowed(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    *,
    top_moments_only_enabled: bool = True,
    min_grade: str = "A",
) -> tuple[bool, str, Optional[str]]:
    """True when candidate is a top FTV / V / ELITE / EXPLODING moment."""
    if not top_moments_only_enabled:
        return True, "disabled", None

    grade = str(ranking.get("grade") or "").upper()
    allowed_grades = set(TOP_MOMENT_GRADES)
    min_grade_u = str(min_grade or "A").upper()
    if min_grade_u == "S":
        allowed_grades = {"S"}
    elif min_grade_u == "B":
        allowed_grades = TOP_MOMENT_GRADES | {"B"}

    if grade == "REJECT":
        return False, "top_moment_grade_reject", None
    if grade not in allowed_grades:
        return False, f"top_moment_requires_grade_{min_grade_u}_or_better", None

    moment = classify_top_moment_type(evidence)
    if moment not in TOP_MOMENT_TYPES:
        return False, "top_moment_requires_ftv_v_elite_or_exploding", None

    timing = str(evidence.get("timingAssessment") or "").upper()
    timing_action = str(evidence.get("timingAction") or "").lower()
    if timing_action in {"block", "reject"} or timing in {
        "FAILED_LAUNCH",
        "FADED",
        "FADING",
        "EXHAUSTED",
        "NEGATIVE",
        "REJECT",
        "BLOCKED",
    }:
        return False, "top_moment_timing_blocked", moment

    if _number(evidence.get("velocity3s")) < (
        -0.8 if evidence.get("slowGrindSuddenLift") else 0.0
    ):
        return False, "top_moment_negative_velocity", moment

    return True, "ok", moment


def qualifies_for_top_moment_max_lots(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    *,
    top_moments_max_lots_only_enabled: bool = True,
    min_grade: str = "A",
) -> tuple[bool, str, Optional[str]]:
    """True when this explosion may use capital-max lots (FTV / V / ELITE / EXPLODING)."""
    if not top_moments_max_lots_only_enabled:
        return True, "disabled", classify_top_moment_type(evidence)

    ok, reason, moment = top_moment_entry_allowed(
        evidence,
        ranking,
        top_moments_only_enabled=True,
        min_grade=min_grade,
    )
    if not ok:
        return False, reason, moment
    if moment not in TOP_MOMENT_TYPES:
        return False, "top_moment_requires_ftv_v_elite_or_exploding", moment
    return True, "ok", moment


def explosion_alert_is_top_moment(alert: Mapping[str, Any]) -> bool:
    """Pre-selector radar filter: BUILDING must show FTV/V shape before candidacy."""
    tier = str(alert.get("tier") or "").upper()
    if tier in ("ELITE", "EXPLODING"):
        return True

    evidence = {
        "tier": tier,
        "vRipReady": bool(alert.get("ictVRipReady")),
        "slowGrindSuddenLift": bool(
            alert.get("slowGrindSuddenLiftReady")
            or alert.get("ictSlowGrindSuddenLift")
        ),
        "fastBullishLocalBase": bool(
            alert.get("fastBullishLocalBaseReady")
            or alert.get("bullishLocalBaseActive")
        ),
        "buildingRipReady": bool(alert.get("ictBuildingRipReady")),
        "buildingRipHelpersOk": bool(
            alert.get("buildingRipHelpersOk") or alert.get("buildingLiftHelping")
        ),
        "buildingLiftHelping": bool(alert.get("buildingLiftHelping")),
        "flatThenVertical": bool(alert.get("ictFlatThenVertical")),
        "activeBreakout": bool(alert.get("ictBreakout")),
        "armedBaseLaunch": bool(alert.get("ictArmedBaseLaunch")),
        "eliteBaseReady": bool(alert.get("ictEliteBaseReady")),
        "firstLift": bool(alert.get("ictFirstLift")),
        "armedBaseSustainedLift": bool(alert.get("ictArmedBaseSustainedLift")),
        "indexHelpersConfirm": bool(alert.get("indexHelpersConfirm")),
        "indexTickSpike": bool(alert.get("indexTickSpike")),
        "midRipCoil": bool(alert.get("ictMidRipCoil") or alert.get("midRipCoil")),
    }
    return classify_top_moment_type(evidence) is not None
