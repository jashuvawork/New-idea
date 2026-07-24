"""Premium capture — morning open rips and afternoon consolidation breakouts."""

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


def in_afternoon_premium_capture_window() -> bool:
    """11:45–15:25 IST — afternoon momentum / consolidation breakouts."""
    if get_market_phase() != "LIVE_MARKET":
        return False
    settings = get_settings()
    if not settings.afternoon_premium_capture_enabled:
        return False
    from app.engines.chop_day_guards import in_momentum_rally_window

    return in_momentum_rally_window() and not in_morning_premium_capture_window()


def in_all_day_explosion_window() -> bool:
    """09:20–15:25 IST — monitor explosive premium moves all session."""
    if get_market_phase() != "LIVE_MARKET":
        return False
    settings = get_settings()
    if not settings.all_day_explosion_capture_enabled:
        return False
    from app.engines.chop_day_guards import _minutes_now

    current = _minutes_now()
    start = settings.all_day_explosion_start_hour * 60 + settings.all_day_explosion_start_minute
    end = settings.all_day_explosion_end_hour * 60 + settings.all_day_explosion_end_minute
    return start <= current < end


def in_premium_capture_window() -> bool:
    return (
        in_morning_premium_capture_window()
        or in_afternoon_premium_capture_window()
        or in_all_day_explosion_window()
    )


def _effective_dominant_velocity_min() -> float:
    settings = get_settings()
    if in_afternoon_premium_capture_window():
        return settings.afternoon_capture_dominant_velocity_min
    return settings.whipsaw_dominant_velocity_min


def _effective_dominant_velocity_ratio() -> float:
    settings = get_settings()
    if in_afternoon_premium_capture_window():
        return settings.afternoon_capture_dominant_velocity_ratio
    return settings.whipsaw_dominant_velocity_ratio


def _is_counter_breadth(side: Side | str, breadth_bias: str) -> bool:
    side_v = _side_str(side)
    bias = (breadth_bias or "NEUTRAL").upper()
    return (bias == "BULLISH" and side_v == "PUT") or (bias == "BEARISH" and side_v == "CALL")


def _market_opposes_side(
    side: Side | str,
    breadth_bias: str,
    chart: Optional[SpotChart],
    *,
    snap: Optional[SymbolSnapshot] = None,
    event: Any = None,
    alert: Optional[dict[str, Any]] = None,
) -> bool:
    """True when breadth or a strong index chart conflicts with the trade leg."""
    if snap is not None:
        from app.engines.local_base_chart_bypass import local_base_overrides_side_bias

        if local_base_overrides_side_bias(side, snap, event=event, alert=alert):
            return False

    settings = get_settings()
    side_v = _side_str(side)
    bias = (breadth_bias or "NEUTRAL").upper()
    direction = (chart.direction or "NEUTRAL").upper() if chart else "NEUTRAL"
    trend = float(chart.trendStrength or 0) if chart else 0.0
    min_strength = float(settings.chart_min_trend_strength or 25.0)

    if side_v == "PUT":
        if direction == "BEARISH":
            mom = float(chart.momentum5Pct or 0) if chart else 0.0
            if trend >= min_strength or mom <= -0.06:
                return False
        if bias == "BULLISH":
            return True
        if direction == "BULLISH" and trend >= min_strength:
            return True
    elif side_v == "CALL":
        if bias == "BEARISH":
            return True
        if direction == "BEARISH" and trend >= min_strength:
            return True
    return False


def _session_move_pct(event: ExplosionEvent) -> float:
    daily = float(getattr(event, "daily_move_pct", 0) or 0)
    peak = float(getattr(event, "peak_move_pct", 0) or 0)
    return max(daily, peak)


