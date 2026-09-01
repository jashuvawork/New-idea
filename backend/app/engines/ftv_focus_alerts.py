"""Advisory FTV focus alerts — no auto entry.

Fires when live FTV timing, compressed local base, chart-aligned side, and
tradeable radar all agree on the same CE/PE direction.
"""

from __future__ import annotations

import time
from typing import Any, Mapping, Optional

from app.config import get_settings
from app.engines.spot_direction import index_trough_momentum_turn, side_aligned_with_chart
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


def _radar_at_local_base(alert: Mapping[str, Any]) -> bool:
    """True when tradeable radar is sitting on an option premium local-base pad."""
    from app.engines.early_radar_pad_capture import watch_local_base_pad_structure
    from app.engines.local_base_chart_bypass import _alert_has_local_base

    row = dict(alert)
    if _alert_has_local_base(row):
        return True
    return watch_local_base_pad_structure(row)


def _radar_has_index_momentum_flag(alert: Mapping[str, Any]) -> bool:
    return bool(
        alert.get("ictIndexTroughSlowV")
        or alert.get("indexTroughSlowV")
        or alert.get("ictIndexPeakSlowV")
        or alert.get("indexPeakSlowV")
    )


def _index_momentum_bypass(side: str, snapshot: SymbolSnapshot) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "ftv_focus_index_momentum_chart_bypass_enabled", True)):
        return False
    return index_trough_momentum_turn(side, snapshot.spotChart, settings=settings)


def _chart_aligned_for_focus(
    dominant: str,
    snapshot: SymbolSnapshot,
    radar: Optional[Mapping[str, Any]] = None,
) -> tuple[bool, bool]:
    """Return (aligned, used_momentum_bypass)."""
    if side_aligned_with_chart(dominant, snapshot.spotChart):
        return True, False
    if _index_momentum_bypass(dominant, snapshot):
        return True, True
    if radar is not None and _radar_has_index_momentum_flag(radar):
        return True, True
    return False, False


def _option_local_base_on_radar(snapshot: SymbolSnapshot, side: str) -> bool:
    side_u = side.upper()
    for alert in snapshot.explosionAlerts or []:
        if str(alert.get("side") or "").upper() != side_u:
            continue
        if _radar_at_local_base(alert):
            return True
    top = snapshot.topExplosion or {}
    if str(top.get("side") or "").upper() == side_u and _radar_at_local_base(top):
        return True
    return False


def _effective_local_base_ready(
    live: Mapping[str, Any],
    snapshot: SymbolSnapshot,
    dominant: str,
) -> tuple[bool, bool]:
    """Return (ready, used_option_led_base)."""
    if live.get("effectiveLocalBaseReady"):
        return True, bool(live.get("optionLocalBaseReady"))
    if live.get("localBaseReady"):
        return True, False
    settings = get_settings()
    if not bool(getattr(settings, "ftv_focus_option_local_base_enabled", True)):
        return False, False
    max_range = float(
        getattr(settings, "ftv_focus_option_local_base_max_index_range_pct", 0.45)
        or 0.45
    )
    base_range = float(live.get("baseRangePct") or 999.0)
    if base_range > max_range:
        return False, False
    if _option_local_base_on_radar(snapshot, dominant):
        return True, True
    return False, False


def _radar_meets_focus_threshold(alert: Mapping[str, Any]) -> bool:
    settings = get_settings()
    if alert.get("tradeable"):
        return True
    if not bool(getattr(settings, "ftv_focus_allow_building_radar", True)):
        return False
    tier = str(alert.get("tier") or "").upper()
    if tier not in {"BUILDING", "ELITE", "EXPLODING", "WATCH"}:
        return False
    score = float(alert.get("explosionScore") or 0)
    return score >= float(getattr(settings, "ftv_focus_min_radar_score", 35.0) or 35.0)


def _best_radar_alert(snapshot: SymbolSnapshot, side: str) -> Optional[dict[str, Any]]:
    side_u = side.upper()
    best: Optional[dict[str, Any]] = None
    best_score = -1.0
    for alert in snapshot.explosionAlerts or []:
        if str(alert.get("side") or "").upper() != side_u:
            continue
        if not _radar_meets_focus_threshold(alert):
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
        and _radar_meets_focus_threshold(top)
    ):
        return top
    return None


