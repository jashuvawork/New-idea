"""#676 book flip capture — entry infra only (no pad rank / best_trade_policy changes).

When symmetric CE/PE capture is on, stale bearish breadth can still fill a PUT while
CALL legs die on exec_mtf_premium_*_fading. These guards:
- Block PUT on bullish session tape (midday mirror of open side align).
- Block PUT into an active index rally on CHOP + RALLY.
- Defer opposite side briefly after same-index CE MTF premium fade reject.
- Block premium MTF that opposes side (PUT + bullish premium rip, CE mirror).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")

MTF_PREMIUM_FADE_REJECT_REASONS = frozenset({
    "exec_mtf_premium_1m_fading",
    "exec_mtf_premium_5m_fading",
    "exec_premium_fading_at_execution",
    "exec_premium_chart_fading",
})

_DEFAULT_PAD676_FLIP_DAY_MODES = frozenset({
    "CHOP + RALLY",
    "CHOP DAY",
    "CHOP (PRE-10)",
    "MOMENTUM RALLY",
})

_opposite_fade_defer_until: dict[tuple[str, str], datetime] = {}
_session_date: str | None = None


def _roll_session(now: datetime) -> None:
    global _session_date
    today = now.astimezone(IST).strftime("%Y-%m-%d")
    if _session_date != today:
        _opposite_fade_defer_until.clear()
        _session_date = today


def pad676_side_aligns_with_session_tape(
    symbol: str,
    side: Side | str,
    snap: Any = None,
    *,
    settings: Any = None,
) -> bool:
    """True when index move from session open does not oppose this side (CE/PE mirror)."""
    from app.engines.open_setup_guards import open_caution_side_align_ok

    align_ok, _, _ = open_caution_side_align_ok(
        symbol, side, snap, settings=settings or get_settings(),
    )
    return bool(align_ok)


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side or "").upper()


def _flip_day_modes(settings: Any) -> frozenset[str]:
    raw = str(getattr(settings, "pad676_flip_capture_day_modes_csv", "") or "").strip()
    if raw:
        return frozenset(s.strip().upper() for s in raw.split(",") if s.strip())
    return _DEFAULT_PAD676_FLIP_DAY_MODES


def pad676_flip_capture_active(
    *,
    day_mode: str = "",
    settings: Any = None,
) -> bool:
    settings = settings or get_settings()
    if not bool(getattr(settings, "pad676_flip_capture_guard_enabled", True)):
        return False
    dm = str(day_mode or "").strip().upper()
    if not dm:
        return False
    return dm in _flip_day_modes(settings)


def record_pad676_mtf_fade_reject(
    symbol: str,
    side: Side | str,
    reason: str,
    *,
    now: Optional[datetime] = None,
) -> None:
    """After one side's MTF/fade reject, defer the opposite side on the same index briefly."""
    settings = get_settings()
    if not bool(getattr(settings, "pad676_defer_put_after_ce_fade_enabled", True)):
        return
    side_v = _side_val(side)
    if side_v == "CALL":
        defer_side = "PUT"
    elif side_v == "PUT":
        defer_side = "CALL"
    else:
        return
    if reason not in MTF_PREMIUM_FADE_REJECT_REASONS:
        return
    current = (now or datetime.now(IST)).astimezone(IST)
    _roll_session(current)
    seconds = int(getattr(settings, "pad676_defer_put_after_ce_fade_seconds", 120) or 120)
    if seconds <= 0:
        return
    sym = str(symbol or "").upper()
    if sym:
        _opposite_fade_defer_until[(sym, defer_side)] = current + timedelta(seconds=seconds)


def record_pad676_ce_mtf_fade_reject(
    symbol: str,
    side: Side | str,
    reason: str,
    *,
    now: Optional[datetime] = None,
) -> None:
    """Backward-compatible alias — records CE/PE symmetric opposite defer."""
    record_pad676_mtf_fade_reject(symbol, side, reason, now=now)


def pad676_defer_opposite_after_mtf_fade_blocked(
    symbol: str,
    side: Side | str,
    *,
    now: Optional[datetime] = None,
) -> tuple[bool, str]:
    settings = get_settings()
    if not bool(getattr(settings, "pad676_defer_put_after_ce_fade_enabled", True)):
        return False, ""
    side_v = _side_val(side)
    if side_v not in ("CALL", "PUT"):
        return False, ""
    current = (now or datetime.now(IST)).astimezone(IST)
    _roll_session(current)
    sym = str(symbol or "").upper()
    until = _opposite_fade_defer_until.get((sym, side_v))
    if until is None or current >= until:
        return False, ""
    if side_v == "PUT":
        return True, "pad676_defer_put_after_ce_mtf_fade_reject"
    return True, "pad676_defer_call_after_pe_mtf_fade_reject"


def pad676_defer_put_after_ce_fade_blocked(
    symbol: str,
    side: Side | str,
    *,
    now: Optional[datetime] = None,
) -> tuple[bool, str]:
    blocked, reason = pad676_defer_opposite_after_mtf_fade_blocked(
        symbol, side, now=now,
    )
    if blocked and _side_val(side) == "PUT":
        return True, reason
    return False, ""