def _counter_trend_rip_ok(event: ExplosionEvent, settings: Any) -> bool:
    """Premium-led vertical rip — allow counter-chart/breadth before ELITE tier peaks."""
    from app.engines.vertical_rip_bypass import qualifies_for_vertical_rip_bypass

    if qualifies_for_vertical_rip_bypass(event):
        return True

    tier = str(event.tier or "").upper()
    if tier not in ("BUILDING", "EXPLODING", "ELITE"):
        return False

    session_move = _session_move_pct(event)
    score = float(event.explosion_score or 0)
    v3 = float(event.velocity_3s or 0)
    v9 = float(event.velocity_9s or 0)
    min_peak = float(getattr(settings, "vertical_rip_bypass_min_peak_pct", 30.0) or 30.0)
    min_score = float(getattr(settings, "premium_led_min_explosion_score", 42.0) or 42.0)
    min_v3 = float(getattr(settings, "premium_led_min_velocity_3s", 2.8) or 2.8)
    min_v9 = float(getattr(settings, "premium_led_min_velocity_9s", 3.5) or 3.5)
    vel_ok = v3 >= min_v3 or v9 >= min_v9

    if tier in ("EXPLODING", "ELITE") and session_move >= min_peak and vel_ok:
        return score >= min_score - 6
    if tier == "BUILDING" and session_move >= min_peak * 0.7 and v3 >= min_v3 * 0.75:
        return score >= min_score - 4
    return False


def _elite_counter_breadth_ok(event: ExplosionEvent, settings: Any) -> bool:
    """Counter-trend premium rip — ELITE tier with vertical peak or near-max explosion score."""
    from app.engines.vertical_rip_bypass import qualifies_for_vertical_rip_bypass

    tier = str(event.tier or "").upper()
    if tier == "ELITE" and qualifies_for_vertical_rip_bypass(event):
        return True
    if tier != "ELITE":
        return False
    score = float(event.explosion_score or 0)
    elite_min = float(getattr(settings, "premium_led_elite_counter_min_score", 90.0) or 90.0)
    if score < elite_min:
        return False
    v3 = float(event.velocity_3s or 0)
    v9 = float(event.velocity_9s or 0)
    return v3 >= settings.premium_led_min_velocity_3s or v9 >= settings.premium_led_min_velocity_9s


def counter_trend_entry_allowed(
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    explosion_event: Optional[ExplosionEvent] = None,
) -> bool:
    """Block counter-trend legs — extreme ALL-IN rips bypass."""
    if explosion_event is not None:
        from app.engines.extreme_explosion_moment import is_extreme_explosion_all_in_bypass
        from app.engines.vertical_rip_bypass import qualifies_for_vertical_rip_bypass

        if is_extreme_explosion_all_in_bypass(event=explosion_event):
            return True
        if qualifies_for_vertical_rip_bypass(explosion_event, snap=snap):
            return True
        side_v = _side_str(side)
        if side_v == "CALL" and _counter_trend_rip_ok(explosion_event, get_settings()):
            return True
    from app.engines.local_base_chart_bypass import (
        local_base_ichimoku_bypass_for_snap,
        local_base_overrides_side_bias,
    )

    if local_base_ichimoku_bypass_for_snap(side, snap, explosion_event=explosion_event):
        return True
    if local_base_overrides_side_bias(side, snap, event=explosion_event):
        return True
    bias = (snap.breadth.bias if snap.breadth else "NEUTRAL") or "NEUTRAL"
    from app.engines.aligned_side_guard import breadth_hard_blocks_side

    hard_blocked, _ = breadth_hard_blocks_side(
        side, bias, event=explosion_event, snap=snap,
    )
    if hard_blocked:
        return False
    if not _market_opposes_side(side, bias, snap.spotChart, snap=snap, event=explosion_event):
        return True
    if explosion_event is None:
        return False
    return _elite_counter_breadth_ok(explosion_event, get_settings())


def premium_led_entry_allowed(
    side: Side | str,
    snap: SymbolSnapshot,
) -> bool:
    """
    Option premium velocity leads index breadth — allow CE in bearish chop (or PE in bullish)
    when the leg itself is exploding at the open or afternoon rally window.
    """
    settings = get_settings()
    if not settings.premium_led_counter_breadth_enabled:
        return False
    if not in_premium_capture_window():
        return False
    side_v = _side_str(side)
    bias = (snap.breadth.bias if snap.breadth else "NEUTRAL") or "NEUTRAL"
    from app.engines.aligned_side_guard import breadth_hard_blocks_side
    from app.engines.local_base_chart_bypass import local_base_overrides_side_bias

    hard_blocked, _ = breadth_hard_blocks_side(side_v, bias, snap=snap)
    if hard_blocked:
        return False
    v3, v9, score, tier = _best_surge_for_side(snap, side_v)
    local_base_ok = local_base_overrides_side_bias(side_v, snap)
    if (
        not local_base_ok
        and (
            _is_counter_breadth(side_v, bias)
            or _market_opposes_side(side_v, bias, snap.spotChart, snap=snap)
        )
    ):
        settings_elite = float(getattr(settings, "premium_led_elite_counter_min_score", 90.0) or 90.0)
        if tier != "ELITE" or score < settings_elite:
            return False
        if v3 >= settings.premium_led_min_velocity_3s or v9 >= settings.premium_led_min_velocity_9s:
            return True
        return False
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
    vel_min = _effective_dominant_velocity_min()
    vel_ratio = _effective_dominant_velocity_ratio()
    if dominant < vel_min:
        return False
    if weaker <= 0.05:
        return True
    return dominant / weaker >= vel_ratio


