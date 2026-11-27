"""Slide-open / rally-open lanes — timing + session-high counter blocks (CE/PE symmetric)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _side_u(side: Any) -> str:
    return side.value if isinstance(side, Side) else str(side or "").upper()


def _in_slide_open_window(*, settings: Any = None) -> bool:
    settings = settings or get_settings()
    now = datetime.now(IST)
    start_h = int(getattr(settings, "session_slide_open_lane_start_hour", 9) or 9)
    start_m = int(getattr(settings, "session_slide_open_lane_start_minute", 45) or 45)
    end_h = int(getattr(settings, "session_slide_open_lane_end_hour", 10) or 10)
    end_m = int(getattr(settings, "session_slide_open_lane_end_minute", 45) or 45)
    start = now.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    end = now.replace(hour=end_h, minute=end_m, second=59, microsecond=0)
    return start <= now <= end


def _index_below_open(snap: SymbolSnapshot, sym: str) -> tuple[bool, dict[str, Any]]:
    from app.engines.spot_direction import pro_index_quote_context

    qctx = pro_index_quote_context({}, float(snap.spot or 0))
    below = bool(qctx.get("belowDayOpen"))
    return below, {"belowDayOpen": below, **qctx}


def slide_open_put_elite_timing_waiver(
    evidence: Mapping[str, Any],
    state: Any,
    snap: SymbolSnapshot | None,
    *,
    settings: Any = None,
) -> tuple[bool, dict[str, Any]]:
    settings = settings or get_settings()
    meta: dict[str, Any] = {}
    if not bool(getattr(settings, "session_slide_open_lane_enabled", True)):
        return False, meta
    side = _side_u(evidence.get("side"))
    if side != "PUT":
        return False, meta
    if not _in_slide_open_window(settings=settings):
        return False, meta
    sym = str(evidence.get("symbol") or getattr(snap, "symbol", "") or "").upper()
    if snap is None:
        return False, meta

    from app.engines.session_intent_authority import resolve_session_intent

    intent = resolve_session_intent(sym, snap, state, settings=settings)
    meta["sessionIntent"] = intent
    if str(intent.get("participationSide") or "") != "PUT":
        return False, meta
    if intent.get("confidence") != "HIGH":
        return False, meta

    below, open_meta = _index_below_open(snap, sym)
    meta.update(open_meta)
    if not below:
        return False, meta

    put_mtf = (intent.get("mtf") or {}).get("PUT") or {}
    if int(put_mtf.get("htfAlignCount") or 0) < 1:
        return False, meta

    tier = str(evidence.get("tier") or "").upper()
    local = float(evidence.get("localBaseMovePct") or evidence.get("offLowMovePct") or 0)
    max_local = float(
        getattr(settings, "session_slide_open_put_max_local_pad_pct", 22.0) or 22.0
    )
    if local > max_local + 1e-6:
        return False, meta
    if tier not in ("EXPLODING", "ELITE", "BUILDING"):
        return False, meta

    meta["slideOpenPutTimingWaiver"] = True
    return True, meta


def rally_open_call_elite_timing_waiver(
    evidence: Mapping[str, Any],
    state: Any,
    snap: SymbolSnapshot | None,
    *,
    settings: Any = None,
) -> tuple[bool, dict[str, Any]]:
    settings = settings or get_settings()
    meta: dict[str, Any] = {}
    if not bool(getattr(settings, "session_slide_open_lane_enabled", True)):
        return False, meta
    side = _side_u(evidence.get("side"))
    if side != "CALL":
        return False, meta
    if not _in_slide_open_window(settings=settings):
        return False, meta
    sym = str(evidence.get("symbol") or getattr(snap, "symbol", "") or "").upper()
    if snap is None:
        return False, meta

    from app.engines.session_intent_authority import resolve_session_intent

    intent = resolve_session_intent(sym, snap, state, settings=settings)
    if str(intent.get("participationSide") or "") != "CALL":
        return False, meta
    if intent.get("confidence") != "HIGH":
        return False, meta

    below, open_meta = _index_below_open(snap, sym)
    meta.update(open_meta)
    if below:
        return False, meta

    call_mtf = (intent.get("mtf") or {}).get("CALL") or {}
    if int(call_mtf.get("htfAlignCount") or 0) < 1:
        return False, meta

    local = float(evidence.get("localBaseMovePct") or evidence.get("offLowMovePct") or 0)
    max_local = float(
        getattr(settings, "session_slide_open_put_max_local_pad_pct", 22.0) or 22.0
    )
    if local > max_local + 1e-6:
        return False, meta
    meta["rallyOpenCallTimingWaiver"] = True
    return True, meta


def session_call_near_day_high_blocked(
    candidate: Any,
    state: Any,
    snapshots: dict[str, SymbolSnapshot],
    *,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    settings = settings or get_settings()
    meta: dict[str, Any] = {}
    if not bool(getattr(settings, "session_call_near_day_high_block_enabled", True)):
        return False, "ok", meta

    side = _side_u(getattr(candidate, "side", None))
    if side != "CALL":
        return False, "ok", meta

    sym = str(getattr(candidate, "symbol", "") or "").upper()
    snap = snapshots.get(sym) or getattr(candidate, "snap", None)
    if snap is None:
        return False, "ok", meta

    from app.engines.index_tick_helpers import resolve_index_session
    from app.engines.session_intent_authority import resolve_session_intent

    intent = resolve_session_intent(sym, snap, state, settings=settings)
    meta["sessionIntent"] = intent
    if str(intent.get("participationSide") or "BOTH") == "CALL":
        return False, "ok", meta
    if str(intent.get("sessionLeg") or "") != "SLIDE":
        return False, "ok", meta

    ext = resolve_index_session(sym, snap)
    hi = float(ext.get("hi") or 0)
    spot = float(ext.get("last") or 0) or float(getattr(snap, "spot", 0) or 0)
    if hi <= 0 or spot <= 0:
        return False, "ok", meta

    near_pct = float(
        getattr(settings, "session_call_near_day_high_off_high_pct", 0.15) or 0.15
    )
    off_high = (hi - spot) / hi * 100.0
    meta["offSessionHighPct"] = round(off_high, 3)
    if off_high > near_pct + 1e-6:
        return False, "ok", meta

    session_move = 0.0
    alert = getattr(candidate, "alert", None)
    if isinstance(alert, dict):
        session_move = max(
            float(alert.get("dailyMovePct") or alert.get("peakMovePct") or 0),
            float(alert.get("localBaseMovePct") or 0),
        )
    meta["sessionMovePct"] = round(session_move, 2)
    min_move = float(
        getattr(settings, "session_call_near_day_high_min_session_move_pct", 25.0) or 25.0
    )
    if session_move < min_move - 1e-6:
        return False, "ok", meta

    return True, "session_call_near_day_high_on_slide", meta