"""Vertical rip bypass — premium-led explosions that outrun index chart/breadth/MTF."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.engines.explosion_detector import ExplosionEvent, retained_peak_velocity_3s
from app.models.schemas import Side, SymbolSnapshot

_TIER_RANK = {"WATCH": 1, "BUILDING": 2, "EXPLODING": 3, "ELITE": 4}


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def _metrics_from_event(event: Any) -> dict[str, float | str]:
    """Resolve explosion metrics from ExplosionEvent, EntryCandidate, or alert dict."""
    tier = ""
    score = 0.0
    daily = 0.0
    peak = 0.0
    v3 = 0.0
    v9 = 0.0
    vol = 1.0
    symbol = ""
    strike = 0.0
    side = Side.CALL

    ev = getattr(event, "explosion_event", None) if event is not None else None
    if isinstance(ev, ExplosionEvent):
        event = ev
    elif isinstance(event, dict):
        alert = event
        tier = str(alert.get("tier", "") or "").upper()
        score = float(alert.get("explosionScore") or alert.get("score") or 0)
        daily = float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0)
        peak = float(alert.get("peakMovePct") or 0)
        v3 = float(alert.get("velocity3s") or 0)
        v9 = float(alert.get("velocity9s") or 0)
        vol = float(alert.get("volumeSurge") or 1)
        symbol = str(alert.get("symbol", "") or "")
        strike = float(alert.get("strike") or 0)
        try:
            side = Side(str(alert.get("side", "CALL")).upper())
        except (TypeError, ValueError):
            side = Side.CALL
        peak_v3 = retained_peak_velocity_3s(symbol, strike, side) if symbol and strike else 0.0
        session_move = max(daily, peak)
        return {
            "tier": tier,
            "score": score,
            "daily_move": daily,
            "peak_move": peak,
            "session_move": session_move,
            "velocity_3s": v3,
            "velocity_9s": v9,
            "volume_surge": vol,
            "peak_velocity_3s": peak_v3,
        }

    if event is not None:
        tier = str(getattr(event, "tier", "") or "").upper()
        score = float(getattr(event, "explosion_score", 0) or getattr(event, "score", 0) or 0)
        daily = float(getattr(event, "daily_move_pct", 0) or 0)
        peak = float(getattr(event, "peak_move_pct", 0) or 0)
        if peak <= 0:
            alert = getattr(event, "alert", None) or {}
            if isinstance(alert, dict):
                peak = float(alert.get("peakMovePct") or 0)
                if peak > daily:
                    daily = max(daily, float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0))
        v3 = float(getattr(event, "velocity_3s", 0) or 0)
        v9 = float(getattr(event, "velocity_9s", 0) or 0)
        vol = float(getattr(event, "volume_surge", 0) or 1.0)
        symbol = str(getattr(event, "symbol", "") or "")
        strike = float(getattr(event, "strike", 0) or 0)
        side = getattr(event, "side", Side.CALL)

    peak_v3 = retained_peak_velocity_3s(symbol, strike, side) if symbol and strike else 0.0
    session_move = max(daily, peak)
    return {
        "tier": tier,
        "score": score,
        "daily_move": daily,
        "peak_move": peak,
        "session_move": session_move,
        "velocity_3s": v3,
        "velocity_9s": v9,
        "volume_surge": vol,
        "peak_velocity_3s": peak_v3,
    }


def qualifies_for_vertical_rip_bypass(
    event: Any,
    *,
    snap: Optional[SymbolSnapshot] = None,
) -> bool:
    """
    Material session peak rip — bypass chart/breadth/MTF/worst-day alignment gates.
    Targets NIFTY 24150 CE / 24000 PE style vertical candles the bot keeps missing.
    """
    settings = get_settings()
    if not getattr(settings, "vertical_rip_bypass_enabled", True):
        return False
    if event is None:
        return False

    m = _metrics_from_event(event)
    tier = str(m["tier"])
    min_tier = str(getattr(settings, "vertical_rip_bypass_min_tier", "EXPLODING") or "EXPLODING").upper()
    if _TIER_RANK.get(tier, 0) < _TIER_RANK.get(min_tier, 3):
        return False

    min_peak = float(getattr(settings, "vertical_rip_bypass_min_peak_pct", 30.0) or 30.0)
    min_score = float(getattr(settings, "vertical_rip_bypass_min_score", 38.0) or 38.0)
    min_peak_v3 = float(getattr(settings, "vertical_rip_bypass_min_peak_velocity_3s", 2.0) or 2.0)
    min_vol = float(getattr(settings, "vertical_rip_bypass_min_volume_surge", 3.0) or 3.0)

    peak_move = float(m["peak_move"])
    session_move = float(m["session_move"])
    score = float(m["score"])
    peak_v3 = float(m["peak_velocity_3s"])
    vol = float(m["volume_surge"])

    move_ok = peak_move >= min_peak or session_move >= min_peak
    if not move_ok:
        return False

    quality_ok = (
        score >= min_score
        or peak_v3 >= min_peak_v3
        or (vol >= min_vol and session_move >= min_peak * 0.85)
    )
    if not quality_ok:
        return False

    from app.engines.extreme_explosion_moment import is_extreme_explosion_all_in_bypass

    if is_extreme_explosion_all_in_bypass(event=event if isinstance(event, ExplosionEvent) else None):
        return True

    return True


def vertical_rip_bypass_meta(event: Any) -> dict[str, Any]:
    m = _metrics_from_event(event)
    return {
        "verticalRipBypass": True,
        "verticalRipPeakMovePct": round(float(m["peak_move"]), 1),
        "verticalRipSessionMovePct": round(float(m["session_move"]), 1),
        "verticalRipPeakVelocity3s": round(float(m["peak_velocity_3s"]), 2),
    }


def vertical_rip_bypass_for_snap(
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    explosion_event: Optional[ExplosionEvent] = None,
) -> bool:
    if explosion_event is not None:
        return qualifies_for_vertical_rip_bypass(explosion_event, snap=snap)

    side_v = _side_val(side)
    for alert in snap.explosionAlerts or []:
        if str(alert.get("side", "")).upper() != side_v:
            continue
        if alert.get("tier") not in ("BUILDING", "EXPLODING", "ELITE"):
            continue
        try:
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
                peak_move_pct=float(alert.get("peakMovePct") or 0),
            )
        except (TypeError, ValueError):
            continue
        if qualifies_for_vertical_rip_bypass(event, snap=snap):
            return True
    return False


def vertical_rip_bypasses_hard_breadth(
    side: Side | str,
    breadth_bias: str,
    *,
    event: Any = None,
    snap: Optional[SymbolSnapshot] = None,
) -> bool:
    """Premium-led vertical rip — allow counter-breadth when option leg is the signal."""
    if not qualifies_for_vertical_rip_bypass(event, snap=snap):
        return False

    settings = get_settings()
    if not getattr(settings, "vertical_rip_hard_breadth_bypass_enabled", True):
        return False

    bias = (breadth_bias or "NEUTRAL").upper()
    side_v = _side_val(side)
    if bias == "NEUTRAL":
        return False

    if bias == "BEARISH" and side_v == "CALL":
        return True

    if bias == "BULLISH" and side_v == "PUT":
        from app.engines.aligned_side_guard import _live_chart_supports_put

        if _live_chart_supports_put(snap):
            return True
        chart = snap.spotChart if snap else None
        if chart and str(chart.direction or "").upper() == "BEARISH":
            return True
        m = _metrics_from_event(event)
        if float(m["peak_move"]) >= float(getattr(settings, "vertical_rip_bypass_min_peak_pct", 30.0) or 30.0):
            return True

    return False