def single_side_surge_session_bypass(snapshots: Optional[dict[str, SymbolSnapshot]]) -> bool:
    """Bypass whipsaw session pause when a single leg is clearly dominating at the open."""
    if not snapshots:
        return False
    settings = get_settings()
    if not settings.whipsaw_single_side_surge_bypass_enabled:
        return False
    from app.engines.session_timing import in_open_caution_window

    if not (in_premium_capture_window() or in_open_caution_window()):
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
    open_move = float(event.daily_move_pct or 0)
    open_min = float(getattr(settings, "open_premium_min_move_pct", 25.0) or 25.0)
    open_bypass_score = float(getattr(settings, "open_premium_bypass_min_score", 35.0) or 35.0)
    open_chart_bypass = float(getattr(settings, "open_premium_chart_bypass_move_pct", 20.0) or 20.0)
    if open_move >= open_min:
        return True
    if not settings.morning_capture_skip_chart_on_extreme_velocity:
        return False
    return (
        event.velocity_3s >= settings.morning_capture_extreme_velocity_3s
        or event.velocity_9s >= settings.morning_capture_extreme_velocity_9s
        or open_move >= open_chart_bypass
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
    open_move = float(event.daily_move_pct or 0)
    open_min = float(getattr(settings, "open_premium_min_move_pct", 25.0) or 25.0)
    open_bypass_score = float(getattr(settings, "open_premium_bypass_min_score", 35.0) or 35.0)
    open_chart_bypass = float(getattr(settings, "open_premium_chart_bypass_move_pct", 20.0) or 20.0)
    if open_move >= open_min:
        vel_ok = True
    vol_ok = vol >= settings.morning_capture_min_vol_surge or v3 >= 2.5
    if open_move >= open_min:
        vol_ok = True

    if not vel_ok or not vol_ok:
        return False

    if event.tier == "BUILDING":
        building_ok = (
            v3 >= settings.morning_capture_building_min_velocity_3s
            or (v9 >= settings.morning_capture_min_velocity_9s and vol >= settings.morning_capture_min_vol_surge)
            or open_move >= open_min
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


def _is_consolidation_breakout(event: ExplosionEvent) -> bool:
    """Volume-confirmed base breakout — catches slow 1pm grinds before 3s velocity spikes."""
    settings = get_settings()
    vol = event.volume_surge
    if vol < settings.afternoon_capture_consolidation_vol_surge:
        return False
    if event.explosion_score < settings.afternoon_capture_building_min_score:
        return False
    return (
        event.velocity_9s >= settings.afternoon_capture_consolidation_velocity_9s
        or event.velocity_3s >= settings.afternoon_capture_building_min_velocity_3s
    )


def _chart_ok_for_afternoon_event(event: ExplosionEvent, chart: Optional[SpotChart]) -> bool:
    if _chart_confirms_side(event.side, chart):
        return True
    settings = get_settings()
    if not settings.afternoon_capture_skip_chart_on_volume:
        return False
    if event.volume_surge >= settings.afternoon_capture_chart_bypass_vol_surge:
        if (
            event.velocity_9s >= settings.afternoon_capture_chart_bypass_velocity_9s
            or event.velocity_3s >= settings.afternoon_capture_min_velocity_3s
        ):
            return True
    return (
        event.velocity_3s >= settings.morning_capture_extreme_velocity_3s
        or event.velocity_9s >= settings.morning_capture_extreme_velocity_9s
    )


def is_afternoon_capture_event(
    event: ExplosionEvent,
    *,
    chart: Optional[SpotChart] = None,
) -> bool:
    """True when a BUILDING/EXPLODING leg matches afternoon consolidation breakout."""
    settings = get_settings()
    if not settings.afternoon_premium_capture_enabled:
        return False
    if not in_afternoon_premium_capture_window():
        return False
    if event.tier not in ("BUILDING", "EXPLODING", "ELITE"):
        return False
    if event.explosion_score < settings.afternoon_capture_building_min_score:
        return False

    v3 = event.velocity_3s
    v9 = event.velocity_9s
    vol = event.volume_surge

    if _is_consolidation_breakout(event):
        if chart and not _chart_ok_for_afternoon_event(event, chart):
            return False
        return True

    vel_ok = (
        v3 >= settings.afternoon_capture_min_velocity_3s
        or v9 >= settings.afternoon_capture_min_velocity_9s
    )
    vol_ok = vol >= settings.afternoon_capture_min_vol_surge or v3 >= 1.8
    if not vel_ok or not vol_ok:
        return False

    if event.tier == "BUILDING":
        building_ok = (
            v3 >= settings.afternoon_capture_building_min_velocity_3s
            or (
                v9 >= settings.afternoon_capture_min_velocity_9s
                and vol >= settings.afternoon_capture_min_vol_surge
            )
        )
        if not building_ok:
            return False

    if chart and not _chart_ok_for_afternoon_event(event, chart):
        return False

    return True


    return True


def _chart_ok_for_all_day_event(event: ExplosionEvent, chart: Optional[SpotChart]) -> bool:
    if _chart_confirms_side(event.side, chart):
        return True
    settings = get_settings()
    open_move = float(event.daily_move_pct or 0)
    if open_move >= settings.all_day_explosion_chart_bypass_move_pct:
        return True
    if event.velocity_3s >= settings.morning_capture_extreme_velocity_3s:
        return True
    if event.velocity_9s >= settings.morning_capture_extreme_velocity_9s:
        return True
    if event.volume_surge >= settings.afternoon_capture_chart_bypass_vol_surge:
        return True
    return False


def is_all_day_explosion_event(
    event: ExplosionEvent,
    *,
    chart: Optional[SpotChart] = None,
) -> bool:
    """Session-wide explosive leg — catches 14:00 PE rips after afternoon window used to close."""
    settings = get_settings()
    if not settings.all_day_explosion_capture_enabled:
        return False
    if not in_all_day_explosion_window():
        return False
    if event.tier not in ("BUILDING", "EXPLODING", "ELITE"):
        return False

    open_move = float(event.daily_move_pct or 0)
    score = float(event.explosion_score or 0)
    v3 = float(event.velocity_3s or 0)
    v9 = float(event.velocity_9s or 0)

    extreme_min = float(getattr(settings, "all_day_explosion_extreme_move_min_pct", 80.0) or 80.0)
    if open_move >= extreme_min:
        min_score = float(getattr(settings, "all_day_explosion_min_score", 38.0) or 38.0)
        return score >= min_score - 5

    session_min = float(getattr(settings, "all_day_explosion_session_move_min_pct", 40.0) or 40.0)
    if open_move >= session_min:
        min_score = float(getattr(settings, "all_day_explosion_min_score", 38.0) or 38.0)
        if score >= min_score:
            return _chart_ok_for_all_day_event(event, chart)

    vel_ok = (
        v3 >= float(getattr(settings, "all_day_explosion_building_min_velocity_3s", 1.0) or 1.0)
        or v9 >= float(getattr(settings, "all_day_explosion_min_velocity_9s", 1.8) or 1.8)
    )
    if not vel_ok:
        return False
    min_score = float(getattr(settings, "all_day_explosion_min_score", 38.0) or 38.0)
    if score < min_score:
        return False
    if chart and not _chart_ok_for_all_day_event(event, chart):
        return False
    return True


def is_all_day_explosion_alert(alert: dict[str, Any], chart: Optional[SpotChart] = None) -> bool:
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
            daily_move_pct=float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0),
        )
    except (TypeError, ValueError):
        return False
    return is_all_day_explosion_event(event, chart=chart)


