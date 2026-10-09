"""Oct 1 pad location — side-aware session range (CE off high, PE slide pad)."""

from __future__ import annotations

from typing import Any, Mapping

from app.config import get_settings


def _side_u(side: Any) -> str:
    if hasattr(side, "value"):
        return str(side.value or "").upper()
    return str(side or "").upper()


def oct1_open_moment_pad_waived(
    side: str,
    evidence: Mapping[str, Any],
    *,
    settings: Any = None,
) -> tuple[bool, str]:
    """09:15–09:45 open-window pad waivers only (no first-lift context — avoids recursion)."""
    from app.engines.live_paper_parity import trading_rules_match_paper

    settings = settings or get_settings()
    if not trading_rules_match_paper(settings):
        return False, ""
    if not bool(getattr(settings, "oct_paper_open_moment_pad_waiver_enabled", True)):
        return False, ""
    side_u = _side_u(side)
    try:
        from app.engines.session_timing import in_open_premium_window

        if not in_open_premium_window():
            return False, ""
    except Exception:
        return False, ""
    if side_u == "CALL":
        off_low = float(evidence.get("offLowMovePct") or 0)
        min_off = float(
            getattr(settings, "live_paper_parity_min_off_session_low_pct", 6.0) or 6.0
        )
        if off_low >= min_off - 1e-6 and (
            evidence.get("armedBaseLaunch")
            or evidence.get("vRipReady")
            or str(evidence.get("momentType") or "")
            in (
                "armed_base_launch",
                "v_rip_session_low",
                "flat_then_vertical",
                "first_lift_local_base",
            )
        ):
            return True, "oct_open_call_rip_pad_waive"
    elif side_u == "PUT":
        from app.engines.put_slide_ce_mirror import put_slide_pad_context

        if put_slide_pad_context(evidence, settings=settings):
            return True, "oct_open_put_slide_pad_waive"
    return False, ""


def oct1_pad_location_waived(
    side: str,
    evidence: Mapping[str, Any],
    *,
    settings: Any = None,
    readiness_reason: str = "",
) -> tuple[bool, str]:
    """Open-window + first-lift waivers before session-high/low chase checks."""
    from app.engines.live_paper_parity import (
        oct_paper_first_lift_small_lift_context,
        trading_rules_match_paper,
    )

    settings = settings or get_settings()
    if not trading_rules_match_paper(settings):
        return False, ""
    if oct_paper_first_lift_small_lift_context(
        evidence,
        settings=settings,
        readiness_reason=readiness_reason,
    ):
        return True, "oct_first_lift_pad_waive"
    return oct1_open_moment_pad_waived(side, evidence, settings=settings)


def oct1_premium_location_chase_blocked(
    side: str,
    pos: float,
    dd: float,
    evidence: Mapping[str, Any],
    *,
    settings: Any = None,
    readiness_reason: str = "",
) -> tuple[bool, str]:
    """
    True when fill location is wrong for Oct 1 pad (not near-base pad).

    CALL: block at option session high / upper range (Oct 7 chase).
    PUT:  slide-pad waives high block; block at session *low* (extended dump chase).
    """
    settings = settings or get_settings()
    waived, _ = oct1_pad_location_waived(
        side, evidence, settings=settings, readiness_reason=readiness_reason,
    )
    if waived:
        return False, ""

    side_u = _side_u(side)
    max_pos = float(
        getattr(settings, "live_paper_parity_max_session_range_position", 0.52) or 0.52
    )
    min_off_high = float(
        getattr(settings, "live_paper_parity_min_off_session_high_pct", 6.0) or 6.0
    )

    if side_u == "PUT" and bool(
        getattr(settings, "live_paper_parity_put_slide_waives_session_high_block", True)
    ):
        from app.engines.put_slide_ce_mirror import put_slide_pad_context

        if put_slide_pad_context(evidence, settings=settings):
            return False, ""

    if side_u == "CALL":
        if pos > max_pos + 1e-6:
            return True, "live_oct1_chase_session_range_high"
        if dd > -min_off_high + 1e-6:
            return True, "live_oct1_chase_at_session_high"
        return False, ""

    if side_u == "PUT":
        min_off_low = float(
            getattr(settings, "live_paper_parity_min_off_session_low_pct", 6.0) or 6.0
        )
        low_fraction = max(0.0, min(1.0, min_off_low / 100.0))
        if pos > 0 and pos < low_fraction - 1e-6:
            local = max(
                float(evidence.get("localBaseMovePct") or 0),
                float(evidence.get("ictBaseRelativeMovePct") or 0),
            )
            if local >= 12.0:
                return True, "live_oct1_put_chase_at_session_low"
        if pos > max_pos + 1e-6:
            return True, "live_oct1_chase_session_range_high"
        if dd > -min_off_high + 1e-6:
            return True, "live_oct1_chase_at_session_high"
        return False, ""

    if pos > max_pos + 1e-6:
        return True, "live_oct1_chase_session_range_high"
    if dd > -min_off_high + 1e-6:
        return True, "live_oct1_chase_at_session_high"
    return False, ""


def oct1_pad_location_ok(
    side: str,
    pos: float,
    dd: float,
    evidence: Mapping[str, Any],
    *,
    settings: Any = None,
    readiness_reason: str = "",
) -> bool:
    blocked, _ = oct1_premium_location_chase_blocked(
        side, pos, dd, evidence, settings=settings, readiness_reason=readiness_reason,
    )
    return not blocked
