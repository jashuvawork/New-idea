"""Block buying an option leg that is in a post-spike premium dump (falling knife).

Sep 24 SENSEX 73700 PE: radar ELITE score stayed high while 1m premium ripped to ~₹240
then dumped on large red candles; entry ~₹150 was mid-collapse. Score measures detection,
not live tick timing — this guard uses session peak + live momentum/candles every execution.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import get_settings
from app.models.schemas import PremiumChart, Side, SymbolSnapshot


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side or "").upper()


def premium_chart_spike_dump_read(
    candles: list,
    ltp: float,
    *,
    settings: Any = None,
) -> dict[str, Any]:
    """1m premium candles at execution — spike + dump pattern."""
    settings = settings or get_settings()
    lookback = int(getattr(settings, "premium_post_spike_dump_chart_bars", 24) or 24)
    opens, highs, lows, closes = [], [], [], []
    for c in candles or []:
        if isinstance(c, list) and len(c) >= 5:
            opens.append(float(c[1]))
            highs.append(float(c[2]))
            lows.append(float(c[3]))
            closes.append(float(c[4]))
        elif isinstance(c, dict):
            opens.append(float(c.get("open", 0) or 0))
            highs.append(float(c.get("high", 0) or 0))
            lows.append(float(c.get("low", 0) or 0))
            closes.append(float(c.get("close", 0) or 0))
    if not closes or ltp <= 0:
        return {"active": False}

    window_high = max(highs[-lookback:]) if highs else ltp
    window_low = min(lows[-lookback:]) if lows else ltp
    drawdown_pct = ((ltp - window_high) / window_high * 100.0) if window_high > 0 else 0.0
    run_pct = ((window_high - window_low) / window_low * 100.0) if window_low > 0 else 0.0

    bodies = [abs(c - o) for o, c in zip(opens[-6:], closes[-6:])]
    signs = [1 if c > o else (-1 if c < o else 0) for o, c in zip(opens[-6:], closes[-6:])]
    avg_body = sum(bodies) / max(1, len(bodies))
    big_red = sum(
        1
        for body, sign in zip(bodies[-4:], signs[-4:])
        if sign < 0 and body >= avg_body * float(
            getattr(settings, "premium_post_spike_dump_big_body_mult", 1.25) or 1.25
        )
    )
    min_red = int(getattr(settings, "premium_post_spike_dump_min_big_red_bars", 2) or 2)
    min_dd = float(getattr(settings, "premium_post_spike_dump_min_drawdown_pct", 12.0) or 12.0)
    min_run = float(getattr(settings, "premium_post_spike_dump_min_spike_run_pct", 35.0) or 35.0)

    near_low_frac = float(
        getattr(settings, "premium_post_spike_dump_near_low_frac", 0.18) or 0.18
    )
    span = window_high - window_low
    near_low = span > 0 and (ltp - window_low) / span <= near_low_frac

    active = (
        run_pct >= min_run
        and drawdown_pct <= -min_dd
        and big_red >= min_red
        and not near_low
    )
    return {
        "active": active,
        "windowHigh": round(window_high, 2),
        "windowLow": round(window_low, 2),
        "drawdownFromHighPct": round(drawdown_pct, 2),
        "spikeRunPct": round(run_pct, 2),
        "bigRedBars": big_red,
        "nearWindowLow": near_low,
    }


def alert_premium_spike_dump_meta(alert: Mapping[str, Any], *, settings: Any = None) -> dict[str, Any]:
    """Tick-level read from alert fields (preorder / selector)."""
    settings = settings or get_settings()
    prem = float(alert.get("premium") or alert.get("lastPremium") or 0)
    peak = float(
        alert.get("sessionPeakPremium")
        or alert.get("peakPremium")
        or alert.get("sessionPeak")
        or 0
    )
    low = float(alert.get("sessionLowPremium") or alert.get("sessionLow") or 0)
    v3 = float(alert.get("velocity3s") or alert.get("velocity_3s") or 0)
    v9 = float(alert.get("velocity9s") or alert.get("velocity_9s") or 0)
    if peak <= 0 or prem <= 0:
        return {"active": False}
    dd = (prem - peak) / peak * 100.0
    run = ((peak - low) / low * 100.0) if low > 0 else float(alert.get("peakMovePct") or 0)
    min_dd = float(getattr(settings, "premium_post_spike_dump_min_drawdown_pct", 12.0) or 12.0)
    min_run = float(getattr(settings, "premium_post_spike_dump_min_spike_run_pct", 35.0) or 35.0)
    near_low_frac = float(
        getattr(settings, "premium_post_spike_dump_near_low_frac", 0.18) or 0.18
    )
    span = peak - low if low > 0 else 0.0
    near_low = span > 0 and (prem - low) / span <= near_low_frac
    falling = v3 < float(
        getattr(settings, "premium_post_spike_dump_min_velocity_3s", -0.15) or -0.15
    ) or v9 < float(
        getattr(settings, "premium_post_spike_dump_min_velocity_9s", -0.25) or -0.25
    )
    active = (
        run >= min_run
        and dd <= -min_dd
        and falling
        and not near_low
    )
    return {
        "active": active,
        "sessionPeakPremium": round(peak, 2),
        "sessionLowPremium": round(low, 2) if low else None,
        "drawdownFromPeakPct": round(dd, 2),
        "spikeRunPct": round(run, 2),
        "velocity3s": round(v3, 3),
        "nearSessionLow": near_low,
    }


def post_spike_premium_dump_blocked(
    explosion_event: Any,
    *,
    alert: Optional[Mapping[str, Any]] = None,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Symmetric for CE and PE — we always buy premium; block when that premium is
    collapsing after a large session spike (not a fresh base at session low).
    """
    settings = settings or get_settings()
    if not bool(getattr(settings, "premium_post_spike_dump_guard_enabled", True)):
        return False, "ok", {}
    meta: dict[str, Any] = {}
    if alert:
        meta = alert_premium_spike_dump_meta(alert, settings=settings)
        if meta.get("active"):
            return True, "premium_post_spike_dump", meta
    if explosion_event is None:
        return False, "ok", meta
    sym = str(getattr(explosion_event, "symbol", "") or "")
    side = getattr(explosion_event, "side", None)
    strike = float(getattr(explosion_event, "strike", 0) or 0)
    if not sym or side is None or strike <= 0:
        return False, "ok", meta
    try:
        from app.engines.explosion_detector import (
            get_session_low_premium,
            get_session_peak_premium,
        )
    except Exception:
        return False, "ok", meta

    peak = float(get_session_peak_premium(sym, strike, side) or 0)
    low = float(get_session_low_premium(sym, strike, side) or 0)
    current = float(getattr(explosion_event, "premium", 0) or 0)
    if alert and current <= 0:
        current = float(alert.get("premium") or 0)
    if peak <= 0 or current <= 0:
        return False, "ok", meta

    dd = (current - peak) / peak * 100.0
    run = ((peak - low) / low * 100.0) if low > 0 else 0.0
    v3 = float(getattr(explosion_event, "velocity_3s", 0) or 0)
    v9 = float(getattr(explosion_event, "velocity_9s", 0) or 0)

    min_dd = float(getattr(settings, "premium_post_spike_dump_min_drawdown_pct", 12.0) or 12.0)
    min_run = float(getattr(settings, "premium_post_spike_dump_min_spike_run_pct", 35.0) or 35.0)
    near_low_frac = float(
        getattr(settings, "premium_post_spike_dump_near_low_frac", 0.18) or 0.18
    )
    span = peak - low if low > 0 else 0.0
    near_low = span > 0 and (current - low) / span <= near_low_frac
    falling = v3 < float(
        getattr(settings, "premium_post_spike_dump_min_velocity_3s", -0.15) or -0.15
    ) or v9 < float(
        getattr(settings, "premium_post_spike_dump_min_velocity_9s", -0.25) or -0.25
    )

    meta = {
        "sessionPeakPremium": round(peak, 2),
        "sessionLowPremium": round(low, 2) if low else None,
        "currentPremium": round(current, 2),
        "drawdownFromPeakPct": round(dd, 2),
        "spikeRunPct": round(run, 2),
        "velocity3s": round(v3, 3),
        "nearSessionLow": near_low,
    }
    if run >= min_run and dd <= -min_dd and falling and not near_low:
        return True, "premium_post_spike_dump", meta
    return False, "ok", meta


