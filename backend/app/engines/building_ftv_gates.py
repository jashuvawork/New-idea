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
    )
