"""Directional side lock — aligned side default; CE↔PE switch only on full confirmation."""

from __future__ import annotations

from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.spot_direction import side_aligned_with_chart
from app.models.schemas import Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")

# symbol -> last traded side this session
_session_locked_side: dict[str, str] = {}
_session_date: Optional[str] = None


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def _expected_side_for_bias(bias: str) -> Optional[str]:
    bias = (bias or "NEUTRAL").upper()
    if bias == "BULLISH":
        return "CALL"
    if bias == "BEARISH":
        return "PUT"
    return None


def _roll_session() -> None:
    global _session_date, _session_locked_side
    from datetime import datetime

    today = datetime.now(IST).strftime("%Y-%m-%d")
    if _session_date != today:
        _session_date = today
        _session_locked_side.clear()


def reset_directional_lock() -> None:
    global _session_date, _session_locked_side
    _session_locked_side.clear()
    _session_date = None


def market_direction(snap: SymbolSnapshot) -> str:
    """BULLISH | BEARISH | NEUTRAL from breadth + optional index chart."""
    settings = get_settings()
    bias = (snap.breadth.bias or "NEUTRAL").upper()
    chart_dir = ""
    if settings.directional_lock_use_chart and snap.spotChart:
        chart_dir = (snap.spotChart.direction or "NEUTRAL").upper()

    if bias in ("BULLISH", "BEARISH"):
        return bias
    if chart_dir in ("BULLISH", "BEARISH"):
        return chart_dir
    return "NEUTRAL"


def session_locked_side(symbol: str) -> Optional[str]:
    _roll_session()
    return _session_locked_side.get(symbol.upper())


def _side_premium_velocity(snap: SymbolSnapshot, side_v: str) -> float:
    best = 0.0
    for entry in snap.explosiveRunnerWatchlist or []:
        if str(entry.get("side", "")).upper() != side_v:
            continue
        best = max(best, float(entry.get("premiumVelocityPct") or 0))
    top = snap.topExplosion or {}
    if str(top.get("side", "")).upper() == side_v:
        best = max(best, float(top.get("velocity3s") or 0))
    runner = snap.explosiveRunner
    if runner and runner.side and _side_val(runner.side) == side_v and runner.signal:
        best = max(best, float(runner.signal.premiumVelocityPct or 0))
    return best


def side_switch_confirmed(
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    tier: str = "",
) -> tuple[bool, str, dict[str, Any]]:
    """
    CE↔PE switch allowed only when multiple independent indicators align for target side.
    Returns (confirmed, reason, meta with signal checklist).
    """
    settings = get_settings()
    side_v = _side_val(side)
    target_bias = "BULLISH" if side_v == "CALL" else "BEARISH"
    opposite_bias = "BEARISH" if side_v == "CALL" else "BULLISH"
    breadth = (snap.breadth.bias or "NEUTRAL").upper()
    chart = snap.spotChart
    chart_dir = (chart.direction or "NEUTRAL").upper() if chart else "NEUTRAL"

    signals: list[str] = []
    missing: list[str] = []

    # Breadth must support target side — block switch into opposite breadth
    if breadth == target_bias:
        signals.append("breadth")
    elif breadth == opposite_bias:
        return False, "breadth_opposite", {
            "signals": signals,
            "missing": ["breadth_flip"],
            "breadth": breadth,
            "targetBias": target_bias,
        }
    else:
        missing.append("breadth_neutral")

    if chart and side_aligned_with_chart(side_v, chart):
        if chart_dir == target_bias:
            signals.append("chart_direction")
        elif chart_dir == "NEUTRAL" and chart.trendStrength >= settings.directional_switch_min_trend_strength:
            if side_v == "CALL" and chart.momentum5Pct > 0:
                signals.append("chart_momentum")
            elif side_v == "PUT" and chart.momentum5Pct < 0:
                signals.append("chart_momentum")
        else:
            missing.append("chart")
    else:
        missing.append("chart")

    if chart:
        if chart.emaBias == target_bias:
            signals.append("ema")
        if chart.candleBias == target_bias:
            signals.append("candles")
        if side_v == "CALL" and chart.abovePoc and chart.momentum5Pct > 0:
            signals.append("poc_structure")
        if side_v == "PUT" and chart.belowPoc and chart.momentum5Pct < 0:
            signals.append("poc_structure")

    vel = _side_premium_velocity(snap, side_v)
    if vel >= settings.directional_switch_min_velocity_pct:
        signals.append(f"velocity_{vel:.1f}")

    top = snap.topExplosion or {}
    if str(top.get("side", "")).upper() == side_v:
        score = float(top.get("explosionScore") or 0)
        if score >= settings.directional_switch_min_explosion_score:
            signals.append("explosion")
        elif tier in ("ELITE", "EXPLODING") and score >= settings.directional_switch_min_explosion_score - 8:
            signals.append("explosion_tier")

    runner = snap.explosiveRunner
    if runner and runner.side and _side_val(runner.side) == side_v:
        if float(runner.score or 0) >= settings.directional_switch_min_runner_score:
            signals.append("runner")

    of = snap.orderflow
    if side_v == "CALL" and of.tickMomentum > 0 and of.deltaVelocity >= 0:
        signals.append("orderflow")
    elif side_v == "PUT" and of.tickMomentum < 0 and of.deltaVelocity <= 0:
        signals.append("orderflow")

    if snap.breadth.aligned and breadth == target_bias:
        signals.append("breadth_aligned")

    required = settings.directional_switch_min_confirmations
    confirmed = len(signals) >= required
    meta = {
        "signals": signals,
        "missing": missing,
        "signalCount": len(signals),
        "required": required,
        "breadth": breadth,
        "chart": chart_dir,
        "velocity": round(vel, 2),
        "targetSide": side_v,
    }
    if confirmed:
        return True, "confirmed", meta
    return False, f"need_{required}_signals_have_{len(signals)}", meta


