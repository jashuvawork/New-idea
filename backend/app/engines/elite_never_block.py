"""ELITE tier — never block entry (user policy: take every ELITE explosion)."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import Side


def _tier_from_sources(
    *,
    tier: Optional[str] = None,
    event: Any = None,
    candidate: Any = None,
    alert: Optional[dict] = None,
) -> str:
    if tier:
        return str(tier).upper()
    if event is not None:
        t = str(getattr(event, "tier", "") or "").upper()
        if t:
            return t
    if candidate is not None:
        t = str(getattr(candidate, "tier", "") or "").upper()
        if t:
            return t
        ev = getattr(candidate, "explosion_event", None)
        if ev is not None:
            t = str(getattr(ev, "tier", "") or "").upper()
            if t:
                return t
        alert = alert or getattr(candidate, "alert", None)
    if isinstance(alert, dict):
        return str(alert.get("tier") or "").upper()
    return ""


def elite_never_block_active(
    *,
    tier: Optional[str] = None,
    event: Any = None,
    candidate: Any = None,
    alert: Optional[dict] = None,
    timing: Optional[dict] = None,
    snap: Any = None,
) -> bool:
    """True when ELITE explosions may skip FOMO/chase/stand-down/live blocks.

    Cold / late / chase timing never gets the bypass — Aug4 NIFTY 24550 PUT was
    ELITE with live v3=0.8 and still skipped live-confirm into a never-green loss.
    """
    settings = get_settings()
    if not getattr(settings, "explosion_elite_never_block_enabled", True):
        return False
    if _tier_from_sources(tier=tier, event=event, candidate=candidate, alert=alert) != "ELITE":
        return False

    if not bool(getattr(settings, "entry_timing_elite_bypass_requires_hot", True)):
        return True

    resolved_timing = timing
    resolved_event = event
    if resolved_event is None and candidate is not None:
        resolved_event = getattr(candidate, "explosion_event", None)

    if resolved_timing is None and resolved_event is not None:
        try:
            from app.engines.entry_timing import assess_timing_for_event
            from app.engines.morning_premium_capture import is_premium_capture_event

            chart = getattr(snap, "spotChart", None) if snap is not None else None
            resolved_timing = assess_timing_for_event(
                resolved_event,
                snap=snap,
                premium_capture=is_premium_capture_event(resolved_event, chart=chart),
            )
        except Exception:
            resolved_timing = None

    # Fail closed: without a GOOD timing verdict, ELITE does not skip FOMO gates.
    if resolved_timing is None:
        return False
    from app.engines.entry_timing import elite_bypass_allowed_for_timing

    return elite_bypass_allowed_for_timing(resolved_timing)
