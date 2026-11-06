"""09:15–09:45 open book: index lanes + cash-open side align + ITM depth (CE/PE symmetric)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.config import get_settings
from app.engines.open_index_lane import (
    _index_bucket,
    _index_open_side_aligned,
    _side_value,
    allowed_open_lane_sides,
    in_open_caution_window_at,
    in_post_open_setup_window_at,
    open_setup_guard_when,
    validate_open_index_lane,
)
from app.models.schemas import SymbolSnapshot
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _active_open_lanes(
    settings: Any,
    *,
    candidate: Any = None,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
) -> list[tuple[str, str]]:
    from app.engines.open_index_lane import allowed_open_lane_sides

    lanes: list[tuple[str, str]] = []
    for index in ("SENSEX", "NIFTY"):
        snap = None
        if candidate is not None and _index_bucket(str(getattr(candidate, "symbol", "") or "")) == index:
            snap = getattr(candidate, "snap", None)
        if snap is None and snapshots:
            snap = snapshots.get(index)
        sides = allowed_open_lane_sides(
            index, settings, symbol=index, snap=snap, snapshots=snapshots,
        )
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
    when: Optional[datetime] = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Block PUT on bullish open / CALL on bearish open; allow either when tape is flat."""
    settings = settings or get_settings()
    meta: dict[str, Any] = {"openSideAlign": True}
    when = open_setup_guard_when(None, when)
    if not in_open_caution_window_at(when):
        return True, "ok", meta
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


_STRUCTURAL_WAIVER_CALL_MOMENTS = frozenset(
    {
        "v_rip_session_low",
        "armed_base_launch",
        "ict_base_armed",
        "first_lift_local_base",
    }
)
_STRUCTURAL_WAIVER_PUT_MOMENTS = frozenset(
    {
        "v_rip_session_high",
        "armed_base_launch",
        "ict_base_armed",
        "first_lift_local_base",
    }
)


def _structural_open_lift_moment_ok(alert: dict[str, Any], side: str) -> bool:
    side_u = _side_value(side)
    moment = str(alert.get("momentType") or "").lower()
    allowed = (
        _STRUCTURAL_WAIVER_CALL_MOMENTS
        if side_u == "CALL"
        else _STRUCTURAL_WAIVER_PUT_MOMENTS
    )
    if moment in allowed:
        return True
    if moment == "first_lift_local_base" and (
        alert.get("ictFirstLift") or alert.get("firstLift")
    ):
        return True
    if side_u == "CALL" and (
        alert.get("ictArmedBaseLaunch") or alert.get("armedBaseLaunch")
    ):
        return True
    if side_u == "PUT" and (
        alert.get("ictArmedBaseLaunch") or alert.get("armedBaseLaunch")
    ):
        return True
    return False


def _open_structural_pad_band_ok(alert: dict[str, Any], settings: Any) -> tuple[bool, float]:
    min_lb = float(getattr(settings, "shallow_otm_local_base_min_move_pct", 2.0) or 2.0)
    max_lb = float(
        getattr(settings, "open_caution_premium_fade_max_local_base_pct", 28.0) or 28.0
    )
    try:
        lb = float(
            alert.get("localBaseMovePct")
            or alert.get("ictBaseRelativeMovePct")
            or alert.get("offLowMovePct")
            or 0
        )
    except (TypeError, ValueError):
        lb = 0.0
    return min_lb <= lb <= max_lb + 1e-6, lb


