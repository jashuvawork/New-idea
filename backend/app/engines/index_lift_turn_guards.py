"""Hard blocks for counter-trend entries during index V-reversal turns.

When spot is rallying off the session low (visible CE lift), new PUT entries are blocked
at a lower point threshold than full index_rally_side_flip unlock. Mirror: slide off
session high blocks CALL.
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot
from app.engines.index_rally_side_flip import index_rally_metrics


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side or "").upper()


def _block_put_min_pts(symbol: str, settings: Any) -> float:
    sym = symbol.upper()
    if sym == "NIFTY":
        return float(
            getattr(settings, "index_lift_turn_block_put_min_pts_nifty", 35.0) or 35.0
        )
    if sym == "BANKNIFTY":
        return float(
            getattr(settings, "index_lift_turn_block_put_min_pts_banknifty", 60.0) or 60.0
        )
    return float(getattr(settings, "index_lift_turn_block_put_min_pts", 70.0) or 70.0)


def _block_call_min_pts(symbol: str, settings: Any) -> float:
    sym = symbol.upper()
    if sym == "NIFTY":
        return float(
            getattr(settings, "index_lift_turn_block_call_min_pts_nifty", 35.0) or 35.0
        )
    if sym == "BANKNIFTY":
        return float(
            getattr(settings, "index_lift_turn_block_call_min_pts_banknifty", 60.0) or 60.0
        )
    return float(getattr(settings, "index_lift_turn_block_call_min_pts", 70.0) or 70.0)


def index_session_rally_turn_active(
    symbol: str,
    snap: SymbolSnapshot,
    *,
    settings: Any = None,
) -> tuple[bool, dict[str, Any]]:
    """Spot has lifted meaningfully off today's low — CE lift regime."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "index_lift_turn_block_put_enabled", True)):
        return False, {}
    sym = str(symbol or "").upper()
    allowed = {
        s.strip().upper()
        for s in str(
            getattr(settings, "index_lift_turn_symbols_csv", "SENSEX,NIFTY,BANKNIFTY") or ""
        ).split(",")
        if s.strip()
    }
    if allowed and sym not in allowed:
        return False, {}

    metrics = index_rally_metrics(sym, snap, settings=settings)
    rally_pts = float(metrics.get("rallyPoints") or 0)
    min_pts = _block_put_min_pts(sym, settings)
    if rally_pts < min_pts:
        return False, {**metrics, "rallyPoints": rally_pts, "minPts": min_pts}

    chart = snap.spotChart
    if chart is None:
        return False, metrics

    min_mom5 = float(getattr(settings, "index_lift_turn_min_mom5_pct", 0.02) or 0.02)
    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0)

    from app.engines.spot_direction import index_trough_momentum_turn

    trough_turn = index_trough_momentum_turn(Side.CALL, chart, settings=settings)
    mom_ok = mom5 >= min_mom5
    if not mom_ok and not trough_turn:
        return False, {**metrics, "mom5": mom5, "troughTurn": trough_turn}

    return True, {
        **metrics,
        "rallyPoints": rally_pts,
        "minPts": min_pts,
        "mom5": mom5,
        "troughTurn": trough_turn,
        "mode": "index_session_rally_turn",
    }


def index_session_slide_turn_active(
    symbol: str,
    snap: SymbolSnapshot,
    *,
    settings: Any = None,
) -> tuple[bool, dict[str, Any]]:
    """Spot has slid meaningfully off today's high — PE slide regime."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "index_lift_turn_block_call_enabled", True)):
        return False, {}
    sym = str(symbol or "").upper()
    allowed = {
        s.strip().upper()
        for s in str(
            getattr(settings, "index_lift_turn_symbols_csv", "SENSEX,NIFTY,BANKNIFTY") or ""
        ).split(",")
        if s.strip()
    }
    if allowed and sym not in allowed:
        return False, {}

    metrics = index_rally_metrics(sym, snap, settings=settings)
    slide_pts = float(metrics.get("slidePoints") or 0)
    min_pts = _block_call_min_pts(sym, settings)
    if slide_pts < min_pts:
        return False, {**metrics, "slidePoints": slide_pts, "minPts": min_pts}

    chart = snap.spotChart
    if chart is None:
        return False, metrics

    min_mom5 = float(getattr(settings, "index_lift_turn_min_mom5_pct", 0.02) or 0.02)
    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0)

    from app.engines.spot_direction import index_trough_momentum_turn

    peak_turn = index_trough_momentum_turn(Side.PUT, chart, settings=settings)
    mom_ok = mom5 <= -min_mom5
    if not mom_ok and not peak_turn:
        return False, {**metrics, "mom5": mom5, "peakTurn": peak_turn}

    return True, {
        **metrics,
        "slidePoints": slide_pts,
        "minPts": min_pts,
        "mom5": mom5,
        "peakTurn": peak_turn,
        "mode": "index_session_slide_turn",
    }


def index_lift_turn_blocks_side(
    symbol: str,
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Return (blocked, reason, meta) when side fights an active index V-turn."""
    settings = settings or get_settings()
    side_v = _side_val(side)
    if side_v == "PUT":
        active, meta = index_session_rally_turn_active(symbol, snap, settings=settings)
        if active:
            return True, "index_lift_turn_blocks_put", meta
    elif side_v == "CALL":
        active, meta = index_session_slide_turn_active(symbol, snap, settings=settings)
        if active:
            return True, "index_lift_turn_blocks_call", meta
    return False, "ok", {}
