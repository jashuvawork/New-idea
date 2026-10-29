"""09:20–09:45 open book: index lanes + cash-open side align + ITM depth (CE/PE symmetric)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.config import get_settings
from app.engines.open_index_lane import (
    _index_bucket,
    _side_value,
    in_open_caution_window_at,
    resolve_lane_when,
    validate_open_index_lane,
)
from app.models.schemas import SymbolSnapshot
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _active_open_lanes(settings: Any) -> list[tuple[str, str]]:
    from app.engines.open_index_lane import allowed_open_lane_sides

    lanes: list[tuple[str, str]] = []
    for index in ("SENSEX", "NIFTY"):
        sides = allowed_open_lane_sides(index, settings)
        if not sides:
            continue
        for side in sorted(sides):
            lanes.append((index, side))
    return lanes


def _candidate_lane_tuple(candidate: Any) -> tuple[str | None, str]:
    index = _index_bucket(str(getattr(candidate, "symbol", "") or ""))
    side = _side_value(getattr(candidate, "side", ""))
    return index, side


def _max_itm_points(index: str | None, side: str, settings: Any) -> float:
    if index == "NIFTY" and side == "PUT":
        return float(getattr(settings, "open_caution_nifty_put_max_itm_points", 400.0) or 400.0)
    if index == "SENSEX" and side == "CALL":
        return float(getattr(settings, "open_caution_sensex_call_max_itm_points", 800.0) or 800.0)
    if index == "SENSEX" and side == "PUT":
        return float(getattr(settings, "open_caution_sensex_put_max_itm_points", 800.0) or 800.0)
    return float(getattr(settings, "open_caution_default_max_itm_points", 800.0) or 800.0)


def open_caution_itm_depth_ok(
    side: str,
    strike: float,
    spot: float,
    *,
    symbol: str = "",
    settings: Any = None,
) -> tuple[bool, float, dict[str, Any]]:
    """ITM with spot−strike (CALL) or strike−spot (PUT) within configured open band."""
    settings = settings or get_settings()
    meta: dict[str, Any] = {"openItmBand": True}
    if spot <= 0 or strike <= 0:
        meta["itmReason"] = "missing_spot_or_strike"
        return False, 0.0, meta
    side_u = _side_value(side)
    if side_u == "CALL":
        if spot < strike:
            meta["itmReason"] = "call_not_itm"
            return False, 0.0, meta
        depth = spot - strike
    elif side_u == "PUT":
        if spot > strike:
            meta["itmReason"] = "put_not_itm"
            return False, 0.0, meta
        depth = strike - spot
    else:
        meta["itmReason"] = "unknown_side"
        return False, 0.0, meta
    index = _index_bucket(symbol)
    cap = _max_itm_points(index, side_u, settings)
    meta["itmDepthPoints"] = round(depth, 2)
    meta["itmMaxPoints"] = cap
    if depth > cap + 1e-6:
        meta["itmReason"] = "open_caution_itm_too_deep"
        return False, depth, meta
    meta["itmReason"] = "ok"
    return True, depth, meta


def _resolve_spot(candidate: Any, snapshots: Optional[dict[str, SymbolSnapshot]]) -> float:
    snap = getattr(candidate, "snap", None)
    if snap is None and snapshots:
        snap = snapshots.get(str(getattr(candidate, "symbol", "") or "").upper())
    if snap is not None:
        try:
            return float(getattr(snap, "spot", 0) or 0)
        except (TypeError, ValueError):
            pass
    alert = getattr(candidate, "alert", None)
    if isinstance(alert, dict):
        for key in ("spot", "indexSpot", "underlyingSpot"):
            try:
                val = float(alert.get(key) or 0)
            except (TypeError, ValueError):
                val = 0.0
            if val > 0:
                return val
    return 0.0


def open_caution_side_align_ok(
    symbol: str,
    side: str,
    snap: Any,
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Block PUT on bullish open / CALL on bearish open; allow either when tape is flat."""
    settings = settings or get_settings()
    meta: dict[str, Any] = {"openSideAlign": True}
    if bool(getattr(settings, "open_caution_block_puts_enabled", False)) and _side_value(side) == "PUT":
        nifty_put_lane = bool(getattr(settings, "open_nifty_put_lane_enabled", False))
        if not (nifty_put_lane and _index_bucket(symbol) == "NIFTY"):
            return False, "open_caution_puts_blocked", meta
    if not bool(getattr(settings, "open_caution_side_align_index_enabled", True)):
        return True, "ok", meta
    from app.engines.index_tick_helpers import resolve_index_session

    ext = resolve_index_session(symbol, snap)
    session_open = float(ext.get("open") or 0)
    spot = float(ext.get("last") or 0) or float(getattr(snap, "spot", 0) or 0)
    if session_open <= 0 or spot <= 0:
        meta["openSideAlignTape"] = "missing"
        return True, "ok", meta
    min_move = float(getattr(settings, "open_side_confirmation_min_index_move_pct", 0.10) or 0.10)
    move_pct = (spot - session_open) / session_open * 100.0
    meta["sessionOpen"] = round(session_open, 2)
    meta["spot"] = round(spot, 2)
    meta["movePct"] = round(move_pct, 3)
    side_u = _side_value(side)
    if move_pct >= min_move and side_u == "PUT":
        return False, "open_caution_put_on_bullish_open", meta
    if move_pct <= -min_move and side_u == "CALL":
        return False, "open_caution_call_on_bearish_open", meta
    return True, "ok", meta


