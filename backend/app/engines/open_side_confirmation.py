"""Open side confirmation — no blind side picks while the session is forming.

Oct 13 NIFTY 22300 PE: entered 09:15:37 off a PUT premium "local low" with a 5m chart
built from the previous session's bars, while NIFTY V-reversed up off the open and the
22300 CE ran +194%. During the open window the side must be confirmed by *today's*
index tape: price moved away from the session open in the trade's direction and sits
in that side's half of the session range. CALL and PUT are exact mirrors.
Macro index side confirmation runs **09:25–09:45** IST (first entries may still
fire from 09:20 under PR #676 capture lanes). The cash open is the broker day
open when the quote has it; a pre-open tick or a restart tick is not the open.

PR #676 top-moment capture (ATM/ITM base + first lift) may waive the macro index
move/range bar when structural base + lift evidence is already confirmed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN_MINUTES = 9 * 60 + 15


def _ist_minutes(now: datetime) -> float:
    return now.hour * 60 + now.minute + now.second / 60.0


def open_side_confirmation_window_start_minutes(settings: Any) -> float:
    settings = settings or get_settings()
    return (
        int(_cfg_float(settings, "open_side_confirmation_start_hour", 9)) * 60
        + int(_cfg_float(settings, "open_side_confirmation_start_minute", 25))
    )


def open_side_confirmation_window_end_minutes(settings: Any) -> float:
    settings = settings or get_settings()
    return (
        int(_cfg_float(settings, "open_caution_until_hour", 9)) * 60
        + int(_cfg_float(settings, "open_caution_until_minute", 45))
    )


def open_side_index_confirmation_window_active(
    now: datetime,
    settings: Any = None,
) -> bool:
    """True during macro index side confirmation (default 09:25–09:44:59 IST)."""
    settings = settings or get_settings()
    minutes = _ist_minutes(now.astimezone(IST))
    start = open_side_confirmation_window_start_minutes(settings)
    end = open_side_confirmation_window_end_minutes(settings)
    return start <= minutes < end


def _cfg_float(settings: Any, name: str, default: float) -> float:
    v = getattr(settings, name, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return float(default)
    return float(v)


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def _candidate_evidence(candidate: Any) -> dict[str, Any]:
    alert = getattr(candidate, "alert", None)
    alert_d = dict(alert) if isinstance(alert, dict) else {}
    pretrade = getattr(candidate, "pretrade_meta", None) or {}
    ranking = pretrade.get("causalRanking") if isinstance(pretrade, dict) else {}
    if not isinstance(ranking, dict):
        ranking = {}
    nested = ranking.get("evidence") if isinstance(ranking.get("evidence"), dict) else {}
    return {**alert_d, **nested, **ranking}


def open_side_top_moment_capture_waived(
    candidate: Any,
    snap: Any = None,
    *,
    state: Any = None,
    settings: Any = None,
) -> tuple[bool, str]:
    """True when PR #676-style base + lift capture should not wait on macro index move."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "open_side_top_moment_capture_waive_enabled", True)):
        return False, ""
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False, ""
    sym = str(getattr(candidate, "symbol", "") or "").upper()
    side_v = _side_val(getattr(candidate, "side", ""))
    snap = snap or getattr(candidate, "snap", None)
    if not sym or side_v not in ("CALL", "PUT"):
        return False, ""

    if side_v == "CALL":
        from app.engines.best_trade_policy import call_atm_itm_base_rank_armed

        armed, arm_mode = call_atm_itm_base_rank_armed(
            candidate, snap, state=state, settings=settings,
        )
        if armed:
            return True, "call_atm_itm_base_capture" if arm_mode == "eligible" else "call_atm_itm_near_base_pad"

    evidence = _candidate_evidence(candidate)
    pretrade = getattr(candidate, "pretrade_meta", None) or {}
    ranking = pretrade.get("causalRanking") if isinstance(pretrade, dict) else {}
    if not isinstance(ranking, dict):
        ranking = {}
    tier = str(evidence.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING", "BUILDING"):
        return False, ""

    from app.engines.best_trade_policy import (
        _call_atm_itm_launch_ok,
        symmetric_structural_base_evidence,
    )

    if not symmetric_structural_base_evidence(evidence, settings=settings):
        return False, ""
    if not _call_atm_itm_launch_ok(evidence, snap=snap, settings=settings):
        return False, ""

    if side_v == "PUT":
        from app.engines.put_slide_ce_mirror import put_slide_entry_unlock_fingerprint

        if put_slide_entry_unlock_fingerprint(
            evidence,
            ranking,
            None,
            state=state,
            snap=snap,
            symbol=sym,
            settings=settings,
        ):
            return True, "put_slide_top_moment_capture"

    return True, "first_lift_structural_base"


def open_side_confirmation(
    symbol: str,
    side: Side | str,
    snap: Any = None,
    *,
    candidate: Any = None,
    state: Any = None,
    now: Optional[datetime] = None,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Return (blocked, reason, meta) for an entry on ``side`` during the open window."""
    settings = settings or get_settings()
    if getattr(settings, "open_side_confirmation_enabled", True) is not True:
        return False, "", {}
    now = (now or datetime.now(IST)).astimezone(IST)
    minutes = _ist_minutes(now)
    if not open_side_index_confirmation_window_active(now, settings):
        return False, "", {}

    side_v = _side_val(side)

    from app.engines.index_tick_helpers import (
        broker_day_ohlc,
        index_session_extremes,
        resolve_index_session,
    )

    ext = resolve_index_session(symbol, snap)
    session_open = float(ext.get("open") or 0)
    hi = float(ext.get("hi") or 0)
    lo = float(ext.get("lo") or 0)
    spot = float(ext.get("last") or 0) or float(getattr(snap, "spot", 0) or 0)
    if session_open <= 0 or spot <= 0 or hi <= 0 or lo <= 0:
        return True, "open_side_no_session_tape", {}
    broker_open, _, _ = broker_day_ohlc(snap)
    if broker_open <= 0:
        tape = index_session_extremes(symbol)
        tape_ok = bool(tape.get("fromCashOpen")) and float(tape.get("open") or 0) > 0
        if not tape_ok:
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
    side_reason = ""
    blocked_side = False
    if side_v == "CALL":
        if move_pct < min_move:
            blocked_side, side_reason = True, "open_side_call_index_not_above_open"
        elif range_pos < min_pos:
            blocked_side, side_reason = True, "open_side_call_not_in_upper_range"
    elif side_v == "PUT":
        if move_pct > -min_move:
            blocked_side, side_reason = True, "open_side_put_index_not_below_open"
        elif range_pos > 1.0 - min_pos:
            blocked_side, side_reason = True, "open_side_put_not_in_lower_range"

    if blocked_side and candidate is not None:
        waived, waive_reason = open_side_top_moment_capture_waived(
            candidate, snap, state=state, settings=settings,
        )
        if waived:
            meta["openSideCaptureWaived"] = waive_reason
            return False, "", meta
    if blocked_side:
        return True, side_reason, meta
    return False, "", meta


def open_side_confirmation_summary(snapshots: dict[str, Any], *, settings: Any = None) -> dict[str, Any]:
    """HUD: whether CE / PE would pass open confirmation right now, per symbol."""
    settings = settings or get_settings()
    out: dict[str, Any] = {
        "enabled": getattr(settings, "open_side_confirmation_enabled", True) is True,
        "windowStartIst": (
            f"{int(getattr(settings, 'open_side_confirmation_start_hour', 9)):02d}:"
            f"{int(getattr(settings, 'open_side_confirmation_start_minute', 25)):02d}"
        ),
        "windowEndIst": (
            f"{int(getattr(settings, 'open_caution_until_hour', 9)):02d}:"
            f"{int(getattr(settings, 'open_caution_until_minute', 45)):02d}"
        ),
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
