"""Extreme session rips (ELITE +100%+) — ALL-IN bypass for gates AI report surfaces."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.engines.explosion_detector import ExplosionEvent
from app.models.schemas import Side, SymbolSnapshot


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def _metrics_from_sources(
    *,
    event: Optional[ExplosionEvent] = None,
    candidate: Any = None,
    alert: Optional[dict] = None,
) -> tuple[str, float, float, str]:
    tier = ""
    daily_move = 0.0
    score = 0.0
    mode = ""

    if event is not None:
        tier = str(event.tier or "").upper()
        daily_move = float(getattr(event, "daily_move_pct", 0) or 0)
        peak = float(getattr(event, "peak_move_pct", 0) or 0)
        if peak > daily_move:
            daily_move = peak
        score = float(event.explosion_score or 0)
        mode = "explosion"

    if candidate is not None:
        mode = mode or str(getattr(candidate, "mode", "") or "")
        tier = tier or str(getattr(candidate, "tier", "") or "").upper()
        score = max(score, float(getattr(candidate, "score", 0) or 0))
        ev = getattr(candidate, "explosion_event", None)
        if isinstance(ev, ExplosionEvent):
            tier = tier or str(ev.tier or "").upper()
            daily_move = max(daily_move, float(ev.daily_move_pct or 0))
            peak = float(getattr(ev, "peak_move_pct", 0) or 0)
            if peak > daily_move:
                daily_move = peak
            score = max(score, float(ev.explosion_score or 0))
        alert = alert or getattr(candidate, "alert", None) or {}

    if alert:
        tier = tier or str(alert.get("tier", "")).upper()
        dm = float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0)
        peak = float(alert.get("peakMovePct") or 0)
        if peak > dm:
            dm = max(dm, peak * 0.65)
        daily_move = max(daily_move, dm)
        score = max(score, float(alert.get("explosionScore") or 0))

    return tier, daily_move, score, mode


def is_extreme_explosion_all_in_bypass(
    *,
    event: Optional[ExplosionEvent] = None,
    candidate: Any = None,
    alert: Optional[dict] = None,
) -> bool:
    """
    ELITE +100%+ or any tier +150%+ session premium move — bypass ALL entry gates.
    Matches AI report rows like SENSEX PUT 76800 · 497% ELITE.
    """
    settings = get_settings()
    if not settings.extreme_explosion_all_in_enabled:
        return False

    tier, daily_move, score, mode = _metrics_from_sources(
        event=event, candidate=candidate, alert=alert,
    )
    if mode and mode != "explosion":
        return False

    min_score = float(settings.extreme_explosion_all_in_min_score)
    elite_min = float(settings.extreme_explosion_elite_move_min_pct)
    all_in_min = float(settings.extreme_explosion_all_in_move_min_pct)

    if tier == "ELITE" and daily_move >= elite_min and score >= min_score:
        return True
    if tier in ("ELITE", "EXPLODING") and daily_move >= all_in_min and score >= min_score:
        return True
    return False


def extreme_all_in_meta(
    *,
    event: Optional[ExplosionEvent] = None,
    candidate: Any = None,
    alert: Optional[dict] = None,
) -> dict[str, Any]:
    tier, daily_move, score, _ = _metrics_from_sources(
        event=event, candidate=candidate, alert=alert,
    )
    return {
        "extremeAllInBypass": True,
        "extremeDailyMovePct": round(daily_move, 1),
        "extremeTier": tier,
        "extremeScore": round(score, 1),
    }


def snapshots_have_all_in_explosion(
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """Session-level: any symbol showing an AI-reportable extreme rip."""
    for snap in snapshots.values():
        if not snap.dataAvailable:
            continue
        for alert in snap.explosionAlerts or []:
            if is_extreme_explosion_all_in_bypass(alert=alert):
                return True
    return False
