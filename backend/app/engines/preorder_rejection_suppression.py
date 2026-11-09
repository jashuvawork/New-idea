"""Short-lived exact-leg suppression after safe pre-order execution rejections."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")

PREORDER_PREMIUM_FADING_REASONS = frozenset({
    "exec_premium_fading_at_execution",
    "exec_premium_chart_fading",
    "exec_premium_fading_high_score",
    "exec_mtf_premium_1m_fading",
    "exec_mtf_premium_5m_fading",
})

PREORDER_EXEC_CHASE_REASONS = frozenset({
    "premium_extended_session_near_base_chase",
    "exec_mtf_premium_htf_opposes",
    "premium_vertical_chase_at_high",
})

_suppressed_until: dict[tuple[str, str, str, float, str, str], datetime] = {}
# After a CALL fade-reject at execution, block PUT on the same index (and mirror CE after PE).
_symbol_opposite_suppressed_until: dict[tuple[str, str], datetime] = {}
_session_date: str | None = None


def _candidate_key(candidate: Any) -> tuple[str, str, str, float, str, str]:
    side = getattr(candidate, "side", "")
    side_value = side.value if isinstance(side, Side) else str(side).upper()
    strategy = getattr(candidate, "strategy_type", "")
    strategy_value = strategy.value if hasattr(strategy, "value") else str(strategy).upper()
    snap = getattr(candidate, "snap", None)
    expiry = str(getattr(snap, "optionExpiry", "") or "")
    return (
        str(getattr(candidate, "symbol", "") or "").upper(),
        expiry,
        side_value,
        float(getattr(candidate, "strike", 0) or 0),
        str(getattr(candidate, "mode", "") or "").lower(),
        strategy_value,
    )


def _roll_session(now: datetime) -> None:
    global _session_date
    today = now.astimezone(IST).strftime("%Y-%m-%d")
    if _session_date != today:
        _suppressed_until.clear()
        _symbol_opposite_suppressed_until.clear()
        _session_date = today


def _opposite_side(side_value: str) -> str:
    return "PUT" if side_value == "CALL" else "CALL"


def suppress_after_preorder_rejection(
    candidate: Any,
    reason: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Suppress only typed premium-fade failures known to happen before submission."""
    if reason not in PREORDER_PREMIUM_FADING_REASONS and reason not in PREORDER_EXEC_CHASE_REASONS:
        return False
    current = now or datetime.now(IST)
    _roll_session(current)
    settings = get_settings()
    recorded = False
    seconds = max(
        0,
        int(getattr(settings, "preorder_rejection_suppression_seconds", 30) or 0),
    )
    if seconds > 0:
        _suppressed_until[_candidate_key(candidate)] = current + timedelta(seconds=seconds)
        recorded = True

    if bool(getattr(settings, "preorder_reject_opposite_side_suppression_enabled", True)):
        opp_seconds = max(
            0,
            int(
                getattr(settings, "preorder_reject_opposite_side_suppression_seconds", 180)
                or 0
            ),
        )
        if opp_seconds > 0:
            side = getattr(candidate, "side", "")
            side_value = side.value if isinstance(side, Side) else str(side).upper()
            sym = str(getattr(candidate, "symbol", "") or "").upper()
            if side_value in {"CALL", "PUT"} and sym:
                opp = _opposite_side(side_value)
                _symbol_opposite_suppressed_until[(sym, opp)] = current + timedelta(
                    seconds=opp_seconds,
                )
                recorded = True
    return recorded


def candidate_preorder_rejection_suppressed(
    candidate: Any,
    *,
    now: datetime | None = None,
) -> bool:
    current = now or datetime.now(IST)
    _roll_session(current)
    key = _candidate_key(candidate)
    until = _suppressed_until.get(key)
    if until is None:
        return False
    if current < until:
        return True
    _suppressed_until.pop(key, None)
    return False


def symbol_opposite_side_preorder_blocked(
    candidate: Any,
    *,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """Block PUT after a recent CALL premium-fade reject on the same index (mirror for PE→CE)."""
    settings = get_settings()
    if not bool(getattr(settings, "preorder_reject_opposite_side_suppression_enabled", True)):
        return False, "ok"
    current = now or datetime.now(IST)
    _roll_session(current)
    side = getattr(candidate, "side", "")
    side_value = side.value if isinstance(side, Side) else str(side).upper()
    sym = str(getattr(candidate, "symbol", "") or "").upper()
    if side_value not in {"CALL", "PUT"} or not sym:
        return False, "ok"
    until = _symbol_opposite_suppressed_until.get((sym, side_value))
    if until is None:
        return False, "ok"
    if current < until:
        if side_value == "PUT":
            from app.engines.index_lift_turn_guards import (
                index_lift_turn_option_rip_waiver,
            )

            rip_ok, _, _ = index_lift_turn_option_rip_waiver(
                Side.PUT,
                explosion_event=getattr(candidate, "explosion_event", None),
                alert=(
                    candidate.alert
                    if isinstance(getattr(candidate, "alert", None), dict)
                    else None
                ),
            )
            if rip_ok:
                return False, "ok"
        elif side_value == "CALL":
            from app.engines.index_lift_turn_guards import (
                index_lift_turn_option_rip_waiver,
            )

            rip_ok, _, _ = index_lift_turn_option_rip_waiver(
                Side.CALL,
                explosion_event=getattr(candidate, "explosion_event", None),
                alert=(
                    candidate.alert
                    if isinstance(getattr(candidate, "alert", None), dict)
                    else None
                ),
            )
            if rip_ok:
                return False, "ok"
        other = _opposite_side(side_value)
        return True, f"preorder_opposite_side_after_{other.lower()}_fade_reject"
    _symbol_opposite_suppressed_until.pop((sym, side_value), None)
    return False, "ok"


def reset_preorder_rejection_suppressions() -> None:
    global _session_date
    _suppressed_until.clear()
    _symbol_opposite_suppressed_until.clear()
    _session_date = None
