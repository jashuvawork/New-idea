"""Morning premium capture — catch chart-style CE/PE explosions (e.g. SENSEX 77800 CE 32→70)."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.engines.explosion_detector import ExplosionEvent
from app.models.schemas import Side, SpotChart, SymbolSnapshot
from app.services.upstox import get_market_phase


def in_morning_premium_capture_window() -> bool:
    """10:00–11:45 IST — primary morning premium expansion window."""
    if get_market_phase() != "LIVE_MARKET":
        return False
    settings = get_settings()
    if not settings.morning_premium_capture_enabled:
        return False
    from app.engines.chop_day_guards import _minutes_now

    current = _minutes_now()
    start = settings.morning_capture_start_hour * 60 + settings.morning_capture_start_minute
    end = settings.morning_capture_end_hour * 60 + settings.morning_capture_end_minute
    return start <= current < end


def _chart_confirms_side(side: Side | str, chart: Optional[SpotChart]) -> bool:
    if not chart:
        return True
    side_val = side.value if isinstance(side, Side) else str(side).upper()
    direction = (chart.direction or "NEUTRAL").upper()
    macd = (chart.macdBias or "NEUTRAL").upper()
    mom5 = chart.momentum5Pct or 0

    if side_val == "CALL":
        if direction == "BEARISH" and mom5 < -0.03:
            return False
        if macd == "BEARISH" and mom5 < 0:
            return False
        return True

    if direction == "BULLISH" and mom5 > 0.03:
        return False
    if macd == "BULLISH" and mom5 > 0:
        return False
    return True


def is_morning_capture_event(
    event: ExplosionEvent,
    *,
    chart: Optional[SpotChart] = None,
) -> bool:
    """True when a BUILDING/EXPLODING leg matches morning chart-style premium surge."""
    settings = get_settings()
    if not settings.morning_premium_capture_enabled:
        return False
    if not in_morning_premium_capture_window():
        return False
    if event.tier not in ("BUILDING", "EXPLODING", "ELITE"):
        return False
    if event.explosion_score < settings.morning_capture_building_min_score:
        return False

    v3 = event.velocity_3s
    v9 = event.velocity_9s
    vol = event.volume_surge
    vel_ok = v3 >= settings.morning_capture_min_velocity_3s or v9 >= settings.morning_capture_min_velocity_9s
    vol_ok = vol >= settings.morning_capture_min_vol_surge or v3 >= 2.5

    if not vel_ok or not vol_ok:
        return False

    if event.tier == "BUILDING":
        building_ok = (
            v3 >= settings.morning_capture_building_min_velocity_3s
            or (v9 >= settings.morning_capture_min_velocity_9s and vol >= settings.morning_capture_min_vol_surge)
        )
        if not building_ok:
            return False

    if chart and not _chart_confirms_side(event.side, chart):
        return False

    return True


def is_morning_capture_alert(alert: dict[str, Any], chart: Optional[SpotChart] = None) -> bool:
    from app.models.schemas import Side

    try:
        event = ExplosionEvent(
            symbol=str(alert.get("symbol", "")),
            side=Side(alert.get("side", "CALL")),
            strike=float(alert.get("strike", 0)),
            premium=float(alert.get("premium", 0)),
            velocity_3s=float(alert.get("velocity3s", 0)),
            velocity_9s=float(alert.get("velocity9s", 0)),
            velocity_15s=float(alert.get("velocity15s", 0)),
            volume_surge=float(alert.get("volumeSurge", 1)),
            explosion_score=float(alert.get("explosionScore", 0)),
            tier=str(alert.get("tier", "WATCH")),
            reason=str(alert.get("reason", "")),
        )
    except (TypeError, ValueError):
        return False
    return is_morning_capture_event(event, chart=chart)


def morning_capture_active(snapshots: Optional[dict[str, SymbolSnapshot]]) -> bool:
    """Any symbol showing a tradeable morning premium surge right now."""
    if not snapshots or not in_morning_premium_capture_window():
        return False
    for snap in snapshots.values():
        if not snap.dataAvailable:
            continue
        chart = snap.spotChart
        for alert in snap.explosionAlerts or []:
            if is_morning_capture_alert(alert, chart):
                return True
    return False


def morning_capture_rank_floor() -> float:
    settings = get_settings()
    return settings.morning_capture_min_rank_score