def premium_chart_post_spike_dump(premium: Optional[PremiumChart]) -> bool:
    if premium is None:
        return False
    return bool(getattr(premium, "postSpikeDump", False))


def live_execution_trade_score(
    base_score: float,
    premium: Optional[PremiumChart] = None,
    *,
    alert: Optional[Mapping[str, Any]] = None,
    settings: Any = None,
) -> tuple[float, dict[str, Any]]:
    """
    Effective score at execution tick — decays when premium is dumping so high
    radar score cannot mask a falling fill.
    """
    settings = settings or get_settings()
    meta: dict[str, Any] = {"baseScore": round(float(base_score or 0), 2)}
    score = float(base_score or 0)
    if not bool(getattr(settings, "live_execution_trade_score_enabled", True)):
        meta["liveScore"] = round(score, 2)
        return score, meta

    penalty = 0.0
    if premium is not None:
        if premium_chart_post_spike_dump(premium):
            penalty += float(
                getattr(settings, "live_execution_trade_score_dump_penalty", 45.0) or 45.0
            )
        if str(premium.direction or "").upper() == "BEARISH":
            mom = float(premium.momentum5Pct or 0)
            if mom < -0.2:
                penalty += min(
                    35.0,
                    abs(mom)
                    * float(
                        getattr(settings, "live_execution_trade_score_mom_factor", 8.0) or 8.0
                    ),
                )
        meta["premiumDirection"] = premium.direction
        meta["premiumMomentum5Pct"] = premium.momentum5Pct
        meta["drawdownFromHighPct"] = getattr(premium, "drawdownFromHighPct", None)
    elif alert:
        dump_meta = alert_premium_spike_dump_meta(alert, settings=settings)
        meta["alertDump"] = dump_meta
        if dump_meta.get("active"):
            penalty += float(
                getattr(settings, "live_execution_trade_score_dump_penalty", 45.0) or 45.0
            )

    live = max(0.0, score - penalty)
    meta["liveScore"] = round(live, 2)
    meta["liveScorePenalty"] = round(penalty, 2)
    return live, meta