def _open_structural_index_v_ok(
    symbol: str,
    side: str,
    snap: Any,
    *,
    settings: Any,
) -> tuple[bool, dict[str, Any]]:
    from app.engines.index_rally_side_flip import _min_move_pts
    from app.engines.index_tick_helpers import resolve_index_session

    meta: dict[str, Any] = {"structuralIndexV": True}
    ext = resolve_index_session(symbol, snap)
    hi = float(ext.get("hi") or 0)
    lo = float(ext.get("lo") or 0)
    spot = float(ext.get("last") or 0) or float(getattr(snap, "spot", 0) or 0)
    if hi <= 0 or lo <= 0 or spot <= 0:
        meta["structuralWaiverReason"] = "missing_session_extremes"
        return False, meta
    hi, lo = max(hi, spot), min(lo, spot)
    span = hi - lo
    range_pos = (spot - lo) / span if span > 0 else 0.5
    frac = float(
        getattr(settings, "open_caution_structural_waiver_rally_frac", 0.5) or 0.5
    )
    min_range = float(
        getattr(settings, "open_caution_structural_waiver_min_range_position", 0.30)
        or 0.30
    )
    near_pct = float(
        getattr(settings, "open_caution_structural_waiver_near_extreme_pct", 0.15) or 0.15
    )
    min_pts = _min_move_pts(symbol, settings) * frac
    side_u = _side_value(side)
    rally_pts = round(spot - lo, 1)
    slide_pts = round(hi - spot, 1)
    meta.update(
        {
            "sessionHigh": round(hi, 2),
            "sessionLow": round(lo, 2),
            "spot": round(spot, 2),
            "rangePosition": round(range_pos, 3),
            "rallyPoints": rally_pts,
            "slidePoints": slide_pts,
            "structuralMinMovePoints": round(min_pts, 1),
        }
    )
    if side_u == "CALL":
        near_extreme = lo > 0 and ((spot - lo) / lo * 100.0) <= near_pct + 1e-6
        ok = rally_pts >= min_pts - 1e-6 and (
            range_pos >= min_range - 1e-6 or near_extreme
        )
        if not ok:
            meta["structuralWaiverReason"] = "call_v_not_confirmed"
        return ok, meta
    if side_u == "PUT":
        near_extreme = hi > 0 and ((hi - spot) / hi * 100.0) <= near_pct + 1e-6
        ok = slide_pts >= min_pts - 1e-6 and (
            range_pos <= (1.0 - min_range) + 1e-6 or near_extreme
        )
        if not ok:
            meta["structuralWaiverReason"] = "put_v_not_confirmed"
        return ok, meta
    meta["structuralWaiverReason"] = "unknown_side"
    return False, meta


def open_caution_structural_side_align_waiver(
    candidate: Any,
    align_reason: str,
    *,
    symbol: str = "",
    side: str = "",
    snap: Any = None,
    settings: Any = None,
    when: Optional[datetime] = None,
) -> tuple[bool, dict[str, Any]]:
    """
    Waive open_caution_*_on_*_open when pad lift + index V off session extreme confirm.
    CE/PE symmetric (CALL on bearish open / PUT on bullish open only).
    """
    settings = settings or get_settings()
    meta: dict[str, Any] = {}
    when = open_setup_guard_when(candidate, when)
    if not in_open_caution_window_at(when):
        return False, meta
    if not bool(
        getattr(settings, "open_caution_structural_side_align_waiver_enabled", True)
    ):
        return False, meta
    side_u = _side_value(side or getattr(candidate, "side", ""))
    sym = str(symbol or getattr(candidate, "symbol", "") or "").upper()
    if side_u == "CALL" and align_reason != "open_caution_call_on_bearish_open":
        return False, meta
    if side_u == "PUT" and align_reason != "open_caution_put_on_bullish_open":
        return False, meta
    alert = getattr(candidate, "alert", None)
    if not isinstance(alert, dict):
        meta["structuralWaiverReason"] = "no_alert"
        return False, meta
    tier = str(
        alert.get("tier")
        or getattr(getattr(candidate, "explosion_event", None), "tier", "")
        or ""
    ).upper()
    if tier not in {"ELITE", "EXPLODING"}:
        meta["structuralWaiverReason"] = "tier_not_elite"
        return False, meta
    if not _structural_open_lift_moment_ok(alert, side_u):
        meta["structuralWaiverReason"] = "no_structural_lift_moment"
        return False, meta
    pad_ok, lb = _open_structural_pad_band_ok(alert, settings)
    meta["localBaseMovePct"] = lb
    if not pad_ok:
        meta["structuralWaiverReason"] = "local_base_out_of_band"
        return False, meta
    if not open_caution_fade_bypass_rank_ok(alert, settings=settings):
        meta["structuralWaiverReason"] = "rank_below_floor"
        return False, meta
    v_ok, v_meta = _open_structural_index_v_ok(sym, side_u, snap, settings=settings)
    meta.update(v_meta)
    if not v_ok:
        return False, meta
    meta["openStructuralSideAlignWaiver"] = True
    return True, meta


