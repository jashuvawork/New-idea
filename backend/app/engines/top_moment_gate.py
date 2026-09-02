"""Top-moment entry gate — only FTV, V-rip, ELITE, and EXPLODING trades.

Product focus: take the highest-quality explosion moments only. Blocks B/C-grade
sleeves, generic BUILDING without a causal FTV/V trigger, and non-explosion modes.

BUILDING-tier FTV/V requires a causal stamp (v-rip, flat→vertical at base, building
rip + helpers, or early pad capture) — slow-grind coil alone on chop days is not
a tradeable moment.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.engines.pad_lane_capture import pad_lane_cold_velocity_ok

TOP_MOMENT_TYPES = frozenset({"ELITE", "EXPLODING", "FTV", "V"})
TOP_MOMENT_GRADES = frozenset({"S", "A"})


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _pad_lane_lift_evidence(evidence: Mapping[str, Any]) -> bool:
    return bool(
        evidence.get("slowGrindSuddenLift")
        or evidence.get("slowGrindConsolidationBase")
        or evidence.get("fastBullishLocalBase")
        or evidence.get("squeezeRelease")
        or evidence.get("indexLedOptionLag")
        or evidence.get("stealthCvdCoil")
        or evidence.get("microPullbackRetest")
        or evidence.get("premiumFvgPad")
        or evidence.get("doubleDipVbase")
        or evidence.get("buildingCoilPad")
    )


def building_has_causal_ftv_v_structure(evidence: Mapping[str, Any]) -> bool:
    """True when BUILDING shows a real FTV/V shape at local base — not coil alone."""
    if bool(evidence.get("vRipReady")) and not bool(evidence.get("midRipCoil")):
        return True
    flat_vert = bool(evidence.get("flatThenVertical"))
    if flat_vert and bool(evidence.get("activeBreakout")):
        return True
    if flat_vert and bool(
        evidence.get("armedBaseLaunch")
        or evidence.get("armedBaseSustainedLift")
        or evidence.get("eliteBaseReady")
        or evidence.get("firstLift")
        or evidence.get("baseArmed")
    ):
        return True
    building_rip = bool(evidence.get("buildingRipReady"))
    helpers_ok = bool(
        evidence.get("buildingRipHelpersOk")
        or evidence.get("buildingLiftHelping")
        or evidence.get("indexHelpersConfirm")
        or evidence.get("indexTickSpike")
    )
    if building_rip and helpers_ok:
        return True
    if bool(evidence.get("indexConfirmedLocalBase")):
        return True
    if bool(evidence.get("earlyRadarPadCapture")):
        return True
    if bool(evidence.get("buildingCoilPad")):
        return True
    return False


def classify_top_moment_type(evidence: Mapping[str, Any]) -> Optional[str]:
    """Return ELITE | EXPLODING | FTV | V when this is a focused top moment."""
    tier = str(evidence.get("tier") or "").upper()

    if bool(evidence.get("vRipReady")) and not bool(evidence.get("midRipCoil")):
        return "V"

    if _pad_lane_lift_evidence(evidence) or bool(evidence.get("earlyRadarPadCapture")):
        if tier in ("ELITE", "EXPLODING"):
            return "FTV"
        if building_has_causal_ftv_v_structure(evidence):
            return "FTV"

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
        if tier == "BUILDING":
            if not building_has_causal_ftv_v_structure(evidence):
                return None
            if building_rip or helpers_ok:
                return "FTV"
            if has_ftv_structure:
                return "FTV"
            return None
        if has_ftv_structure:
            return "FTV"

    if tier == "ELITE" and (has_base_trigger or has_ftv_structure):
        return "ELITE"
    if tier == "EXPLODING" and (has_base_trigger or has_ftv_structure):
        return "EXPLODING"

    if tier == "WATCH":
        from app.engines.early_radar_pad_capture import watch_local_base_pad_structure

        if watch_local_base_pad_structure(evidence):
            return "FTV"

    return None


def top_moment_entry_allowed(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    *,
    top_moments_only_enabled: bool = True,
    min_grade: str = "A",
    readiness_reason: str = "",
) -> tuple[bool, str, Optional[str]]:
    """True when candidate is a top FTV / V / ELITE / EXPLODING moment."""
    if not top_moments_only_enabled:
        return True, "disabled", None

    from app.engines.building_ftv_gates import (
        building_armed_base_grade_a_top_moment_ok,
        building_coil_pad_grade_a_top_moment_ok,
    )

    if building_armed_base_grade_a_top_moment_ok(
        evidence, ranking, readiness_reason=readiness_reason,
    ):
        return True, "ok", "FTV"

    if building_coil_pad_grade_a_top_moment_ok(
        evidence, ranking, readiness_reason=readiness_reason,
    ):
        return True, "ok", "FTV"

    grade = str(ranking.get("grade") or "").upper()
    allowed_grades = set(TOP_MOMENT_GRADES)
    min_grade_u = str(min_grade or "A").upper()
    if min_grade_u == "S":
        allowed_grades = {"S"}
    elif min_grade_u == "B":
        allowed_grades = TOP_MOMENT_GRADES | {"B"}

    from app.engines.pad_lane_capture import pad_lane_grade_floor_applies

    if pad_lane_grade_floor_applies(evidence) and grade in {"REJECT", "C"}:
        grade = "A"

    from app.engines.early_radar_pad_capture import building_armed_prelaunch_pad_lane
    from app.config import get_settings

    if grade in {"REJECT", "C"} and building_armed_prelaunch_pad_lane(
        evidence if isinstance(evidence, dict) else {},
        get_settings(),
    ):
        grade = "B"

    if grade == "REJECT":
        return False, "top_moment_grade_reject", None
    if grade not in allowed_grades:
        return False, f"top_moment_requires_grade_{min_grade_u}_or_better", None

    moment = classify_top_moment_type(evidence)
    if moment not in TOP_MOMENT_TYPES:
        return False, "top_moment_requires_ftv_v_elite_or_exploding", None

    timing = str(evidence.get("timingAssessment") or "").upper()
    timing_action = str(evidence.get("timingAction") or "").lower()
    from app.engines.pad_lane_capture import pad_lane_ftv_waives_timing_block

    timing_blocked = timing_action in {"block", "reject"} or timing in {
        "FAILED_LAUNCH",
        "FADED",
        "FADING",
        "EXHAUSTED",
        "NEGATIVE",
        "REJECT",
        "BLOCKED",
    }
    if timing_blocked and not pad_lane_ftv_waives_timing_block(evidence):
        return False, "top_moment_timing_blocked", moment

    v3 = _number(evidence.get("velocity3s"))
    v9 = _number(evidence.get("velocity9s"))
    if v3 < 0 and not pad_lane_cold_velocity_ok(evidence, v3, v9):
        if not pad_lane_ftv_waives_timing_block(evidence):
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
    if bool(alert.get("earlyRadarPadCapture") or alert.get("ictEarlyRadarPadCapture")):
        return True
    if bool(alert.get("buildingCoilPadReady")):
        return True
    from app.config import get_settings
    from app.engines.early_radar_pad_capture import (
        building_armed_prelaunch_pad_lane,
        building_coil_pad_lift_signal,
    )

    settings = get_settings()
    if building_armed_prelaunch_pad_lane(alert, settings):
        return True
    tier = str(alert.get("tier") or "").upper()
    base_rel = _number(
        alert.get("ictBaseRelativeMovePct") or alert.get("localBaseMovePct")
    )
    pad_lo = float(
        getattr(settings, "building_coil_pad_min_local_move_pct", 10.0) or 10.0
    )
    pad_hi = float(
        getattr(settings, "building_coil_pad_max_local_move_pct", 25.0) or 25.0
    )
    vol_awake = bool(
        alert.get("volumeAwaken")
        or alert.get("ictVolumeAwakening")
        or float(alert.get("volumeSurge") or 0) >= 1.2
    )
    if (
        tier == "BUILDING"
        and pad_lo <= base_rel <= pad_hi + 1e-6
        and bool(alert.get("ictBaseArmed"))
        and vol_awake
        and building_coil_pad_lift_signal(alert, settings)
    ):
        return True
    if (
        tier == "BUILDING"
        and bool(getattr(settings, "building_armed_base_grade_a_live_enabled", True))
        and bool(alert.get("ictBaseArmed"))
        and base_rel > 0
    ):
        from app.engines.building_ftv_gates import building_armed_base_grade_a_live_ok

        if building_armed_base_grade_a_live_ok(
            alert,
            readiness_reason=str(
                alert.get("ictBaseReadinessReason")
                or alert.get("readyReason")
                or "armed_base_option_led_ready"
            ),
        ):
            return True
    if tier in ("ELITE", "EXPLODING"):
        return True

    if bool(
        alert.get("ictIndexConfirmedLocalBase")
        or alert.get("indexConfirmedLocalBase")
    ):
        return True

    max_off = float(
        getattr(settings, "early_radar_pad_max_off_low_pct", 15.0) or 15.0
    )
    off_low = _number(alert.get("offLowMovePct"))
    if (
        tier in ("WATCH", "BUILDING")
        and bool(alert.get("ictFlatThenVertical"))
        and off_low <= max_off + 1e-6
        and bool(
            alert.get("volumeAwaken")
            or alert.get("ictVolumeAwakening")
            or alert.get("ictBreakout")
        )
    ):
        return True

    from app.engines.early_radar_pad_capture import watch_local_base_pad_structure

    if watch_local_base_pad_structure(alert):
        return True

    evidence = {
        "tier": tier,
        "vRipReady": bool(alert.get("ictVRipReady")),
        "slowGrindSuddenLift": bool(
            alert.get("slowGrindSuddenLiftReady")
            or alert.get("ictSlowGrindSuddenLift")
        ),
        "slowGrindConsolidationBase": bool(
            alert.get("slowGrindConsolidationBaseReady")
            or alert.get("ictSlowGrindConsolidationBase")
        ),
        "fastBullishLocalBase": bool(
            alert.get("fastBullishLocalBaseReady")
            or alert.get("bullishLocalBaseActive")
        ),
        "squeezeRelease": bool(
            alert.get("squeezeReleaseReady") or alert.get("ictSqueezeRelease")
        ),
        "indexLedOptionLag": bool(
            alert.get("indexLedOptionLagReady") or alert.get("ictIndexLedOptionLag")
        ),
        "stealthCvdCoil": bool(
            alert.get("stealthCvdCoilReady") or alert.get("ictStealthCvdCoil")
        ),
        "microPullbackRetest": bool(
            alert.get("microPullbackRetestReady") or alert.get("ictMicroPullbackRetest")
        ),
        "premiumFvgPad": bool(
            alert.get("premiumFvgPadReady") or alert.get("ictPremiumFvgPad")
        ),
        "doubleDipVbase": bool(
            alert.get("doubleDipVbaseReady") or alert.get("ictDoubleDipVbase")
        ),
        "earlyRadarPadCapture": bool(
            alert.get("earlyRadarPadCapture") or alert.get("ictEarlyRadarPadCapture")
        ),
        "buildingCoilPad": bool(
            alert.get("buildingCoilPad") or alert.get("buildingCoilPadReady")
        ),
        "buildingRipReady": bool(alert.get("ictBuildingRipReady")),
        "buildingRipHelpersOk": bool(
            alert.get("buildingRipHelpersOk") or alert.get("buildingLiftHelping")
        ),
        "buildingLiftHelping": bool(alert.get("buildingLiftHelping")),
        "flatThenVertical": bool(alert.get("ictFlatThenVertical")),
        "activeBreakout": bool(alert.get("ictBreakout")),
        "armedBaseLaunch": bool(
            alert.get("ictArmedBaseLaunch") or alert.get("ictBaseArmed")
        ),
        "eliteBaseReady": bool(alert.get("ictEliteBaseReady")),
        "firstLift": bool(alert.get("ictFirstLift")),
        "armedBaseSustainedLift": bool(alert.get("ictArmedBaseSustainedLift")),
        "indexHelpersConfirm": bool(alert.get("indexHelpersConfirm")),
        "indexConfirmedLocalBase": bool(
            alert.get("indexConfirmedLocalBase")
            or alert.get("ictIndexConfirmedLocalBase")
        ),
        "indexTickSpike": bool(alert.get("indexTickSpike")),
        "midRipCoil": bool(alert.get("ictMidRipCoil") or alert.get("midRipCoil")),
    }
    return classify_top_moment_type(evidence) is not None
