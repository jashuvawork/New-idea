"""Open side confirmation — no blind side picks while the session is forming.

Oct 13 NIFTY 22300 PE: entered 09:15:37 off a PUT premium "local low" with a 5m chart
built from the previous session's bars, while NIFTY V-reversed up off the open and the
22300 CE ran +194%. During the open window the side must be confirmed by *today's*
index tape: price moved away from the session open in the trade's direction and sits
in that side's half of the session range. CALL and PUT are exact mirrors.
Active from 09:15 until 09:45, then idle. The first minute stays blocked.
The first order stays 09:20. The cash open is the broker day open when the
quote has it; a pre-open tick or a restart tick is not the open.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN_MINUTES = 9 * 60 + 15


def _cfg_float(settings: Any, name: str, default: float) -> float:
    v = getattr(settings, name, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return float(default)
    return float(v)


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def open_side_confirmation(
    symbol: str,
    side: Side | str,
    snap: Any = None,
    *,
    now: Optional[datetime] = None,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Return (blocked, reason, meta) for an entry on ``side`` during the open window."""
    settings = settings or get_settings()
    if getattr(settings, "open_side_confirmation_enabled", True) is not True:
        return False, "", {}
    now = (now or datetime.now(IST)).astimezone(IST)
    minutes = now.hour * 60 + now.minute + now.second / 60.0
    until = (
        int(_cfg_float(settings, "open_caution_until_hour", 9)) * 60
        + int(_cfg_float(settings, "open_caution_until_minute", 45))
    )
    if minutes < MARKET_OPEN_MINUTES or minutes >= until:
        return False, "", {}

    side_v = _side_val(side)
    min_wait = _cfg_float(settings, "open_side_confirmation_min_minutes", 1.0)
    if minutes < MARKET_OPEN_MINUTES + min_wait:
        return True, "open_side_unconfirmed_first_bar", {
            "minutesSinceOpen": round(minutes - MARKET_OPEN_MINUTES, 2),
        }

    from app.engines.index_tick_helpers import broker_day_ohlc, resolve_index_session

    ext = resolve_index_session(symbol, snap)
    session_open = float(ext.get("open") or 0)
    hi = float(ext.get("hi") or 0)
    lo = float(ext.get("lo") or 0)
    spot = float(ext.get("last") or 0) or float(getattr(snap, "spot", 0) or 0)
    if session_open <= 0 or spot <= 0 or hi <= 0 or lo <= 0:
        return True, "open_side_no_session_tape", {}
    entry_earliest_min = (
        int(_cfg_float(settings, "entry_earliest_hour", 9)) * 60
        + int(_cfg_float(settings, "entry_earliest_minute", 20))
    )
    if minutes >= entry_earliest_min:
        broker_open, _, _ = broker_day_ohlc(snap)
        if broker_open <= 0:
            return True, "open_side_broker_day_open_required", {
                "sessionOpen": round(session_open, 2),
                "spot": round(spot, 2),
                "tapeOpenOnly": True,
            }
    hi, lo = max(hi, spot), min(lo, spot)

    move_pct = (spot - session_open) / session_open * 100.0
    span = hi - lo
    range_pos = (spot - lo) / span if span > 0 else 0.5
    meta = {
        "sessionOpen": round(session_open, 2),
        "spot": round(spot, 2),
        "sessionHigh": round(hi, 2),
        "sessionLow": round(lo, 2),
        "movePct": round(move_pct, 3),
        "rangePosition": round(range_pos, 3),
    }

    min_move = _cfg_float(settings, "open_side_confirmation_min_index_move_pct", 0.10)
    min_pos = _cfg_float(settings, "open_side_confirmation_min_range_position", 0.6)
    if side_v == "CALL":
        if move_pct < min_move:
            return True, "open_side_call_index_not_above_open", meta
        if range_pos < min_pos:
            return True, "open_side_call_not_in_upper_range", meta
    elif side_v == "PUT":
        if move_pct > -min_move:
            return True, "open_side_put_index_not_below_open", meta
        if range_pos > 1.0 - min_pos:
            return True, "open_side_put_not_in_lower_range", meta
    return False, "", meta


def open_side_confirmation_summary(snapshots: dict[str, Any], *, settings: Any = None) -> dict[str, Any]:
    """HUD: whether CE / PE would pass open confirmation right now, per symbol."""
    settings = settings or get_settings()
    out: dict[str, Any] = {
        "enabled": getattr(settings, "open_side_confirmation_enabled", True) is True,
        "symbols": {},
    }
    for sym, snap in (snapshots or {}).items():
        call_block, call_reason, meta = open_side_confirmation(sym, Side.CALL, snap, settings=settings)
        put_block, put_reason, _ = open_side_confirmation(sym, Side.PUT, snap, settings=settings)
        out["symbols"][sym] = {
            "callBlocked": call_block,
            "callReason": call_reason or None,
            "putBlocked": put_block,
            "putReason": put_reason or None,
            **meta,
        }
    return out