def open_setup_guard_summary(settings: Any = None) -> dict[str, Any]:
    settings = settings or get_settings()
    return {
        "sideAlignIndex": bool(getattr(settings, "open_caution_side_align_index_enabled", True)),
        "structuralSideAlignWaiver": bool(
            getattr(settings, "open_caution_structural_side_align_waiver_enabled", True)
        ),
        "legacyBlockAllPuts": bool(getattr(settings, "open_caution_block_puts_enabled", False)),
        "blockPutsInOpen": bool(getattr(settings, "open_caution_block_puts_enabled", False)),
        "nonLaneIndexBlocked": bool(
            getattr(settings, "open_caution_non_lane_index_blocked", True)
        ),
        "alignedSideLaneWaiver": bool(
            getattr(settings, "open_caution_aligned_side_lane_waiver_enabled", True)
        ),
        "openAlignedSideRankBonus": float(
            getattr(settings, "open_aligned_side_rank_bonus", 40.0) or 40.0
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
    Open caution guards before SELECT / pretrade. Idle outside 09:15–09:45.
    """
    settings = settings or get_settings()
    when = open_setup_guard_when(candidate, when)
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
        sym, side, snap, settings=settings, when=when,
    )
    meta.update(align_meta)
    if not align_ok:
        waived, waiver_meta = open_caution_structural_side_align_waiver(
            candidate,
            align_reason,
            symbol=sym,
            side=side,
            snap=snap,
            settings=settings,
            when=when,
        )
        meta.update(waiver_meta)
        if not waived:
            return False, align_reason, meta

    if bool(getattr(settings, "open_caution_non_lane_index_blocked", True)) and index:
        per_index_sides = allowed_open_lane_sides(
            index,
            settings,
            symbol=sym,
            snap=snap,
            snapshots=snapshots,
        )
        in_lane = per_index_sides is not None and side in per_index_sides
        if (
            not in_lane
            and bool(
                getattr(settings, "open_caution_aligned_side_lane_waiver_enabled", True)
            )
            and (
                _index_open_side_aligned(
                    index, side, symbol=sym, snap=snap, settings=settings,
                )
                or meta.get("openStructuralSideAlignWaiver")
            )
        ):
            in_lane = True
            if meta.get("openStructuralSideAlignWaiver"):
                meta["openStructuralSideLaneWaiver"] = True
            else:
                meta["openAlignedSideLaneWaiver"] = True
        if per_index_sides is not None and not in_lane:
            return False, "open_caution_non_lane_index", meta

    lane_ok, lane_reason, lane_meta = validate_open_index_lane(
        candidate, settings=settings, when=when, snapshots=snapshots,
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


def _open_book_side_align_ok(
    candidate: Any,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
    *,
    settings: Any = None,
    when: Optional[datetime] = None,
) -> bool:
    """True during open/post-open windows when index tape aligns with candidate side."""
    settings = settings or get_settings()
    when = open_setup_guard_when(candidate, when)
    if not (
        in_open_caution_window_at(when) or in_post_open_setup_window_at(when)
    ):
        return False
    index, side = _candidate_lane_tuple(candidate)
    if not index:
        return False
    sym = str(getattr(candidate, "symbol", "") or "")
    snap = getattr(candidate, "snap", None)
    if snap is None and snapshots:
        snap = snapshots.get(sym.upper())
    return _index_open_side_aligned(
        index, side, symbol=sym, snap=snap, settings=settings,
    )


def open_aligned_side_rank_bonus(
    candidate: Any,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
    *,
    settings: Any = None,
    when: Optional[datetime] = None,
) -> float:
    """Prefer session-aligned CE/PE during 09:15–post_open_setup (CE on bullish open, etc.)."""
    settings = settings or get_settings()
    if not _open_book_side_align_ok(
        candidate, snapshots, settings=settings, when=when,
    ):
        return 0.0
    bonus = float(getattr(settings, "open_aligned_side_rank_bonus", 40.0) or 0.0)
    return bonus if bonus > 0 else 0.0


def open_counter_trend_side_rank_penalty(
    candidate: Any,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
    *,
    settings: Any = None,
    when: Optional[datetime] = None,
) -> float:
    """09:45–10:30: deprioritize PUT on bullish tape / CALL on bearish (side align would pass)."""
    settings = settings or get_settings()
    when = open_setup_guard_when(candidate, when)
    if not in_post_open_setup_window_at(when):
        return 0.0
    index, side = _candidate_lane_tuple(candidate)
    if not index:
        return 0.0
    sym = str(getattr(candidate, "symbol", "") or "")
    snap = getattr(candidate, "snap", None)
    if snap is None and snapshots:
        snap = snapshots.get(sym.upper())
    if _index_open_side_aligned(
        index, side, symbol=sym, snap=snap, settings=settings,
    ):
        return 0.0
    penalty = float(getattr(settings, "open_counter_trend_side_rank_penalty", 45.0) or 0.0)
    return penalty if penalty > 0 else 0.0


def open_caution_deep_itm_rank_bonus(
    candidate: Any,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
    *,
    settings: Any = None,
    when: Optional[datetime] = None,
) -> float:
    """Prefer deeper ITM (73000 over 73400) during open caution."""
    settings = settings or get_settings()
    when = open_setup_guard_when(candidate, when)
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