def is_afternoon_capture_alert(alert: dict[str, Any], chart: Optional[SpotChart] = None) -> bool:
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
    return is_afternoon_capture_event(event, chart=chart)


def afternoon_capture_active(snapshots: Optional[dict[str, SymbolSnapshot]]) -> bool:
    if not snapshots or not in_afternoon_premium_capture_window():
        return False
    for snap in snapshots.values():
        if not snap.dataAvailable:
            continue
        chart = snap.spotChart
        for alert in snap.explosionAlerts or []:
            if is_afternoon_capture_alert(alert, chart):
                return True
    return False


def is_premium_capture_event(
    event: ExplosionEvent,
    *,
    chart: Optional[SpotChart] = None,
) -> bool:
    return (
        is_morning_capture_event(event, chart=chart)
        or is_afternoon_capture_event(event, chart=chart)
        or is_all_day_explosion_event(event, chart=chart)
    )


def is_premium_capture_alert(alert: dict[str, Any], chart: Optional[SpotChart] = None) -> bool:
    return (
        is_morning_capture_alert(alert, chart)
        or is_afternoon_capture_alert(alert, chart)
        or is_all_day_explosion_alert(alert, chart)
    )


def premium_capture_active(snapshots: Optional[dict[str, SymbolSnapshot]]) -> bool:
    if not snapshots:
        return False
    if not in_premium_capture_window():
        return False
    for snap in snapshots.values():
        if not snap.dataAvailable:
            continue
        chart = snap.spotChart
        for alert in snap.explosionAlerts or []:
            if is_premium_capture_alert(alert, chart):
                return True
    return False


