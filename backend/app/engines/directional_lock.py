"""Directional side lock — BULLISH = CE only, BEARISH = PE only, no CE↔PE flips."""

from __future__ import annotations

from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")

# symbol -> locked side for session (no CE↔PE switch once set)
_session_locked_side: dict[str, str] = {}
_session_date: Optional[str] = None


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


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


def record_trade_side(symbol: str, side: Side | str, snap: SymbolSnapshot) -> None:
    """After a fill, lock symbol to this side — no CE↔PE switching rest of session."""
    settings = get_settings()
    if not settings.directional_side_lock_enabled:
        return
    _roll_session()
    sym = symbol.upper()
    side_v = _side_val(side)
    direction = market_direction(snap)

    if direction == "BULLISH":
        _session_locked_side[sym] = "CALL"
    elif direction == "BEARISH":
        _session_locked_side[sym] = "PUT"
    elif settings.directional_sticky_per_symbol:
        _session_locked_side.setdefault(sym, side_v)


def check_directional_side_lock(
    symbol: str,
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    tier: str = "",
) -> tuple[bool, str]:
    """
    Returns (blocked, reason).
    BULLISH → CALL only. BEARISH → PUT only. No flip vs session lock.
    """
    settings = get_settings()
    if not settings.directional_side_lock_enabled:
        return False, "ok"

    side_v = _side_val(side)
    direction = market_direction(snap)

    if direction == "BULLISH" and side_v == "PUT":
        return True, "directional_lock_bullish_ce_only"

    if direction == "BEARISH" and side_v == "CALL":
        return True, "directional_lock_bearish_pe_only"

    if settings.directional_lock_block_chart_counter:
        chart = snap.spotChart
        if chart:
            chart_dir = (chart.direction or "NEUTRAL").upper()
            if chart_dir == "BULLISH" and side_v == "PUT":
                return True, "directional_lock_chart_bullish_ce_only"
            if chart_dir == "BEARISH" and side_v == "CALL":
                return True, "directional_lock_chart_bearish_pe_only"

    locked = session_locked_side(symbol)
    if locked and side_v != locked:
        return True, f"directional_lock_no_ce_pe_switch_{locked}_locked"

    return False, "ok"


def check_directional_side_lock_simple(
    symbol: str,
    side: Side | str,
    breadth_bias: str,
    chart: Optional[SpotChart] = None,
) -> tuple[bool, str]:
    """Breadth/chart/sticky lock without full snapshot."""
    settings = get_settings()
    if not settings.directional_side_lock_enabled:
        return False, "ok"

    side_v = _side_val(side)
    bias = (breadth_bias or "NEUTRAL").upper()

    if bias == "BULLISH" and side_v == "PUT":
        return True, "directional_lock_bullish_ce_only"
    if bias == "BEARISH" and side_v == "CALL":
        return True, "directional_lock_bearish_pe_only"

    if settings.directional_lock_block_chart_counter and chart:
        chart_dir = (chart.direction or "NEUTRAL").upper()
        if chart_dir == "BULLISH" and side_v == "PUT":
            return True, "directional_lock_chart_bullish_ce_only"
        if chart_dir == "BEARISH" and side_v == "CALL":
            return True, "directional_lock_chart_bearish_pe_only"

    locked = session_locked_side(symbol)
    if locked and side_v != locked:
        return True, f"directional_lock_no_ce_pe_switch_{locked}_locked"

    return False, "ok"


def directional_lock_summary(snapshots: dict[str, SymbolSnapshot]) -> dict[str, Any]:
    settings = get_settings()
    _roll_session()
    per_symbol = {}
    for sym, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        per_symbol[sym] = {
            "direction": market_direction(snap),
            "lockedSide": session_locked_side(sym),
            "breadth": (snap.breadth.bias or "NEUTRAL").upper(),
            "chart": (snap.spotChart.direction or "NEUTRAL").upper() if snap.spotChart else "NEUTRAL",
        }
    return {
        "enabled": settings.directional_side_lock_enabled,
        "stickyPerSymbol": settings.directional_sticky_per_symbol,
        "symbols": per_symbol,
    }
