"""Helper-confirmed BUILDING rip — capture ATM vertical legs on index thrust + pullback."""

from __future__ import annotations

from typing import Any, Mapping

from app.config import get_settings
from app.models.schemas import Side


def _side_val(side: Any) -> str:
    if isinstance(side, Side):
        return side.value
    return str(side or "").upper()


def effective_building_rip_velocity_3s(
    alert: Mapping[str, Any],
    *,
    settings: Any = None,
) -> float:
    settings = settings or get_settings()
    v3 = float(alert.get("velocity3s") or alert.get("tickVelocity3s") or 0)
    sym = str(alert.get("symbol") or "")
    strike = float(alert.get("strike") or 0)
    side = _side_val(alert.get("side"))
    if not sym or strike <= 0 or side not in ("CALL", "PUT"):
        return v3
    stamped_peak = float(alert.get("peakVelocity3s") or alert.get("retainedPeakVelocity3s") or 0)
    try:
        from app.engines.explosion_detector import retained_peak_velocity_3s

        side_enum = Side[side]
        state_peak = float(retained_peak_velocity_3s(sym, strike, side_enum))
    except Exception:
        state_peak = 0.0
    return max(v3, stamped_peak, state_peak)


def helper_confirmed_building_rip_active(
    alert: Mapping[str, Any],
    *,
    settings: Any = None,
) -> bool:
    settings = settings or get_settings()
    if not bool(getattr(settings, "building_rip_helper_capture_enabled", True)):
        return False
    if not bool(
        alert.get("ictBuildingRipReady")
        or alert.get("buildingRipReady")
    ):
        return False
    if not bool(
        alert.get("indexHelpersConfirm")
        or alert.get("buildingRipHelpersOk")
        or alert.get("buildingLiftHelping")
    ):
        return False
    bonus = float(alert.get("buildingHelperBonus") or 0)
    min_bonus = float(
        getattr(settings, "building_rip_helper_confirmed_min_bonus", 35.0) or 35.0
    )
    if bonus + 1e-6 < min_bonus:
        return False
    tier = str(alert.get("tier") or "").upper()
    if tier not in ("BUILDING", "EXPLODING", "ELITE"):
        return False
    retained_min = float(
        getattr(settings, "building_rip_pullback_min_retained_v3", 1.0) or 1.0
    )
    eff_v3 = effective_building_rip_velocity_3s(alert, settings=settings)
    live_v3 = float(alert.get("velocity3s") or 0)
    if live_v3 < 0 and eff_v3 + 1e-6 < retained_min:
        return False
    return True


def building_rip_ftv_local_move_pct(
    evidence: Mapping[str, Any],
    *,
    settings: Any = None,
) -> float:
    """Local-base % for BUILDING_RIP_FTV — cap chase misread on vertical index rip."""
    settings = settings or get_settings()
    move = float(evidence.get("localBaseMovePct") or 0)
    if not bool(evidence.get("buildingRipReady")):
        return move
    if not bool(
        evidence.get("indexHelpersConfirm")
        or evidence.get("buildingRipHelpersOk")
    ):
        return move
    cap = float(
        getattr(settings, "building_rip_ftv_helper_cap_local_pct", 28.0) or 28.0
    )
    ict_base = float(
        evidence.get("ictBaseRelativeMovePct")
        or evidence.get("armedBaseRelativeMovePct")
        or 0
    )
    if ict_base > 0:
        return min(move, max(ict_base, cap)) if move > cap else move
    if move > cap:
        return cap
    return move


def apply_helper_confirmed_building_rip_boost(alert: dict[str, Any]) -> dict[str, Any]:
    """After index/building helpers stamp — promote tradeable vertical CE/PE moments."""
    settings = get_settings()
    if not helper_confirmed_building_rip_active(alert, settings=settings):
        return alert

    eff_v3 = effective_building_rip_velocity_3s(alert, settings=settings)
    alert["velocity3s"] = eff_v3
    alert["retainedPeakVelocity3s"] = eff_v3
    min_score = float(
        getattr(settings, "building_rip_helper_confirmed_min_explosion_score", 85.0)
        or 85.0
    )
    score = max(float(alert.get("explosionScore") or 0), min_score)
    alert["explosionScore"] = score
    alert["radarExplosionScore"] = score
    if str(alert.get("tier") or "").upper() == "BUILDING":
        alert["tier"] = "EXPLODING"
    alert["tradeable"] = True
    alert["buildingRipReady"] = True
    alert["buildingRipHelpersOk"] = True

    move = float(alert.get("localBaseMovePct") or 0)
    capped = building_rip_ftv_local_move_pct(
        {
            "localBaseMovePct": move,
            "buildingRipReady": True,
            "indexHelpersConfirm": alert.get("indexHelpersConfirm"),
            "buildingRipHelpersOk": True,
            "ictBaseRelativeMovePct": alert.get("ictBaseRelativeMovePct"),
        },
        settings=settings,
    )
    if capped != move:
        alert["localBaseMovePct"] = capped
        alert["ictBaseRelativeMovePct"] = capped

    from app.engines.live_entry_score import stamp_alert_live_entry_scores

    return stamp_alert_live_entry_scores(alert)
