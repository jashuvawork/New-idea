"""Lower rank/score floors for first pad catches — before top/chase sleeves."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings


def early_catch_pretrade_min_rank(
    candidate: Any,
    *,
    settings: Any | None = None,
) -> Optional[float]:
    """Return a lowered pretrade rank floor when this is a pad/first-lift catch."""
    s = settings or get_settings()
    alert = getattr(candidate, "alert", None)
    alert_row = dict(alert) if isinstance(alert, dict) else {}
    snap = getattr(candidate, "snap", None)
    event = getattr(candidate, "explosion_event", None)

    from app.engines.grade_a_ftv_capture import is_grade_a_ftv_first_lift_candidate

    if is_grade_a_ftv_first_lift_candidate(candidate):
        return float(getattr(s, "grade_a_ftv_first_lift_min_rank", 40.0) or 40.0)

    from app.engines.bullish_local_base import alert_is_bullish_local_base_pad_entry

    if alert_row and alert_is_bullish_local_base_pad_entry(alert_row, snap):
        return float(getattr(s, "early_catch_pad_min_rank", 35.0) or 35.0)

    from app.engines.early_radar_pad_capture import alert_has_early_radar_pad_capture

    if alert_has_early_radar_pad_capture(alert_row):
        return float(getattr(s, "early_catch_pad_min_rank", 35.0) or 35.0)

    from app.engines.top_ftv_v_expiry_bypass import is_top_ftv_or_v_candidate

    if is_top_ftv_or_v_candidate(candidate):
        return float(getattr(s, "top_ftv_v_expiry_bypass_min_rank", 0.0) or 0.0)

    if event is not None and snap is not None:
        from app.engines.ict_breakout_monitor import first_lift_entry_ready

        if first_lift_entry_ready(snap=snap, event=event, alert=alert_row or None):
            return float(getattr(s, "first_lift_early_pad_min_rank", 38.0) or 38.0)

    from app.engines.pad_lane_capture import pad_lane_early_near_miss_waive

    if pad_lane_early_near_miss_waive(alert_row, snap=snap):
        return float(getattr(s, "early_catch_pad_min_rank", 35.0) or 35.0)

    return None
