"""Advisory FTV focus alerts — no auto entry.

Fires when live FTV timing, compressed local base, chart-aligned side, and
tradeable radar all agree on the same CE/PE direction.
"""

from __future__ import annotations

import time
from typing import Any, Mapping, Optional

from app.config import get_settings
from app.engines.spot_direction import side_aligned_with_chart
from app.models.schemas import SymbolSnapshot

_CONFIDENCE_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
_last_fired_mono: dict[str, float] = {}


def clear_ftv_focus_alert_state() -> None:
    """Reset cooldown memory (tests and explicit deployment resets)."""
    _last_fired_mono.clear()


def _confidence_meets_minimum(confidence: str, minimum: str) -> bool:
    return _CONFIDENCE_RANK.get(confidence.upper(), 0) >= _CONFIDENCE_RANK.get(
        minimum.upper(), 1,
    )


def _side_peak_probability(live: Mapping[str, Any], side: str) -> float:
    side_row = (live.get("sides") or {}).get(side) or {}
    probabilities = side_row.get("probabilities") or {}
    if not probabilities:
        return 0.0
    return max(float(value) for value in probabilities.values())


def _best_radar_alert(snapshot: SymbolSnapshot, side: str) -> Optional[dict[str, Any]]:
    side_u = side.upper()
    best: Optional[dict[str, Any]] = None
    best_score = -1.0
    for alert in snapshot.explosionAlerts or []:
        if str(alert.get("side") or "").upper() != side_u:
            continue
        if not alert.get("tradeable"):
            continue
        score = float(alert.get("explosionScore") or 0)
        if score >= best_score:
            best = alert
            best_score = score
    if best is not None:
        return best
    top = snapshot.topExplosion or {}
    if (
        str(top.get("side") or "").upper() == side_u
        and top.get("tradeable", True)
    ):
        return top
    return None


def evaluate_ftv_focus_alert(
    symbol: str,
    snapshot: SymbolSnapshot,
    live: Mapping[str, Any],
    *,
    now_mono: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    """Return one advisory focus alert when all soft gates align."""
    settings = get_settings()
    if not settings.ftv_focus_alerts_enabled:
        return None
    if not live.get("liveReady"):
        return None
    if not live.get("localBaseReady"):
        return None

    confidence = str(live.get("confidence") or "LOW").upper()
    if not _confidence_meets_minimum(
        confidence, settings.ftv_focus_min_confidence,
    ):
        return None

    dominant = str(live.get("dominantSide") or "NEUTRAL").upper()
    if dominant not in {"CALL", "PUT"}:
        return None
    if not side_aligned_with_chart(dominant, snapshot.spotChart):
        return None

    peak_probability = _side_peak_probability(live, dominant)
    if peak_probability < float(settings.ftv_focus_min_peak_probability_pct):
        return None

    radar = _best_radar_alert(snapshot, dominant)
    if radar is None:
        return None

    alert_id = f"ftv-focus:{symbol.upper()}:{dominant}"
    now = now_mono if now_mono is not None else time.monotonic()
    cooldown = max(30, int(settings.ftv_focus_cooldown_seconds))
    last_fired = _last_fired_mono.get(alert_id)
    cooldown_remaining = 0
    if last_fired is not None:
        elapsed = now - last_fired
        if elapsed < cooldown:
            cooldown_remaining = int(cooldown - elapsed)
        else:
            _last_fired_mono.pop(alert_id, None)

    if cooldown_remaining > 0:
        return {
            "id": alert_id,
            "symbol": symbol.upper(),
            "side": dominant,
            "status": "COOLDOWN",
            "confidence": confidence,
            "localBaseReady": True,
            "chartAligned": True,
            "radarTradeable": True,
            "dominantSide": dominant,
            "peakProbabilityPct": round(peak_probability, 1),
            "estimatedWindow": live.get("estimatedWindow"),
            "baseRangePct": live.get("baseRangePct"),
            "radarStrike": radar.get("strike"),
            "radarTier": str(radar.get("tier") or "TRADEABLE").upper(),
            "radarScore": round(float(radar.get("explosionScore") or 0), 1),
            "cooldownSecRemaining": cooldown_remaining,
            "message": (
                f"FTV focus cooling · {symbol.upper()} {dominant} "
                f"({cooldown_remaining}s)"
            ),
            "asOf": live.get("asOf"),
        }

    _last_fired_mono[alert_id] = now
    return {
        "id": alert_id,
        "symbol": symbol.upper(),
        "side": dominant,
        "status": "ACTIVE",
        "confidence": confidence,
        "localBaseReady": True,
        "chartAligned": True,
        "radarTradeable": True,
        "dominantSide": dominant,
        "peakProbabilityPct": round(peak_probability, 1),
        "estimatedWindow": live.get("estimatedWindow"),
        "baseRangePct": live.get("baseRangePct"),
        "radarStrike": radar.get("strike"),
        "radarTier": str(radar.get("tier") or "TRADEABLE").upper(),
        "radarScore": round(float(radar.get("explosionScore") or 0), 1),
        "cooldownSecRemaining": 0,
        "message": (
            f"FTV focus · {symbol.upper()} {dominant} · compressed base + "
            f"chart-aligned radar ({confidence.lower()} confidence)"
        ),
        "detail": (
            "Advisory only — confirm live premium, volume, and entry gates "
            "before acting."
        ),
        "asOf": live.get("asOf"),
    }


def build_ftv_focus_alerts(
    snapshots: Mapping[str, SymbolSnapshot],
    ftv_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Build dashboard-level focus alerts from FTV live estimates."""
    settings = get_settings()
    if not settings.ftv_focus_alerts_enabled or not ftv_payload.get("enabled"):
        return {"enabled": False, "active": [], "status": "DISABLED"}

    alerts: list[dict[str, Any]] = []
    for symbol, row in (ftv_payload.get("symbols") or {}).items():
        snapshot = snapshots.get(symbol)
        live = row.get("live") or {}
        if snapshot is None:
            continue
        alert = evaluate_ftv_focus_alert(symbol, snapshot, live)
        if alert is not None:
            alerts.append(alert)

    alerts.sort(
        key=lambda row: (
            row.get("status") == "ACTIVE",
            row.get("confidence") == "HIGH",
            row.get("peakProbabilityPct", 0),
            row.get("radarScore", 0),
        ),
        reverse=True,
    )
    active = [row for row in alerts if row.get("status") == "ACTIVE"]
    return {
        "enabled": True,
        "status": "LIVE" if active else ("COOLDOWN" if alerts else "WAITING"),
        "active": active,
        "recent": alerts,
        "guardrail": (
            "Soft focus alert only — never auto-enters. Radar tradeable plus "
            "FTV timing alignment is a watchlist cue, not a GO signal."
        ),
    }
