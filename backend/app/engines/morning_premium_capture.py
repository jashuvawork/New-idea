"""Morning premium capture — catch chart-style CE/PE explosions (e.g. NIFTY 24350 CE open rip)."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.engines.explosion_detector import ExplosionEvent
from app.models.schemas import Side, SpotChart, SymbolSnapshot
from app.services.upstox import get_market_phase


def in_morning_premium_capture_window() -> bool:
    """09:15–11:45 IST — morning premium expansion (includes market open)."""
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


def _side_str(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def _best_surge_for_side(
    snap: SymbolSnapshot,
    side: str,
) -> tuple[float, float, float, str]:
    """Best (v3, v9, score, tier) for one option side on this symbol."""
    side = side.upper()
    best_v3, best_v9, best_score, best_tier = 0.0, 0.0, 0.0, ""
    for alert in snap.explosionAlerts or []:
        if _side_str(alert.get("side", "")) != side:
            continue
        v3 = float(alert.get("velocity3s", 0) or 0)
        v9 = float(alert.get("velocity9s", 0) or 0)
        score = float(alert.get("explosionScore", 0) or 0)
        tier = str(alert.get("tier", "WATCH"))
        if v3 >= best_v3:
            best_v3, best_v9, best_score, best_tier = v3, v9, score, tier
    for entry in snap.explosiveRunnerWatchlist or []:
        if _side_str(entry.get("side", "")) != side:
            continue
        vel = float(entry.get("premiumVelocityPct", 0) or 0)
        if vel >= best_v3:
            best_v3 = vel
            best_v9 = max(best_v9, vel)
            best_score = max(best_score, float(entry.get("score", 0) or 0))
            best_tier = str(entry.get("tier", best_tier) or best_tier)
    return best_v3, best_v9, best_score, best_tier


def premium_led_entry_allowed(
    side: Side | str,
    snap: SymbolSnapshot,
) -> bool:
    """
    Option premium velocity leads index breadth — allow CE in bearish chop (or PE in bullish)
    when the leg itself is exploding at the open.
    """
    settings = get_settings()
    if not settings.premium_led_counter_breadth_enabled:
        return False
    if not in_morning_premium_capture_window():
        return False
    v3, v9, score, tier = _best_surge_for_side(snap, _side_str(side))
    if tier in ("BUILDING", "EXPLODING", "ELITE") and score >= settings.premium_led_min_explosion_score:
        if v3 >= settings.premium_led_min_velocity_3s or v9 >= settings.premium_led_min_velocity_9s:
            return True
    if v3 >= settings.premium_led_min_velocity_3s + 0.7:
        return True
    return False


def dominant_single_side_surge(snap: SymbolSnapshot) -> bool:
    """One leg ripping much faster than the other — not CE↔PE whipsaw."""
    settings = get_settings()
    if not settings.whipsaw_single_side_surge_bypass_enabled:
        return False

    watchlist = snap.explosiveRunnerWatchlist or []
    best_call = 0.0
    best_put = 0.0
    for entry in watchlist:
        side = _side_str(entry.get("side", ""))
        vel = float(entry.get("premiumVelocityPct", 0) or 0)
        if side == "CALL":
            best_call = max(best_call, vel)
        elif side == "PUT":
            best_put = max(best_put, vel)

    for alert in snap.explosionAlerts or []:
        tier = str(alert.get("tier", "")).upper()
        v3 = float(alert.get("velocity3s", 0) or 0)
        if tier in ("BUILDING", "EXPLODING", "ELITE") and v3 >= settings.whipsaw_dominant_velocity_min:
            return True
        side = _side_str(alert.get("side", ""))
        if side == "CALL":
            best_call = max(best_call, v3)
        elif side == "PUT":
            best_put = max(best_put, v3)

    dominant = max(best_call, best_put)
    weaker = min(best_call, best_put)
    if dominant < settings.whipsaw_dominant_velocity_min:
        return False
    if weaker <= 0.05:
        return True
    return dominant / weaker >= settings.whipsaw_dominant_velocity_ratio


def single_side_surge_session_bypass(snapshots: Optional[dict[str, SymbolSnapshot]]) -> bool:
    """Bypass whipsaw session pause when a single leg is clearly dominating at the open."""
    if not snapshots:
        return False
    settings = get_settings()
    if not settings.whipsaw_single_side_surge_bypass_enabled:
        return False
    from app.engines.session_timing import in_open_caution_window

    if not (in_morning_premium_capture_window() or in_open_caution_window()):
        return False
    return any(
        snap.dataAvailable and dominant_single_side_surge(snap)
        for snap in snapshots.values()
    )


def _chart_confirms_side(side: Side | str, chart: Optional[SpotChart]) -> bool:
    if not chart:
        return True
    side_val = _side_str(side)
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


def _chart_ok_for_morning_event(event: ExplosionEvent, chart: Optional[SpotChart]) -> bool:
    if _chart_confirms_side(event.side, chart):
        return True
    settings = get_settings()
    if not settings.morning_capture_skip_chart_on_extreme_velocity:
        return False
    return (
        event.velocity_3s >= settings.morning_capture_extreme_velocity_3s
        or event.velocity_9s >= settings.morning_capture_extreme_velocity_9s
    )


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

    if chart and not _chart_ok_for_morning_event(event, chart):
        return False

    return True


def is_morning_capture_alert(alert: dict[str, Any], chart: Optional[SpotChart] = None) -> bool:
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