def _needs_confirmation(
    symbol: str,
    side_v: str,
    snap: SymbolSnapshot,
) -> bool:
    """True when entry is counter-trend or a CE↔PE flip vs last traded side."""
    locked = session_locked_side(symbol)
    if locked and locked != side_v:
        return True

    direction = market_direction(snap)
    expected = _expected_side_for_bias(direction)
    if expected and side_v != expected:
        return True

    if get_settings().directional_lock_block_chart_counter:
        chart = snap.spotChart
        if chart:
            chart_expected = _expected_side_for_bias((chart.direction or "NEUTRAL").upper())
            if chart_expected and side_v != chart_expected:
                return True

    return False


def record_trade_side(symbol: str, side: Side | str, snap: SymbolSnapshot) -> None:
    """Record last traded side for the symbol (updated on each fill)."""
    settings = get_settings()
    if not settings.directional_side_lock_enabled:
        return
    _roll_session()
    sym = symbol.upper()
    _session_locked_side[sym] = _side_val(side)


def check_directional_side_lock(
    symbol: str,
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    tier: str = "",
    premium_led_bypass: bool = False,
) -> tuple[bool, str]:
    """
    Returns (blocked, reason).
    Aligned side entries pass. CE↔PE switch / counter-trend needs full confirmation.
    """
    settings = get_settings()
    if not settings.directional_side_lock_enabled:
        return False, "ok"

    side_v = _side_val(side)

    if premium_led_bypass:
        return False, "ok"

    if not _needs_confirmation(symbol, side_v, snap):
        return False, "ok"

    confirmed, reason, meta = side_switch_confirmed(side_v, snap, tier=tier)
    if confirmed:
        return False, "ok"

    locked = session_locked_side(symbol)
    if locked and locked != side_v:
        return True, f"directional_switch_blocked_{locked}_to_{side_v}_{reason}"

    direction = market_direction(snap)
    if direction == "BULLISH" and side_v == "PUT":
        return True, f"directional_put_needs_confirmation_{reason}"
    if direction == "BEARISH" and side_v == "CALL":
        return True, f"directional_call_needs_confirmation_{reason}"

    return True, f"directional_switch_unconfirmed_{reason}"


def check_directional_side_lock_simple(
    symbol: str,
    side: Side | str,
    breadth_bias: str,
    chart: Optional[SpotChart] = None,
    *,
    premium_led_bypass: bool = False,
) -> tuple[bool, str]:
    """Lightweight gate — counter-trend blocked unless breadth already flipped."""
    settings = get_settings()
    if not settings.directional_side_lock_enabled:
        return False, "ok"

    if premium_led_bypass:
        return False, "ok"

    side_v = _side_val(side)
    bias = (breadth_bias or "NEUTRAL").upper()
    locked = session_locked_side(symbol)

    if locked and locked != side_v:
        expected = _expected_side_for_bias(bias)
        if expected != side_v:
            return True, f"directional_switch_blocked_{locked}_to_{side_v}_breadth_not_flipped"

    if bias == "BULLISH" and side_v == "PUT":
        return True, "directional_put_needs_confirmation_breadth_bullish"
    if bias == "BEARISH" and side_v == "CALL":
        return True, "directional_call_needs_confirmation_breadth_bearish"

    if settings.directional_lock_block_chart_counter and chart:
        chart_dir = (chart.direction or "NEUTRAL").upper()
        if chart_dir == "BULLISH" and side_v == "PUT":
            return True, "directional_put_needs_confirmation_chart_bullish"
        if chart_dir == "BEARISH" and side_v == "CALL":
            return True, "directional_call_needs_confirmation_chart_bearish"

    if locked and locked != side_v:
        return True, f"directional_switch_blocked_{locked}_to_{side_v}_needs_full_confirm"

    return False, "ok"


def directional_lock_summary(snapshots: dict[str, SymbolSnapshot]) -> dict[str, Any]:
    settings = get_settings()
    _roll_session()
    per_symbol = {}
    for sym, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        call_ok, _, call_meta = side_switch_confirmed(Side.CALL, snap)
        put_ok, _, put_meta = side_switch_confirmed(Side.PUT, snap)
        per_symbol[sym] = {
            "direction": market_direction(snap),
            "lockedSide": session_locked_side(sym),
            "breadth": (snap.breadth.bias or "NEUTRAL").upper(),
            "chart": (snap.spotChart.direction or "NEUTRAL").upper() if snap.spotChart else "NEUTRAL",
            "callSwitchConfirmed": call_ok,
            "putSwitchConfirmed": put_ok,
            "callSignals": call_meta.get("signals", []),
            "putSignals": put_meta.get("signals", []),
        }
    return {
        "enabled": settings.directional_side_lock_enabled,
        "stickyPerSymbol": settings.directional_sticky_per_symbol,
        "switchMinConfirmations": settings.directional_switch_min_confirmations,
        "symbols": per_symbol,
    }