def _confidence_allows_focus(
    confidence: str,
    *,
    radar_score: float,
    used_momentum_bypass: bool,
    used_option_base: bool,
) -> bool:
    settings = get_settings()
    if _confidence_meets_minimum(confidence, settings.ftv_focus_min_confidence):
        return True
    if confidence != "LOW":
        return False
    if not (used_momentum_bypass or used_option_base):
        return False
    floor = float(
        getattr(settings, "ftv_focus_low_confidence_min_radar_score", 55.0) or 55.0
    )
    return radar_score >= floor


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

    dominant = str(live.get("dominantSide") or "NEUTRAL").upper()
    if dominant not in {"CALL", "PUT"}:
        return None

    local_base_ready, used_option_base = _effective_local_base_ready(
        live, snapshot, dominant,
    )
    if not local_base_ready:
        return None

    radar = _best_radar_alert(snapshot, dominant)
    if radar is None:
        return None
    if not _radar_at_local_base(radar):
        return None

    chart_aligned, used_momentum_bypass = _chart_aligned_for_focus(
        dominant, snapshot, radar,
    )
    if not chart_aligned:
        return None

    confidence = str(live.get("confidence") or "LOW").upper()
    radar_score = float(radar.get("explosionScore") or 0)
    if not _confidence_allows_focus(
        confidence,
        radar_score=radar_score,
        used_momentum_bypass=used_momentum_bypass,
        used_option_base=used_option_base,
    ):
        return None

    peak_probability = _side_peak_probability(live, dominant)
    if peak_probability < float(settings.ftv_focus_min_peak_probability_pct):
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

    meta = {
        "optionLedBase": used_option_base,
        "indexMomentumBypass": used_momentum_bypass,
        "radarTradeable": bool(radar.get("tradeable")),
    }

    if cooldown_remaining > 0:
        return {
            "id": alert_id,
            "symbol": symbol.upper(),
            "side": dominant,
            "status": "COOLDOWN",
            "confidence": confidence,
            "localBaseReady": True,
            "radarLocalBase": True,
            "chartAligned": True,
            "radarTradeable": bool(radar.get("tradeable")),
            "dominantSide": dominant,
            "peakProbabilityPct": round(peak_probability, 1),
            "estimatedWindow": live.get("estimatedWindow"),
            "baseRangePct": live.get("baseRangePct"),
            "radarStrike": radar.get("strike"),
            "radarTier": str(radar.get("tier") or "TRADEABLE").upper(),
            "radarScore": round(radar_score, 1),
            "cooldownSecRemaining": cooldown_remaining,
            "message": (
                f"FTV focus cooling · {symbol.upper()} {dominant} "
                f"({cooldown_remaining}s)"
            ),
            "asOf": live.get("asOf"),
            **meta,
        }

    _last_fired_mono[alert_id] = now
    active_alert = {
        "id": alert_id,
        "symbol": symbol.upper(),
        "side": dominant,
        "status": "ACTIVE",
        "confidence": confidence,
        "localBaseReady": True,
        "radarLocalBase": True,
        "chartAligned": True,
        "radarTradeable": bool(radar.get("tradeable")),
        "dominantSide": dominant,
        "peakProbabilityPct": round(peak_probability, 1),
        "estimatedWindow": live.get("estimatedWindow"),
        "baseRangePct": live.get("baseRangePct"),
        "radarStrike": radar.get("strike"),
        "radarTier": str(radar.get("tier") or "TRADEABLE").upper(),
        "radarScore": round(radar_score, 1),
        "cooldownSecRemaining": 0,
        "message": (
            f"FTV focus · {symbol.upper()} {dominant} · local base pad + "
            f"chart-aligned radar ({confidence.lower()} confidence)"
        ),
        "detail": (
            "Advisory only — confirm live premium, volume, and entry gates "
            "before acting."
        ),
        "asOf": live.get("asOf"),
        **meta,
    }
    from app.services.operator_event_log import append_operator_event

    append_operator_event("ftv_focus_active", active_alert)
    return active_alert


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
            "Soft focus alert only — never auto-enters. Fires at confirmed "
            "option local-base pads when FTV timing and chart-aligned radar agree."
        ),
    }
