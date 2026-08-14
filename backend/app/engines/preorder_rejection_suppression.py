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
})

_suppressed_until: dict[tuple[str, str, str, float, str, str], datetime] = {}
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
        _session_date = today


def suppress_after_preorder_rejection(
    candidate: Any,
    reason: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Suppress only typed premium-fade failures known to happen before submission."""
    if reason not in PREORDER_PREMIUM_FADING_REASONS:
        return False
    current = now or datetime.now(IST)
    _roll_session(current)
    seconds = max(
        0,
        int(getattr(get_settings(), "preorder_rejection_suppression_seconds", 30) or 0),
    )
    if seconds <= 0:
        return False
    _suppressed_until[_candidate_key(candidate)] = current + timedelta(seconds=seconds)
    return True


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


def reset_preorder_rejection_suppressions() -> None:
    global _session_date
    _suppressed_until.clear()
    _session_date = None
