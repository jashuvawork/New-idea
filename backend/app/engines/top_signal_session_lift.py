"""Centralized session-lift detection for top FTV/V, ELITE, and explosive trades.

When any qualifying top signal is on radar (or a candidate qualifies at order time),
session halts (worst-day pause, live block, expiry wait, daily caps, last-N pause,
whipsaw pause) lift to elite-only mode instead of blocking the session entirely.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import get_settings
from app.models.schemas import SymbolSnapshot


def _lift_enabled() -> bool:
    return bool(getattr(get_settings(), "top_signal_session_lift_enabled", True))


def snapshots_have_top_signal_session_lift(
    snapshots: Optional[dict[str, SymbolSnapshot]],
) -> bool:
    """True when radar has any top-tier signal that should lift session halts."""
    if not snapshots or not _lift_enabled():
        return False

    from app.engines.extreme_explosion_moment import snapshots_have_all_in_explosion

    if snapshots_have_all_in_explosion(snapshots):
        return True

    from app.engines.elite_never_block import snapshots_have_top_must_take

    if snapshots_have_top_must_take(snapshots):
        return True

    from app.engines.top_ftv_v_expiry_bypass import snapshots_have_top_ftv_or_v

    if snapshots_have_top_ftv_or_v(snapshots):
        return True

    from app.engines.bullish_local_base import snapshots_have_bullish_local_base_pad

    if snapshots_have_bullish_local_base_pad(snapshots):
        return True

    return False


def candidate_qualifies_top_signal_session_lift(
    candidate: Any,
    *,
    snap: Optional[SymbolSnapshot] = None,
    alert: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Per-candidate check for order-time session lift (live block, controlled cap, etc.)."""
    if not _lift_enabled():
        return False

    from app.engines.extreme_explosion_moment import is_extreme_explosion_all_in_bypass

    if is_extreme_explosion_all_in_bypass(candidate=candidate):
        return True

    snap_v = snap or getattr(candidate, "snap", None)
    alert_row = alert
    if alert_row is None:
        raw = getattr(candidate, "alert", None)
        alert_row = raw if isinstance(raw, dict) else {}

    from app.engines.elite_never_block import elite_never_block_active

    if elite_never_block_active(candidate=candidate, alert=alert_row, snap=snap_v):
        return True

    from app.engines.top_ftv_v_expiry_bypass import is_top_ftv_or_v_candidate

    if is_top_ftv_or_v_candidate(candidate):
        return True

    from app.engines.expiry_day_guards import is_expiry_elite_top_candidate

    if is_expiry_elite_top_candidate(candidate):
        return True

    from app.engines.grade_a_ftv_capture import is_grade_a_ftv_first_lift_candidate

    if is_grade_a_ftv_first_lift_candidate(candidate):
        return True

    if alert_row:
        from app.engines.bullish_local_base import alert_is_bullish_local_base_pad_entry

        if alert_is_bullish_local_base_pad_entry(alert_row, snap_v):
            return True

    return False


def candidate_qualifies_daily_cap_elite_bypass(candidate: Any) -> bool:
    """Per-candidate gate when daily cap is lifted for elite/top signals only."""
    return candidate_qualifies_top_signal_session_lift(candidate)