def pad676_session_tape_blocks_side(
    symbol: str,
    side: Side | str,
    snap: Any = None,
    *,
    when: Optional[datetime] = None,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Midday: no PUT on bullish session tape / no CALL on bearish (CE/PE mirror)."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "pad676_session_tape_align_enabled", True)):
        return False, "", {}
    when = (when or datetime.now(IST)).astimezone(IST)
    from app.engines.open_index_lane import in_open_caution_window_at

    if in_open_caution_window_at(when):
        return False, "", {}
    from app.engines.open_setup_guards import open_caution_side_align_ok

    align_ok, reason, meta = open_caution_side_align_ok(
        symbol, side, snap, settings=settings,
    )
    if align_ok:
        return False, "", meta
    if reason == "open_caution_put_on_bullish_open":
        return True, "pad676_session_put_on_bullish_tape", meta
    if reason == "open_caution_call_on_bearish_open":
        return True, "pad676_session_call_on_bearish_tape", meta
    return False, "", meta


def pad676_put_into_index_rally_blocked(
    symbol: str,
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    day_mode: str = "",
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """CHOP + RALLY: do not open PUT while index is rallying off the low above open."""
    settings = settings or get_settings()
    meta: dict[str, Any] = {"pad676RallyGuard": True}
    if _side_val(side) != "PUT":
        return False, "", meta
    if not pad676_flip_capture_active(day_mode=day_mode, settings=settings):
        return False, "", meta
    if not bool(getattr(settings, "pad676_block_put_into_index_rally_enabled", True)):
        return False, "", meta

    from app.engines.index_rally_side_flip import index_rally_metrics

    metrics = index_rally_metrics(symbol, snap, settings=settings)
    meta["indexRallyMetrics"] = metrics
    rally_pts = float(metrics.get("rallyPoints") or 0)
    min_pts = float(metrics.get("minMovePoints") or 0)
    mom5 = float(metrics.get("momentum5Pct") or 0)
    if rally_pts < min_pts or mom5 < 0:
        return False, "", meta

    from app.engines.index_tick_helpers import resolve_index_session

    ext = resolve_index_session(symbol, snap)
    session_open = float(ext.get("open") or 0)
    spot = float(ext.get("last") or 0) or float(getattr(snap, "spot", 0) or 0)
    if session_open <= 0 or spot <= 0:
        return False, "", meta
    min_move = float(getattr(settings, "open_side_confirmation_min_index_move_pct", 0.10) or 0.10)
    move_pct = (spot - session_open) / session_open * 100.0
    meta["sessionOpen"] = round(session_open, 2)
    meta["spot"] = round(spot, 2)
    meta["movePctFromOpen"] = round(move_pct, 3)
    if move_pct >= min_move:
        return True, "pad676_put_into_index_rally", meta
    return False, "", meta


def premium_mtf_opposes_entry_side(
    side: Side | str,
    premium_mtf: Optional[dict[str, Any]],
    *,
    settings: Any = None,
    waive_opposing: bool = False,
    symbol: str = "",
    snap: Any = None,
) -> tuple[bool, str]:
    """
    PUT + bullish expanding premium / CALL + bearish collapsing premium at execution.
    Waive pad-lane / open-setup fade only when session tape still aligns with this side.
    """
    if waive_opposing:
        if snap is None:
            return False, ""
        if pad676_side_aligns_with_session_tape(symbol, side, snap, settings=settings):
            return False, ""
        # Misaligned side (e.g. PUT on bullish open): never waive opposing premium.
    settings = settings or get_settings()
    if not bool(getattr(settings, "pad676_premium_mtf_opposing_block_enabled", True)):
        return False, ""
    if not premium_mtf or not getattr(settings, "execution_chart_premium_check_enabled", True):
        return False, ""

    side_v = _side_val(side)
    min_opp = float(
        getattr(settings, "pad676_premium_mtf_opposing_min_momentum_pct", 0.45) or 0.45
    )

    for req in ("5m", "15m"):
        pt = premium_mtf.get(req)
        if pt is None:
            continue
        direction = str(getattr(pt, "direction", "") or "").upper()
        try:
            mom = float(getattr(pt, "momentumPct", 0) or 0)
        except (TypeError, ValueError):
            mom = 0.0
        if side_v == "PUT" and direction == "BULLISH" and mom >= min_opp:
            return True, f"exec_mtf_premium_{req}_opposing_put"
        if side_v == "CALL" and direction == "BEARISH" and mom <= -min_opp:
            return True, f"exec_mtf_premium_{req}_opposing_call"
    return False, ""


def pad676_flip_capture_entry_blocked(
    candidate: Any,
    *,
    day_mode: str = "",
    settings: Any = None,
    when: Optional[datetime] = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Pretrade bundle for #676 symmetric capture days."""
    settings = settings or get_settings()
    meta: dict[str, Any] = {}
    if not pad676_flip_capture_active(day_mode=day_mode, settings=settings):
        return False, "", meta
    meta["pad676FlipCapture"] = True

    sym = str(getattr(candidate, "symbol", "") or "")
    side = getattr(candidate, "side", "")
    snap = getattr(candidate, "snap", None)
    when = when or getattr(snap, "timestamp", None) if snap is not None else None
    if when is not None and not isinstance(when, datetime):
        when = None

    defer, defer_reason = pad676_defer_opposite_after_mtf_fade_blocked(sym, side, now=when)
    if defer:
        return True, defer_reason, meta

    tape_block, tape_reason, tape_meta = pad676_session_tape_blocks_side(
        sym, side, snap, when=when, settings=settings,
    )
    meta.update(tape_meta)
    if tape_block:
        return True, tape_reason, meta

    if snap is not None:
        rally_block, rally_reason, rally_meta = pad676_put_into_index_rally_blocked(
            sym, side, snap, day_mode=day_mode, settings=settings,
        )
        meta.update(rally_meta)
        if rally_block:
            return True, rally_reason, meta

    return False, "", meta