def open_setup_guard_summary(settings: Any = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return {
        "sideAlignIndex": bool(getattr(settings, "open_caution_side_align_index_enabled", True)),
        "legacyBlockAllPuts": bool(getattr(settings, "open_caution_block_puts_enabled", False)),
        "blockPutsInOpen": bool(getattr(settings, "open_caution_block_puts_enabled", False)),
        "nonLaneIndexBlocked": bool(
            getattr(settings, "open_caution_non_lane_index_blocked", True)
        ),
        "itmBandEnabled": bool(getattr(settings, "open_caution_itm_band_enabled", True)),
        "sensexCallMaxItmPoints": float(
            getattr(settings, "open_caution_sensex_call_max_itm_points", 800.0) or 800.0
        ),
        "sensexPutMaxItmPoints": float(
            getattr(settings, "open_caution_sensex_put_max_itm_points", 800.0) or 800.0
        ),
        "niftyPutMaxItmPoints": float(
            getattr(settings, "open_caution_nifty_put_max_itm_points", 400.0) or 400.0
        ),
        "fadeBypassMinRank": float(
            getattr(settings, "open_caution_premium_fade_min_rank_score", 90.0) or 90.0
        ),
        "deepItmRankBonus": float(getattr(settings, "open_caution_deep_itm_rank_bonus", 20.0) or 20.0),
        "selectorExpiryOtmPrefilter": bool(
            getattr(settings, "selector_expiry_otm_prefilter_enabled", True)
        ),
    }


def validate_open_setup_entry(
    candidate: Any,
    *,
    settings: Any = None,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
    when: Optional[datetime] = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Open caution guards before SELECT / pretrade. Idle outside 09:20–09:45.
    """
    settings = settings or get_settings()
    when = resolve_lane_when(candidate, when)
    meta: dict[str, Any] = {"openSetupGuard": True}
    if not in_open_caution_window_at(when):
        return True, "ok", {}

    if not bool(getattr(settings, "open_setup_guards_enabled", True)):
        return True, "ok", meta

    index, side = _candidate_lane_tuple(candidate)
    meta["openIndex"] = index
    meta["openSide"] = side

    sym = str(getattr(candidate, "symbol", "") or "")
    snap = getattr(candidate, "snap", None)
    if snap is None and snapshots:
        snap = snapshots.get(sym.upper())
    align_ok, align_reason, align_meta = open_caution_side_align_ok(
        sym, side, snap, settings=settings,
    )
    meta.update(align_meta)
    if not align_ok:
        return False, align_reason, meta

    lanes = _active_open_lanes(settings)
    if bool(getattr(settings, "open_caution_non_lane_index_blocked", True)) and lanes:
        allowed = any(index == idx and side == req for idx, req in lanes)
        if not allowed:
            return False, "open_caution_non_lane_index", meta

    lane_ok, lane_reason, lane_meta = validate_open_index_lane(
        candidate, settings=settings, when=when,
    )
    meta.update(lane_meta)
    if not lane_ok:
        return False, lane_reason, meta

    if bool(getattr(settings, "open_caution_itm_band_enabled", True)):
        strike = float(getattr(candidate, "strike", 0) or 0)
        spot = _resolve_spot(candidate, snapshots)
        itm_ok, depth, itm_meta = open_caution_itm_depth_ok(
            side,
            strike,
            spot,
            symbol=str(getattr(candidate, "symbol", "") or ""),
            settings=settings,
        )
        meta.update(itm_meta)
        meta["openItmDepthPoints"] = depth
        if not itm_ok:
            reason = str(itm_meta.get("itmReason") or "open_caution_itm_band")
            return False, reason, meta

    meta["openSetupGuardPassed"] = True
    return True, "ok", meta


def open_caution_deep_itm_rank_bonus(
    candidate: Any,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
    *,
    settings: Any = None,
    when: Optional[datetime] = None,
) -> float:
    """Prefer deeper ITM (73000 over 73400) during open caution."""
    settings = settings or get_settings()
    when = resolve_lane_when(candidate, when)
    if not in_open_caution_window_at(when):
        return 0.0
    if not bool(getattr(settings, "open_caution_deep_itm_rank_bonus_enabled", True)):
        return 0.0
    _, side = _candidate_lane_tuple(candidate)
    strike = float(getattr(candidate, "strike", 0) or 0)
    spot = _resolve_spot(candidate, snapshots)
    itm_ok, depth, _ = open_caution_itm_depth_ok(
        side,
        strike,
        spot,
        symbol=str(getattr(candidate, "symbol", "") or ""),
        settings=settings,
    )
    if not itm_ok or depth <= 0:
        return 0.0
    cap = _max_itm_points(_index_bucket(str(getattr(candidate, "symbol", "") or "")), side, settings)
    if cap <= 0:
        return 0.0
    frac = min(1.0, depth / cap)
    bonus = float(getattr(settings, "open_caution_deep_itm_rank_bonus", 20.0) or 20.0)
    return round(frac * bonus, 2)


def _record_selector_prefilter_rejection(candidate: Any, reason: str) -> None:
    try:
        from app.services.radar_learning import record_funnel_gate_block

        side = getattr(candidate, "side", "")
        side_v = side.value if hasattr(side, "value") else str(side)
        record_funnel_gate_block(
            str(getattr(candidate, "symbol", "") or "").upper(),
            side_v,
            float(getattr(candidate, "strike", 0) or 0),
            str(reason or "selector_rejected"),
            stage="SELECTOR_GATE",
        )
    except Exception:
        pass


def daily_entry_prefilter_reason(
    candidate: Any,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
    *,
    state: Any = None,
    settings: Any = None,
) -> str:
    """Funnel reason if candidate must not rank; empty if OK. Day-agnostic (every session)."""
    settings = settings or get_settings()
    ok, reason, _ = validate_open_setup_entry(
        candidate, settings=settings, snapshots=snapshots,
    )
    if not ok:
        return str(reason or "open_setup_guard")

    if not bool(getattr(settings, "selector_expiry_otm_prefilter_enabled", True)):
        return ""
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return ""

    sym = str(getattr(candidate, "symbol", "") or "").upper()
    snap = getattr(candidate, "snap", None)
    if snap is None and snapshots:
        snap = snapshots.get(sym)
    if snap is None:
        return ""

    from app.engines.best_trade_policy import expiry_cheap_otm_entry_blocked

    alert = getattr(candidate, "alert", None)
    blocked, otm_reason = expiry_cheap_otm_entry_blocked(
        candidate,
        snap,
        alert if isinstance(alert, dict) else None,
        state=state,
        settings=settings,
    )
    return str(otm_reason or "") if blocked else ""


def filter_daily_entry_candidates(
    candidates: list[Any],
    snapshots: dict[str, SymbolSnapshot],
    *,
    state: Any = None,
    settings: Any = None,
    record_rejections: bool = True,
) -> list[Any]:
    """Open setup + expiry OTM pre-rank filter with funnel telemetry."""
    settings = settings or get_settings()
    kept: list[Any] = []
    for c in candidates:
        reason = daily_entry_prefilter_reason(
            c, snapshots, state=state, settings=settings,
        )
        if reason:
            if record_rejections:
                _record_selector_prefilter_rejection(c, reason)
            continue
        kept.append(c)
    return kept


def filter_open_setup_candidates(
    candidates: list[Any],
    snapshots: dict[str, SymbolSnapshot],
    *,
    state: Any = None,
    settings: Any = None,
) -> list[Any]:
    """Backward-compatible alias — prefer filter_daily_entry_candidates."""
    return filter_daily_entry_candidates(
        candidates, snapshots, state=state, settings=settings,
    )


def open_caution_fade_bypass_rank_ok(
    alert: Optional[dict[str, Any]],
    *,
    settings: Any = None,
    causal_rank_score: Optional[float] = None,
    causal_grade: Optional[str] = None,
) -> bool:
    settings = settings or get_settings()
    min_rank = float(getattr(settings, "open_caution_premium_fade_min_rank_score", 90.0) or 90.0)
    rank = causal_rank_score
    grade = (causal_grade or "").upper()
    if rank is None and isinstance(alert, dict):
        try:
            rank = float(
                alert.get("causalRankScore")
                or alert.get("rankScore")
                or alert.get("selectionScore")
                or 0
            )
        except (TypeError, ValueError):
            rank = 0.0
    if grade == "" and isinstance(alert, dict):
        grade = str(alert.get("causalGrade") or alert.get("grade") or "").upper()
    if rank is not None and float(rank) >= min_rank - 1e-6:
        return True
    if bool(getattr(settings, "open_caution_premium_fade_allow_grade_s", True)) and grade == "S":
        return True
    return False