def premium_capture_rank_floor() -> float:
    settings = get_settings()
    floors: list[float] = []
    if in_morning_premium_capture_window():
        floors.append(settings.morning_capture_min_rank_score)
    if in_afternoon_premium_capture_window():
        floors.append(settings.afternoon_capture_min_rank_score)
    if in_all_day_explosion_window():
        floors.append(settings.all_day_explosion_min_score)
    return min(floors) if floors else settings.morning_capture_min_rank_score


def afternoon_capture_skips_chart_block(
    event: ExplosionEvent,
    chart: Optional[SpotChart],
) -> bool:
    """Premium-led afternoon rally — option moves before index chart flips."""
    return is_afternoon_capture_event(event, chart=chart) and _chart_ok_for_afternoon_event(
        event, chart,
    )


def premium_led_explosion_bypass(
    event: ExplosionEvent,
    chart: Optional[SpotChart],
    breadth_bias: str,
    *,
    snap: Optional[SymbolSnapshot] = None,
) -> bool:
    """
    Option premium leading index — bypass counter-chart blocks on explosions.
    Never bypasses hard breadth alignment (no PUT on BULLISH / CALL on BEARISH).
    """
    settings = get_settings()
    if not settings.premium_led_explosion_bypass_enabled:
        return False
    if not settings.premium_led_counter_breadth_enabled:
        return False
    if not in_premium_capture_window():
        return False

    from app.engines.aligned_side_guard import breadth_hard_blocks_side

    hard_blocked, _ = breadth_hard_blocks_side(event.side, breadth_bias, event=event, snap=snap)
    if hard_blocked:
        return False

    side = _side_str(event.side)
    bias = (breadth_bias or "NEUTRAL").upper()
    direction = (chart.direction or "NEUTRAL").upper() if chart else "NEUTRAL"

    if _market_opposes_side(event.side, breadth_bias, chart, snap=snap, event=event):
        if side == "CALL" and _counter_trend_rip_ok(event, settings):
            return True
        return _elite_counter_breadth_ok(event, settings)

    counter_breadth = _is_counter_breadth(side, bias)
    counter_chart = (direction == "BULLISH" and side == "PUT") or (direction == "BEARISH" and side == "CALL")
    if counter_chart and side == "CALL" and _counter_trend_rip_ok(event, settings):
        return True
    if not counter_breadth and not counter_chart:
        return False

    tier = str(event.tier or "").upper()
    if tier not in ("BUILDING", "EXPLODING", "ELITE"):
        return False

    v3 = float(event.velocity_3s or 0)
    v9 = float(event.velocity_9s or 0)
    score = float(event.explosion_score or 0)
    open_move = float(event.daily_move_pct or 0)
    peak_move = float(getattr(event, "peak_move_pct", 0) or 0)
    session_move = max(open_move, peak_move)
    open_min = float(getattr(settings, "open_premium_min_move_pct", 25.0) or 25.0)
    open_bypass_score = float(getattr(settings, "open_premium_bypass_min_score", 35.0) or 35.0)

    from app.engines.vertical_rip_bypass import qualifies_for_vertical_rip_bypass

    if qualifies_for_vertical_rip_bypass(event):
        return True

    extreme_move = float(getattr(settings, "all_day_explosion_extreme_move_min_pct", 80.0) or 80.0)
    if session_move >= extreme_move and score >= settings.open_premium_bypass_min_score - 3:
        return True

    if session_move >= open_min and score >= open_bypass_score:
        return True

    if v3 >= settings.morning_capture_extreme_velocity_3s or v9 >= settings.morning_capture_extreme_velocity_9s:
        return True

    from app.engines.session_timing import in_open_caution_window

    if in_open_caution_window():
        bypass_v3 = float(getattr(settings, "open_premium_relax_velocity_3s", 1.8) or 1.8)
        bypass_v9 = float(getattr(settings, "open_premium_relax_velocity_9s", 2.5) or 2.5)
        if tier in ("EXPLODING", "ELITE"):
            vel_ok = v3 >= bypass_v3 or v9 >= bypass_v9
            if vel_ok and score >= settings.premium_led_min_explosion_score - 4:
                return True

    if tier in ("EXPLODING", "ELITE"):
        vel_ok = v3 >= settings.premium_led_min_velocity_3s or v9 >= settings.premium_led_min_velocity_9s
        if vel_ok and score >= settings.premium_led_min_explosion_score:
            return True

    if tier == "BUILDING":
        building_vel = (
            v3 >= settings.morning_capture_building_min_velocity_3s
            or (v9 >= settings.morning_capture_min_velocity_9s and event.volume_surge >= settings.morning_capture_min_vol_surge)
        )
        if building_vel and score >= settings.morning_capture_building_min_score:
            return True
        if open_move >= open_min and score >= open_bypass_score:
            return True

    return False


