"""Index trend side-flip bypass — unlock opposite side after a sticky session flip.

CALL: spot rips off session low with bullish RSI/MACD (e.g. SENSEX +130pts).
PUT:  spot slides off session high with bearish RSI/MACD (mirror of the above).
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side or "").upper()


def _symbol_allowed(symbol: str, settings: Any) -> bool:
    raw = str(getattr(settings, "index_rally_side_flip_symbols_csv", "SENSEX,NIFTY") or "")
    allowed = {s.strip().upper() for s in raw.split(",") if s.strip()}
    return not allowed or symbol.upper() in allowed


def _min_move_pts(symbol: str, settings: Any) -> float:
    sym = symbol.upper()
    if sym == "NIFTY":
        return float(getattr(settings, "index_rally_side_flip_min_pts_nifty", 45.0) or 45.0)
    if sym == "BANKNIFTY":
        return float(
            getattr(settings, "index_rally_side_flip_min_pts_banknifty", 80.0) or 80.0
        )
    return float(getattr(settings, "index_rally_side_flip_min_pts", 130.0) or 130.0)


def _session_extremes_and_spot(
    symbol: str,
    snap: SymbolSnapshot,
) -> tuple[float, float, float]:
    """Session high, low, and live spot from tick tape or broker candles."""
    from app.engines.index_tick_helpers import (
        _snap_session_extremes,
        index_session_extremes,
    )

    sym = symbol.upper()
    ext = index_session_extremes(sym)
    hi = float(ext.get("hi") or 0)
    lo = float(ext.get("lo") or 0)
    spot = float(getattr(snap, "spot", 0) or 0) or float(ext.get("last") or 0)

    snap_hi, snap_lo = _snap_session_extremes(snap)
    if snap_hi > 0:
        hi = max(hi, snap_hi)
    if snap_lo > 0:
        lo = min(lo, snap_lo) if lo > 0 else snap_lo

    return hi, lo, spot


def index_rally_metrics(
    symbol: str,
    snap: SymbolSnapshot,
    *,
    settings: Any = None,
) -> dict[str, Any]:
    """Spot rally off session low + slide off session high with chart RSI/MACD."""
    settings = settings or get_settings()
    hi, lo, spot = _session_extremes_and_spot(symbol, snap)
    chart = snap.spotChart
    rsi = float(getattr(chart, "rsi", 0) or 0) if chart else 0.0
    macd_bias = str(getattr(chart, "macdBias", "") or "NEUTRAL").upper() if chart else "NEUTRAL"
    macd_hist = float(getattr(chart, "macdHistogram", 0) or 0) if chart else 0.0
    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0) if chart else 0.0
    rally_pts = round(spot - lo, 1) if spot > 0 and lo > 0 else 0.0
    slide_pts = round(hi - spot, 1) if spot > 0 and hi > 0 else 0.0
    min_pts = _min_move_pts(symbol, settings)
    return {
        "symbol": symbol.upper(),
        "sessionLow": round(lo, 2),
        "sessionHigh": round(hi, 2),
        "spot": round(spot, 2),
        "rallyPoints": rally_pts,
        "slidePoints": slide_pts,
        "minMovePoints": min_pts,
        "minRallyPoints": min_pts,
        "rsi": round(rsi, 1),
        "macdBias": macd_bias,
        "macdHistogram": round(macd_hist, 4),
        "momentum5Pct": round(mom5, 3),
    }


def _call_rally_bypass(
    sym: str,
    snap: SymbolSnapshot,
    settings: Any,
    *,
    locked: str | None,
    direction: str,
    breadth: str,
) -> tuple[bool, str, dict[str, Any]]:
    if bool(getattr(settings, "index_rally_side_flip_require_put_session", True)):
        put_session = locked == "PUT" or direction == "BEARISH" or breadth == "BEARISH"
        if not put_session:
            return False, "no_put_session", {"lockedSide": locked, "direction": direction}

    metrics = index_rally_metrics(sym, snap, settings=settings)
    rally_pts = float(metrics.get("rallyPoints") or 0)
    min_pts = float(metrics.get("minMovePoints") or 0)
    if rally_pts < min_pts:
        return False, f"rally_{rally_pts:.0f}<{min_pts:.0f}pts", metrics

    chart = snap.spotChart
    if chart is None:
        return False, "no_chart", metrics

    min_rsi = float(getattr(settings, "index_rally_side_flip_min_rsi", 50.0) or 50.0)
    rsi = float(getattr(chart, "rsi", 0) or 0)
    if rsi < min_rsi:
        return False, f"rsi_{rsi:.1f}<{min_rsi:.1f}", metrics

    if bool(getattr(settings, "index_rally_side_flip_require_macd_bullish", True)):
        macd_bias = str(getattr(chart, "macdBias", "") or "NEUTRAL").upper()
        macd_hist = float(getattr(chart, "macdHistogram", 0) or 0)
        macd_ok = macd_bias == "BULLISH" or (macd_bias == "NEUTRAL" and macd_hist > 0)
        if not macd_ok:
            return False, f"macd_{macd_bias.lower()}", metrics

    min_mom5 = float(getattr(settings, "index_rally_side_flip_min_mom5_pct", 0.05) or 0.05)
    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0)
    if mom5 < min_mom5:
        return False, f"mom5_{mom5:.2f}<{min_mom5:.2f}", metrics

    metrics.update({"lockedSide": locked, "direction": direction, "breadth": breadth, "mode": "rally"})
    return True, "index_rally_side_flip", metrics


def _put_slide_bypass(
    sym: str,
    snap: SymbolSnapshot,
    settings: Any,
    *,
    locked: str | None,
    direction: str,
    breadth: str,
) -> tuple[bool, str, dict[str, Any]]:
    if bool(getattr(settings, "index_rally_side_flip_require_call_session", True)):
        call_session = locked == "CALL" or direction == "BULLISH" or breadth == "BULLISH"
        if not call_session:
            return False, "no_call_session", {"lockedSide": locked, "direction": direction}

    metrics = index_rally_metrics(sym, snap, settings=settings)
    slide_pts = float(metrics.get("slidePoints") or 0)
    min_pts = float(metrics.get("minMovePoints") or 0)
    if slide_pts < min_pts:
        return False, f"slide_{slide_pts:.0f}<{min_pts:.0f}pts", metrics

    chart = snap.spotChart
    if chart is None:
        return False, "no_chart", metrics

    max_rsi = float(getattr(settings, "index_rally_side_flip_max_rsi", 50.0) or 50.0)
    rsi = float(getattr(chart, "rsi", 0) or 0)
    if rsi > max_rsi:
        return False, f"rsi_{rsi:.1f}>{max_rsi:.1f}", metrics

    if bool(getattr(settings, "index_rally_side_flip_require_macd_bearish", True)):
        macd_bias = str(getattr(chart, "macdBias", "") or "NEUTRAL").upper()
        macd_hist = float(getattr(chart, "macdHistogram", 0) or 0)
        macd_ok = macd_bias == "BEARISH" or (macd_bias == "NEUTRAL" and macd_hist < 0)
        if not macd_ok:
            return False, f"macd_{macd_bias.lower()}", metrics

    min_mom5 = float(getattr(settings, "index_rally_side_flip_min_mom5_pct", 0.05) or 0.05)
    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0)
    if mom5 > -min_mom5:
        return False, f"mom5_{mom5:.2f}>-{min_mom5:.2f}", metrics

    metrics.update({"lockedSide": locked, "direction": direction, "breadth": breadth, "mode": "slide"})
    return True, "index_slide_side_flip", metrics


def index_rally_side_flip_bypass(
    symbol: str,
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    True when a sustained index move + aligned RSI/MACD should unlock the opposite
    side despite sticky session lock or stale breadth/chart bias.

    CALL: rally off session low after a PUT session.
    PUT:  slide off session high after a CALL session.
    """
    settings = settings or get_settings()
    if not bool(getattr(settings, "index_rally_side_flip_enabled", True)):
        return False, "disabled", {}

    side_v = _side_val(side)
    if side_v not in {"CALL", "PUT"}:
        return False, "invalid_side", {}

    sym = str(symbol or "").upper()
    if not _symbol_allowed(sym, settings):
        return False, "symbol_not_enabled", {}

    from app.engines.directional_lock import market_direction, session_locked_side

    locked = session_locked_side(sym)
    direction = market_direction(snap)
    breadth = (snap.breadth.bias or "NEUTRAL").upper() if snap.breadth else "NEUTRAL"

    if side_v == "CALL":
        return _call_rally_bypass(
            sym, snap, settings, locked=locked, direction=direction, breadth=breadth,
        )
    return _put_slide_bypass(
        sym, snap, settings, locked=locked, direction=direction, breadth=breadth,
    )