def opposite_side_dump_capture_rank_bonus(
    candidate: Any,
    snap: SymbolSnapshot,
    *,
    settings: Any = None,
) -> float:
    """
    When one side's premium is in post-spike dump, favor the opposite side on the
    same index (PE dump → CE bounce capture, symmetric CE dump → PE).
    """
    settings = settings or get_settings()
    if not bool(getattr(settings, "premium_dump_opposite_side_rank_enabled", True)):
        return 0.0
    side = _side_val(getattr(candidate, "side", "") or "")
    if side not in ("CALL", "PUT"):
        return 0.0
    alert = getattr(candidate, "alert", None)
    if not isinstance(alert, dict):
        return 0.0
    sym = str(getattr(candidate, "symbol", "") or alert.get("symbol") or "").upper()
    if not sym:
        return 0.0
    opp = "PUT" if side == "CALL" else "CALL"
    opp_alerts = [
        a
        for a in (snap.explosionAlerts or [])
        if str(a.get("symbol") or "").upper() == sym
        and str(a.get("side") or "").upper() == opp
    ]
    if not opp_alerts:
        return 0.0
    for oa in opp_alerts:
        if alert_premium_spike_dump_meta(oa, settings=settings).get("active"):
            bonus = float(
                getattr(settings, "premium_dump_opposite_side_rank_bonus", 12.0) or 12.0
            )
            breadth = str(snap.breadth.bias if snap.breadth else "NEUTRAL").upper()
            if (side == "CALL" and breadth == "BULLISH") or (
                side == "PUT" and breadth == "BEARISH"
            ):
                bonus += float(
                    getattr(
                        settings, "premium_dump_opposite_side_breadth_bonus", 6.0
                    )
                    or 6.0
                )
            return bonus
    return 0.0
