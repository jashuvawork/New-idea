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
    ELITE/EXPLODING extreme-rip ALL-IN bypass — skip entry gates for a genuine rip.

    Inert by design under the current policy: the extended-chase ceiling
    (``extreme_all_in_bypass_max_move_pct``, 70%) sits *below* the extreme-move
    floors (``extreme_explosion_elite_move_min_pct`` 100% / ...all_in 150%), so no
    move can satisfy both — anything big enough to be "extreme" is already past the
    chase ceiling and must not skip gates (Jul17 24250 @ +91% PF killer). Genuine
    early base rips are handled by high-conviction sizing + the expiry elite-top
    bypass instead. The ``floor < ceiling`` guards below make that explicit and keep
    this a no-op unless a floor is ever deliberately re-tuned below the ceiling.
    """
    settings = get_settings()
    if not settings.extreme_explosion_all_in_enabled:
        return False

    tier, daily_move, score, mode = _metrics_from_sources(
        event=event, candidate=candidate, alert=alert,
    )
    if mode and mode != "explosion":
        return False

    max_move = float(getattr(settings, "extreme_all_in_bypass_max_move_pct", 70.0) or 70.0)
    if daily_move >= max_move:
        return False

    min_score = float(settings.extreme_explosion_all_in_min_score)
    elite_min = float(settings.extreme_explosion_elite_move_min_pct)
    all_in_min = float(settings.extreme_explosion_all_in_move_min_pct)

    if tier == "ELITE" and elite_min < max_move and daily_move >= elite_min and score >= min_score:
        return True
    if (
        tier in ("ELITE", "EXPLODING")
        and all_in_min < max_move
        and daily_move >= all_in_min
        and score >= min_score
    ):
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



def is_high_mover_elite_bypass(
    *,
    event: Optional[ExplosionEvent] = None,
    candidate: Any = None,
    alert: Optional[dict] = None,
) -> bool:
    """Aligned ELITE/EXPLODING rips — bypass last-N/cooldown only before chase ceiling."""
    if is_extreme_explosion_all_in_bypass(event=event, candidate=candidate, alert=alert):
        return True
    settings = get_settings()
    tier, daily_move, score, mode = _metrics_from_sources(
        event=event, candidate=candidate, alert=alert,
    )
    if mode and mode != "explosion":
        return False
    if tier not in ("ELITE", "EXPLODING"):
        return False
    max_move = float(getattr(settings, "high_mover_bypass_max_move_pct", 70.0) or 70.0)
    if daily_move >= max_move:
        return False
    # (An elite-move-floor branch used to sit here, but elite_move_min (100%) * 0.95 = 95%
    # is always above the 70% ceiling above, so it could never fire. Removed as dead code —
    # the rip_min / session-move branches below cover genuine sub-ceiling ELITE rips.)
    rip_min = float(getattr(settings, "vertical_rip_bypass_min_peak_pct", 30.0) or 30.0)
    if daily_move >= rip_min and score >= settings.all_day_explosion_min_score - 2:
        return True
    if daily_move >= settings.all_day_explosion_session_move_min_pct and score >= settings.all_day_explosion_min_score + 4:
        return True
    return False


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
