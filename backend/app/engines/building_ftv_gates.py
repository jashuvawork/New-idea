"""Shared BUILDING / FTV readiness helpers for entry gates."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings

BUILDING_READY_REASONS = frozenset(
    {
        "building_rip_bullish_ready",
        "building_local_base_lift_ready",
        "building_first_lift_ready",
        "building_first_lift_preauthorized",
    }
)

PAD_LANE_READY_REASONS = frozenset(
    {
        "slow_grind_sudden_lift_ready",
        "slow_grind_armed_trough_ready",
        "slow_grind_consolidation_base_ready",
        "fast_bullish_local_base_ready",
        "v_rip_session_low_ready",
        "squeeze_release_ready",
        "index_led_option_lag_ready",
        "stealth_cvd_coil_ready",
        "micro_pullback_retest_ready",
        "premium_fvg_pad_ready",
        "double_dip_vbase_ready",
        "early_radar_pad_ready",
    }
)


def alert_has_building_rip_signal(alert: Optional[dict[str, Any]]) -> bool:
    """True when radar stamped a BUILDING rip (including after EXPLODING promote)."""
    if not isinstance(alert, dict):
        return False
    if bool(alert.get("ictBuildingRipReady") or alert.get("buildingRipReady")):
        return True
    if bool(alert.get("buildingLiftHelping") or alert.get("buildingRipHelpersOk")):
        return True
    reason = str(alert.get("reason") or "")
    if "buildingRip" in reason:
        return True
    ready_reason = str(
        alert.get("ictBaseReadinessReason") or alert.get("readyReason") or ""
    )
    return ready_reason in BUILDING_READY_REASONS or ready_reason.startswith(
        "buildingRip"
    )


def building_rip_ready_reason(
    *,
    alert: Optional[dict[str, Any]] = None,
    readiness_reason: str = "",
) -> str:
    rr = str(readiness_reason or "")
    if rr in BUILDING_READY_REASONS or rr.startswith("buildingRip"):
        return rr
    if isinstance(alert, dict):
        stamped = str(alert.get("ictBaseReadinessReason") or "")
        if stamped in BUILDING_READY_REASONS or stamped.startswith("buildingRip"):
            return stamped
    if alert_has_building_rip_signal(alert):
        return "building_rip_bullish_ready"
    return ""


def pad_lane_ready_reason(
    *,
    alert: Optional[dict[str, Any]] = None,
    readiness_reason: str = "",
) -> str:
    rr = str(readiness_reason or "")
    if rr in PAD_LANE_READY_REASONS:
        return rr
    if isinstance(alert, dict):
        stamped = str(alert.get("ictBaseReadinessReason") or "")
        if stamped in PAD_LANE_READY_REASONS:
            return stamped
        if bool(
            alert.get("slowGrindSuddenLiftReady")
            or alert.get("ictSlowGrindSuddenLift")
        ):
            stamped = str(alert.get("ictBaseReadinessReason") or "")
            if stamped == "slow_grind_armed_trough_ready":
                return "slow_grind_armed_trough_ready"
            if stamped == "slow_grind_consolidation_base_ready":
                return "slow_grind_consolidation_base_ready"
            return "slow_grind_sudden_lift_ready"
        if bool(
            alert.get("fastBullishLocalBaseReady")
            or alert.get("bullishLocalBaseActive")
        ):
            return "fast_bullish_local_base_ready"
        if bool(alert.get("squeezeReleaseReady") or alert.get("ictSqueezeRelease")):
            return "squeeze_release_ready"
        if bool(alert.get("indexLedOptionLagReady") or alert.get("ictIndexLedOptionLag")):
            return "index_led_option_lag_ready"
        if bool(alert.get("stealthCvdCoilReady") or alert.get("ictStealthCvdCoil")):
            return "stealth_cvd_coil_ready"
        if bool(alert.get("microPullbackRetestReady") or alert.get("ictMicroPullbackRetest")):
            return "micro_pullback_retest_ready"
        if bool(alert.get("premiumFvgPadReady") or alert.get("ictPremiumFvgPad")):
            return "premium_fvg_pad_ready"
        if bool(alert.get("doubleDipVbaseReady") or alert.get("ictDoubleDipVbase")):
            return "double_dip_vbase_ready"
        if bool(alert.get("earlyRadarPadCapture") or alert.get("ictEarlyRadarPadCapture")):
            return "early_radar_pad_ready"
    return ""


def pad_lane_bypasses_fake_trap(
    *,
    alert: Optional[dict[str, Any]] = None,
    readiness_reason: str = "",
    candidate: Any = None,
) -> bool:
    """Selector / pretrade — pad-lane pre-lift takes bypass fake-trap like BUILDING rip."""
    if candidate is not None and not isinstance(alert, dict):
        raw = getattr(candidate, "alert", None)
        alert = raw if isinstance(raw, dict) else None
        meta = getattr(candidate, "pretrade_meta", None) or {}
        if isinstance(meta, dict) and not readiness_reason:
            readiness_reason = str(
                meta.get("ictBaseReadinessReason")
                or meta.get("firstLiftReadinessReason")
                or ""
            )
    return bool(pad_lane_ready_reason(alert=alert, readiness_reason=readiness_reason))


def building_rip_bypasses_fake_trap(
    *,
    alert: Optional[dict[str, Any]] = None,
    readiness_reason: str = "",
    candidate: Any = None,
) -> bool:
    """Selector / pretrade / order path — same soft bypass for helper BUILDING rips."""
    settings = get_settings()
    if not bool(getattr(settings, "building_rip_bypasses_fake_trap", True)):
        return False
    if candidate is not None and not isinstance(alert, dict):
        raw = getattr(candidate, "alert", None)
        alert = raw if isinstance(raw, dict) else None
        meta = getattr(candidate, "pretrade_meta", None) or {}
        if isinstance(meta, dict) and not readiness_reason:
            readiness_reason = str(
                meta.get("ictBaseReadinessReason")
                or meta.get("firstLiftReadinessReason")
                or ""
            )
    return bool(
        building_rip_ready_reason(alert=alert, readiness_reason=readiness_reason)
        or alert_has_building_rip_signal(alert)
        or pad_lane_ready_reason(alert=alert, readiness_reason=readiness_reason)
    )


def top_must_take_bypasses_fake_trap(
    *,
    must_take: bool = False,
    alert: Optional[dict[str, Any]] = None,
    candidate: Any = None,
    snap: Any = None,
) -> bool:
    """Soft bypass for top ELITE/EXPLODING must-take when index helpers confirm.

    Fake-trap still *evaluates* (meta stamps); selector/pretrade may continue.
    Hard counter-trend / DEFENSIVE / mid-rip coil remain enforced elsewhere.
    """
    if not must_take:
        return False
    settings = get_settings()
    if not bool(getattr(settings, "top_must_take_bypasses_fake_trap", True)):
        return False
    if candidate is not None and not isinstance(alert, dict):
        raw = getattr(candidate, "alert", None)
        alert = raw if isinstance(raw, dict) else None
    try:
        from app.engines.index_tick_helpers import (
            evaluate_index_tick_helpers,
            index_helpers_confirm_from_alert,
        )

        if index_helpers_confirm_from_alert(alert):
            return True
        # Always allow must-take soft bypass when setting is on — index helpers
        # are preferred but near-base ATM/ITM ELITE already cleared must-take.
        if bool(
            getattr(settings, "top_must_take_fake_trap_requires_index", False)
        ):
            resolved_snap = snap
            if resolved_snap is None and candidate is not None:
                resolved_snap = getattr(candidate, "snap", None)
            side = ""
            if isinstance(alert, dict):
                side = str(alert.get("side") or "")
            if not side and candidate is not None:
                side = str(getattr(candidate, "side", "") or "")
            if resolved_snap is not None and side:
                idx = evaluate_index_tick_helpers(
                    snap=resolved_snap, side=side, alert=alert,
                )
                return bool(idx.confirming or idx.tick_align)
            return False
        return True
    except Exception:
        return bool(
            not getattr(settings, "top_must_take_fake_trap_requires_index", False)
        )


def building_rip_bypasses_extended_chase(
    *,
    alert: Optional[dict[str, Any]] = None,
    readiness_reason: str = "",
    candidate: Any = None,
) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "building_rip_bypasses_extended_chase", True)):
        return False
    return building_rip_bypasses_fake_trap(
        alert=alert,
        readiness_reason=readiness_reason,
        candidate=candidate,
    ) or pad_lane_bypasses_fake_trap(
        alert=alert,
        readiness_reason=readiness_reason,
        candidate=candidate,
    )
