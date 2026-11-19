"""Chart structure (session range, VWAP, pivots) for targeted entry waivers — CE/PE symmetric."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import SymbolSnapshot
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _session_range_position(symbol: str, snap: Any) -> tuple[float, dict[str, Any]]:
    from app.engines.index_tick_helpers import resolve_index_session

    meta: dict[str, Any] = {}
    ext = resolve_index_session(symbol, snap)
    hi = float(ext.get("hi") or 0)
    lo = float(ext.get("lo") or 0)
    spot = float(ext.get("last") or 0) or float(getattr(snap, "spot", 0) or 0)
    if hi <= 0 or lo <= 0 or spot <= 0:
        meta["rangeReason"] = "missing_extremes"
        return 0.5, meta
    hi, lo = max(hi, spot), min(lo, spot)
    span = hi - lo
    pos = (spot - lo) / span if span > 0 else 0.5
    meta.update(
        {
            "sessionHigh": round(hi, 2),
            "sessionLow": round(lo, 2),
            "spot": round(spot, 2),
            "rangePosition": round(pos, 4),
        }
    )
    return pos, meta


def _pivot_level(snap: Any, key: str = "P") -> float:
    ca = getattr(snap, "chartAnalysis", None) if snap is not None else None
    if ca is None:
        return 0.0
    pivots = getattr(ca, "pivots", None) or {}
    if not isinstance(pivots, dict):
        return 0.0
    try:
        return float(pivots.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def chart_pivot_confirms_side(side: str, snap: Any, *, buffer_pct: float = 0.0) -> tuple[bool, dict[str, Any]]:
    """CALL: spot at/above pivot P. PUT: spot at/below pivot P."""
    side_u = str(side or "").upper()
    spot = float(getattr(snap, "spot", 0) or 0)
    p = _pivot_level(snap, "P")
    meta: dict[str, Any] = {"pivotP": p, "spot": spot}
    if p <= 0 or spot <= 0:
        meta["pivotReason"] = "missing"
        return False, meta
    buf = abs(buffer_pct) / 100.0 * p
    if side_u == "CALL":
        ok = spot >= p - buf - 1e-6
        meta["pivotReason"] = "call_at_or_above_p" if ok else "call_below_p"
        return ok, meta
    if side_u == "PUT":
        ok = spot <= p + buf + 1e-6
        meta["pivotReason"] = "put_at_or_below_p" if ok else "put_above_p"
        return ok, meta
    meta["pivotReason"] = "unknown_side"
    return False, meta


def chart_structure_open_reclaim_ok(
    symbol: str,
    side: str,
    snap: Any,
    *,
    settings: Any = None,
    when: Optional[datetime] = None,
) -> tuple[bool, dict[str, Any]]:
    """
    PDF open-caution reclaim: index in upper/lower session range with VWAP + pivot confirm.

    CALL on bearish cash open: upper range (default 60%) + (VWAP bullish reclaim OR spot ≥ pivot P).
    PUT on bullish cash open: lower range (default 40%) + (VWAP bearish loss OR spot ≤ pivot P).
    """
    settings = settings or get_settings()
    meta: dict[str, Any] = {"chartStructureOpenReclaim": True}
    if not bool(
        getattr(settings, "open_caution_chart_structure_reclaim_waiver_enabled", True)
    ):
        meta["chartStructureReason"] = "disabled"
        return False, meta
    when = when or datetime.now(IST)
    if when.tzinfo is None:
        when = when.replace(tzinfo=IST)
    start_h = int(getattr(settings, "open_caution_chart_reclaim_earliest_hour", 9) or 9)
    start_m = int(getattr(settings, "open_caution_chart_reclaim_earliest_minute", 25) or 25)
    if (when.hour, when.minute) < (start_h, start_m):
        meta["chartStructureReason"] = "before_earliest_ist"
        return False, meta

    side_u = str(side or "").upper()
    range_pos, range_meta = _session_range_position(symbol, snap)
    meta.update(range_meta)
    call_min = float(
        getattr(settings, "open_caution_call_reclaim_min_range_position", 0.60) or 0.60
    )
    put_max = float(
        getattr(settings, "open_caution_put_reclaim_max_range_position", 0.40) or 0.40
    )

    from app.engines.advanced_indicators import index_vwap_confirms_side

    from app.models.schemas import Side

    vwap_ok = index_vwap_confirms_side(Side(side_u) if side_u in ("CALL", "PUT") else side_u, snap)
    pivot_ok, pivot_meta = chart_pivot_confirms_side(side_u, snap)
    meta.update(pivot_meta)
    meta["vwapReclaim"] = vwap_ok

    if side_u == "CALL":
        if range_pos < call_min - 1e-6:
            meta["chartStructureReason"] = "call_range_too_low"
            return False, meta
        if vwap_ok or pivot_ok:
            meta["chartStructureReason"] = "ok"
            meta["openChartStructureReclaimWaiver"] = True
            return True, meta
        meta["chartStructureReason"] = "call_no_vwap_or_pivot"
        return False, meta

    if side_u == "PUT":
        if range_pos > put_max + 1e-6:
            meta["chartStructureReason"] = "put_range_too_high"
            return False, meta
        if vwap_ok or pivot_ok:
            meta["chartStructureReason"] = "ok"
            meta["openChartStructureReclaimWaiver"] = True
            return True, meta
        meta["chartStructureReason"] = "put_no_vwap_or_pivot"
        return False, meta

    meta["chartStructureReason"] = "unknown_side"
    return False, meta


def index_continuation_chart_structure_ok(
    side: str,
    snap: Optional[SymbolSnapshot],
    *,
    settings: Any = None,
    when: Optional[datetime] = None,
) -> tuple[bool, dict[str, Any]]:
    """Before noon: VWAP reclaim + pivot side confirm (structure-backed continuation)."""
    settings = settings or get_settings()
    meta: dict[str, Any] = {"indexContinuationChartStructure": True}
    if not bool(
        getattr(settings, "index_continuation_chart_structure_waive_enabled", True)
    ):
        meta["chartStructureReason"] = "disabled"
        return False, meta
    when = when or datetime.now(IST)
    if when.tzinfo is None:
        when = when.replace(tzinfo=IST)
    end_h = int(getattr(settings, "index_continuation_chart_structure_until_hour", 12) or 12)
    end_m = int(getattr(settings, "index_continuation_chart_structure_until_minute", 0) or 0)
    if (when.hour, when.minute) >= (end_h, end_m):
        meta["chartStructureReason"] = "after_morning_window"
        return False, meta
    if snap is None:
        meta["chartStructureReason"] = "no_snap"
        return False, meta

    from app.engines.advanced_indicators import index_vwap_confirms_side
    from app.models.schemas import Side

    side_u = str(side or "").upper()
    vwap_ok = index_vwap_confirms_side(Side(side_u), snap)
    pivot_ok, pivot_meta = chart_pivot_confirms_side(side_u, snap)
    meta.update(pivot_meta)
    meta["vwapReclaim"] = vwap_ok
    if not (vwap_ok and pivot_ok):
        meta["chartStructureReason"] = "vwap_or_pivot_missing"
        return False, meta
    meta["chartStructureReason"] = "ok"
    meta["indexContinuationChartStructureOk"] = True
    return True, meta