def premium_led_bypass_for_snap(
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    explosion_event: Optional[ExplosionEvent] = None,
) -> bool:
    """Resolve premium-led bypass from explosion event or matching live alert."""
    chart = snap.spotChart
    bias = (snap.breadth.bias if snap.breadth else "NEUTRAL") or "NEUTRAL"
    if explosion_event is not None:
        return premium_led_explosion_bypass(explosion_event, chart, bias, snap=snap)

    side_v = _side_str(side)
    for alert in snap.explosionAlerts or []:
        if str(alert.get("side", "")).upper() != side_v:
            continue
        if alert.get("tier") not in ("BUILDING", "EXPLODING", "ELITE"):
            continue
        event = ExplosionEvent(
            symbol=snap.symbol,
            side=Side(side_v),
            strike=float(alert.get("strike") or 0),
            premium=float(alert.get("premium") or 0),
            velocity_3s=float(alert.get("velocity3s") or 0),
            velocity_9s=float(alert.get("velocity9s") or 0),
            velocity_15s=float(alert.get("velocity15s") or 0),
            volume_surge=float(alert.get("volumeSurge") or 1),
            explosion_score=float(alert.get("explosionScore") or 0),
            tier=str(alert.get("tier") or ""),
            reason=str(alert.get("reason") or ""),
            daily_move_pct=float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0),
        )
        if premium_led_explosion_bypass(event, chart, bias, snap=snap):
            return True
    return False


def afternoon_capture_exit_params(event_tier: str = "BUILDING") -> "ExplosionExitParams":
    """Wider targets/trails for afternoon momentum rides."""
    from app.engines.explosion_profit import ExplosionExitParams

    settings = get_settings()
    target = settings.afternoon_capture_exit_target_points
    if event_tier == "ELITE":
        target = max(target, settings.explosion_target_elite * 0.75)
    return ExplosionExitParams(
        stop_points=settings.afternoon_capture_exit_stop_points,
        target_points=target,
        trail_arm_points=settings.afternoon_capture_exit_trail_arm_points,
        trail_keep_ratio=settings.afternoon_capture_exit_trail_keep_ratio,
        micro_target_points=4.0,
        adaptive_stop=True,
    )
