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
) -> bool:
    """True when ELITE explosions must skip FOMO/chase/stand-down/live blocks."""
    settings = get_settings()
    if not getattr(settings, "explosion_elite_never_block_enabled", True):
        return False
    return _tier_from_sources(tier=tier, event=event, candidate=candidate, alert=alert) == "ELITE"
