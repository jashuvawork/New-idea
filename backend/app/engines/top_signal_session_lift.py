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


def _alert_is_coil_armed_top(
    alert: Optional[Mapping[str, Any]],
    settings: Any = None,
) -> bool:
    """A strongly-ripe, directional, near-base coil (from the coil predictor) counts as a
    top signal that may lift a chop/worst-day session halt.

    This is what lets the early-ignition / low-score lanes actually fire on a chop day —
    otherwise the session block vetoes the very near-base winner we want. Opt-in and gated
    to a HIGH coil readiness so ordinary chop coils do NOT re-open the session.
    """
    settings = settings or get_settings()
    if not bool(getattr(settings, "coil_armed_session_lift_enabled", False)):
        return False
    if not isinstance(alert, Mapping):
        return False
    if not bool(alert.get("coilCoiling")):
        return False
    side = str(alert.get("side") or "").upper()
    predicted = str(alert.get("coilPredictedSide") or "")
    if not predicted or predicted != side:
        return False
    readiness = float(alert.get("coilReadinessScore") or 0)
    if readiness < float(
        getattr(settings, "coil_armed_session_lift_min_readiness", 75.0) or 75.0
    ):
        return False
    base_move = float(
        alert.get("ictBaseRelativeMovePct") or alert.get("localBaseMovePct") or 0
    )
    if base_move > float(
        getattr(settings, "coil_armed_session_lift_max_base_move_pct", 12.0) or 12.0
    ):
        return False
    tier = str(alert.get("tier") or "").upper()
    # Top moment intent only: ELITE/EXPLODING, or FTV/V structure present.
    if tier not in ("ELITE", "EXPLODING") and not (
        alert.get("ictFlatThenVertical") or alert.get("ictVRipReady")
    ):
        return False
    return True


def snapshots_have_coil_armed_top_signal(
    snapshots: Optional[dict[str, SymbolSnapshot]],
) -> bool:
    """True when any radar alert is a strongly-ripe coil-armed top setup (opt-in)."""
    settings = get_settings()
    if not snapshots or not bool(
        getattr(settings, "coil_armed_session_lift_enabled", False)
    ):
        return False
    for snap in snapshots.values():
        if not getattr(snap, "dataAvailable", False):
            continue
        for alert in getattr(snap, "explosionAlerts", None) or []:
            if _alert_is_coil_armed_top(alert, settings):
                return True
    return False


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

    if snapshots_have_coil_armed_top_signal(snapshots):
        return True

    from app.engines.bad_day_routing import (
        snapshots_have_expiring_deep_itm_power_hour_setup,
    )

    if snapshots_have_expiring_deep_itm_power_hour_setup(snapshots):
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

    from app.engines.bad_day_routing import candidate_is_expiry_deep_itm_trade

    if snap_v is not None:
        sym = str(getattr(snap_v, "symbol", "") or getattr(candidate, "symbol", "") or "").upper()
        snap_map = {sym: snap_v} if sym else {}
        if candidate_is_expiry_deep_itm_trade(
            candidate, snap_map, power_hour_only=True,
        ):
            return True

    if alert_row:
        from app.engines.bullish_local_base import alert_is_bullish_local_base_pad_entry

        if alert_is_bullish_local_base_pad_entry(alert_row, snap_v):
            return True
        if _alert_is_coil_armed_top(alert_row):
            return True

    return False


def candidate_qualifies_daily_cap_elite_bypass(candidate: Any) -> bool:
    """Per-candidate gate when daily cap is lifted for elite/top signals only."""
    return candidate_qualifies_top_signal_session_lift(candidate)
