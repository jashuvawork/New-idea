"""Lower entry floors on confirmed bullish / momentum-rally sessions."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import AutoTraderState, SymbolSnapshot


def _resolve_day_mode(
    day_mode: str,
    state: Any = None,
) -> str:
    dm = (day_mode or "").upper()
    if dm:
        return dm
    if state is not None:
        ds = getattr(state, "dailyStrategy", None) or {}
        if isinstance(ds, dict):
            return str(ds.get("dayMode") or "").upper()
        return str(getattr(ds, "dayMode", "") or "").upper()
    try:
        from app.engines.daily_18pct_strategy import get_session_limits

        limits = get_session_limits()
        return str(getattr(limits, "dayMode", "") or "").upper() if limits else ""
    except Exception:
        return ""


def _resolve_confidence_tier(confidence_tier: str, state: Any = None) -> str:
    tier = (confidence_tier or "").upper()
    if tier:
        return tier
    if state is not None:
        ds = getattr(state, "dailyStrategy", None) or {}
        if isinstance(ds, dict):
            return str(ds.get("confidenceTier") or "").upper()
    return ""


def bullish_day_context_active(
    *,
    day_mode: str = "",
    confidence_tier: str = "",
    state: Optional[AutoTraderState] = None,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
) -> bool:
    """BULLISH / MOMENTUM RALLY + HIGH/ELITE confidence — relax entry floors."""
    settings = get_settings()
    if not getattr(settings, "bullish_day_floor_relief_enabled", True):
        return False

    dm = _resolve_day_mode(day_mode, state)
    tier = _resolve_confidence_tier(confidence_tier, state)
    rally_day = any(x in dm for x in ("BULLISH", "MOMENTUM RALLY", "RALLY"))
    if not rally_day:
        return False
    if tier not in ("ELITE", "HIGH"):
        return False

    if state is not None and snapshots:
        from app.engines.dual_mode_strategy import good_day_session_active

        active, _ = good_day_session_active(
            state,
            snapshots,
            day_mode=dm,
            confidence_tier=tier,
        )
        return active
    return True


def bullish_day_first_lift_floors(settings: Any = None) -> dict[str, float]:
    settings = settings or get_settings()
    return {
        "minMove": float(
            getattr(settings, "bullish_day_structured_min_move_pct", 8.0) or 8.0
        ),
        "minScore": float(
            getattr(settings, "bullish_day_first_lift_min_score", 45.0) or 45.0
        ),
        "minQuality": float(
            getattr(settings, "bullish_day_first_lift_min_quality", 50.0) or 50.0
        ),
        "immatureLocalBaseMinMove": float(
            getattr(settings, "bullish_day_immature_local_base_min_move_pct", 8.0)
            or 8.0
        ),
        "structureBypassMinScore": float(
            getattr(settings, "bullish_day_structure_bypass_min_score", 55.0) or 55.0
        ),
        "structureBypassMinBaseMove": float(
            getattr(settings, "bullish_day_structure_bypass_min_base_move_pct", 2.0)
            or 2.0
        ),
    }


def bullish_day_structure_bypass_allowed(
    *,
    tier: str,
    score: float,
    base_move_pct: float,
    volume_awakening: bool,
    day_mode: str = "",
    confidence_tier: str = "",
    state: Any = None,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
) -> bool:
    """EXPLODING/ELITE on bullish day may enter before flat→vertical confirms."""
    settings = get_settings()
    if not bullish_day_context_active(
        day_mode=day_mode,
        confidence_tier=confidence_tier,
        state=state,
        snapshots=snapshots,
    ):
        return False
    allowed = {
        t.strip().upper()
        for t in str(
            getattr(settings, "bullish_day_structure_bypass_tiers_csv", "ELITE,EXPLODING")
            or "ELITE,EXPLODING"
        ).split(",")
        if t.strip()
    }
    if str(tier or "").upper() not in allowed:
        return False
    floors = bullish_day_first_lift_floors(settings)
    if float(score or 0) + 1e-9 < floors["structureBypassMinScore"]:
        return False
    if volume_awakening:
        return True
    return float(base_move_pct or 0) + 1e-9 >= floors["structureBypassMinBaseMove"]
