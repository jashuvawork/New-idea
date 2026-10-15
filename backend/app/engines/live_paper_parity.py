"""When armed for live paper parity (₹1.5L / ₹2L book), match paper rules — only execution differs."""

from __future__ import annotations

from typing import Any, Mapping

_OCT_FIRST_LIFT_SMALL_LIFT_MOMENTS = frozenset(
    {
        "armed_base_launch",
        "v_rip_session_low",
        "v_rip_session_high",
        "first_lift_local_base",
        "ict_base_armed",
        "ELITE_BASE_READY",
        "elite_base_ready",
        "flat_then_vertical",
        "volume_awaken",
    }
)


def _parity_number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def oct_paper_first_lift_small_lift_context(
    evidence: Mapping[str, Any] | None,
    *,
    settings: Any = None,
    readiness_reason: str = "",
) -> bool:
    """
    Oct 1 paper: symmetric CE/PE early armed-base / v-rip / first-lift at pad (small lift).

    When true under trading_rules_match_paper, chase-style selector/elite blocks are waived.
    negative_velocity and deep cold-tick rejects are not waived here.
    """
    from app.config import get_settings

    s = settings or get_settings()
    if not oct_paper_structural_entry_waivers_active(s):
        return False
    if not bool(getattr(s, "oct_paper_first_lift_small_lift_waiver_enabled", True)):
        return False
    if not isinstance(evidence, dict):
        return False

    tier = str(evidence.get("tier") or evidence.get("signalTier") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False

    moment = str(evidence.get("momentType") or "")
    rr = str(
        readiness_reason
        or evidence.get("firstLiftReadinessReason")
        or evidence.get("ictBaseReadinessReason")
        or ""
    ).lower()
    launch = (
        bool(evidence.get("firstLift") or evidence.get("ictFirstLift"))
        or bool(evidence.get("armedBaseLaunch") or evidence.get("ictArmedBaseLaunch"))
        or bool(evidence.get("eliteBaseReady") or evidence.get("ictEliteBaseReady"))
        or bool(evidence.get("vRipReady"))
        or moment in _OCT_FIRST_LIFT_SMALL_LIFT_MOMENTS
        or rr.startswith(
            (
                "armed_base",
                "v_rip_session_low",
                "v_rip_session_high",
                "first_lift",
                "ict_base",
            )
        )
    )
    if not launch:
        return False

    side = str(evidence.get("side") or "").upper()
    local = max(
        _parity_number(evidence.get("localBaseMovePct")),
        _parity_number(evidence.get("ictBaseRelativeMovePct")),
    )
    min_move = float(
        getattr(s, "oct_paper_first_lift_small_lift_min_local_pct", 2.0) or 2.0
    )
    max_move = float(
        getattr(s, "oct_paper_first_lift_small_lift_max_local_pct", 40.0) or 40.0
    )
    max_move = max(
        max_move,
        float(getattr(s, "first_lift_trade_max_move_pct", 40.0) or 40.0),
    )

    location_pad = False
    if side == "CALL":
        off_low = _parity_number(evidence.get("offLowMovePct"))
        min_off = float(
            getattr(s, "live_paper_parity_min_off_session_low_pct", 6.0) or 6.0
        )
        location_pad = off_low >= min_off - 1e-6
    elif side == "PUT":
        from app.engines.put_slide_ce_mirror import put_slide_pad_context

        location_pad = put_slide_pad_context(evidence, settings=s)

    session_pad = location_pad
    # First lift off a measured local base (2–40%) is pad entry, not session-high chase.
    if not session_pad and launch and min_move <= local <= max_move + 1e-6:
        session_pad = True

    pos = _parity_number(evidence.get("sessionRangePosition"))
    max_pos = float(
        getattr(s, "live_paper_parity_max_session_range_position", 0.52) or 0.52
    )
    dd = _parity_number(evidence.get("drawdownFromHighPct"))
    min_off_high = float(
        getattr(s, "live_paper_parity_min_off_session_high_pct", 6.0) or 6.0
    )
    dd_present = (
        evidence.get("drawdownFromHighPct") is not None
        and str(evidence.get("drawdownFromHighPct")).strip() != ""
    )
    from app.engines.oct1_pad_location import oct1_premium_location_chase_core

    chase_blocked, chase_reason = oct1_premium_location_chase_core(
        side,
        pos,
        dd,
        evidence,
        settings=s,
        dd_present=dd_present,
    )
    if chase_blocked:
        if chase_reason == "live_oct1_put_chase_at_session_low":
            if not location_pad:
                return False
        elif chase_reason == "live_oct1_chase_at_session_high":
            return False
        elif chase_reason == "live_oct1_chase_session_range_high":
            off_session_high = dd_present and dd > -min_off_high + 1e-6
            pad_ok = location_pad or (
                launch
                and min_move <= local <= max_move + 1e-6
                and not off_session_high
            )
            if not pad_ok:
                return False
        elif not (session_pad and launch):
            return False
    if pos > max_pos + 1e-6 and not session_pad:
        from app.engines.oct1_pad_location import oct1_open_moment_pad_waived

        location_ok = False
        if side == "PUT":
            from app.engines.put_slide_ce_mirror import put_slide_pad_context

            location_ok = put_slide_pad_context(evidence, settings=s)
        if not location_ok:
            location_ok = bool(oct1_open_moment_pad_waived(side, evidence, settings=s)[0])
        if not location_ok:
            try:
                from app.engines.session_timing import in_open_premium_window

                if not in_open_premium_window():
                    return False
            except Exception:
                return False

    if local <= 0 and session_pad:
        local = min_move

    if local > 0 and local < min_move - 1e-6:
        return False
    if local > max_move + 1e-6 and not session_pad:
        return False
    if local > max_move + 1e-6 and session_pad:
        session_cap = float(
            getattr(s, "oct_paper_first_lift_small_lift_session_expansion_max_local_pct", 55.0)
            or 55.0
        )
        try:
            from app.engines.session_timing import in_open_premium_window

            if in_open_premium_window():
                open_cap = float(
                    getattr(s, "oct_paper_open_moment_max_local_pct", 70.0) or 70.0
                )
                session_cap = max(session_cap, open_cap)
        except Exception:
            pass
        if local > session_cap + 1e-6:
            return False

    try:
        from app.engines.session_timing import in_open_premium_window

        if in_open_premium_window() and session_pad and launch:
            score = _parity_number(
                evidence.get("explosionScore") or evidence.get("score")
            )
            min_score = float(getattr(s, "aggressive_min_explosion_score", 45.0) or 45.0)
            if score >= min_score - 1e-6:
                if str(evidence.get("moneyness") or "").upper() != "OTM":
                    return True
    except Exception:
        pass

    if str(evidence.get("moneyness") or "").upper() == "OTM":
        steps = _parity_number(evidence.get("strikeStepsFromAtm"))
        max_steps = int(
            getattr(s, "oct_paper_first_lift_small_lift_max_strike_steps", 3) or 3
        )
        if steps <= 0 or steps > max_steps + 1e-6:
            return False

    return True


def oct_paper_first_lift_otm_entry_ok(
    alert: Mapping[str, Any] | None,
    *,
    depth_steps: int,
    settings: Any = None,
) -> bool:
    """Oct 1 paper: ELITE first-lift / armed-base OTM (≤N steps) any session — not open-window only."""
    from app.config import get_settings

    s = settings or get_settings()
    if not oct_paper_structural_entry_waivers_active(s):
        return False
    if not isinstance(alert, dict):
        return False
    if not oct_paper_structural_pad_context(alert, settings=s):
        return False
    max_steps = int(
        getattr(s, "oct_paper_first_lift_small_lift_max_strike_steps", 3) or 3
    )
    return int(depth_steps or 0) > 0 and int(depth_steps) <= max_steps


def oct_paper_first_lift_entry_window_lo_relax(
    alert: Mapping[str, Any] | None,
    *,
    default_lo: float,
    settings: Any = None,
    readiness_reason: str = "",
) -> float:
    """Oct 1 paper: first-lift at pad uses small-lift floor (e.g. 2%), not 15% entry window."""
    from app.config import get_settings

    s = settings or get_settings()
    if not oct_paper_structural_entry_waivers_active(s):
        return default_lo
    if not isinstance(alert, dict):
        return default_lo
    if not oct_paper_first_lift_small_lift_context(
        alert,
        settings=s,
        readiness_reason=readiness_reason,
    ):
        return default_lo
    floor = float(
        getattr(s, "oct_paper_first_lift_small_lift_min_local_pct", 2.0) or 2.0
    )
    return min(default_lo, floor) if floor > 0 else default_lo


def oct_paper_elite_rip_context(
    evidence: Mapping[str, Any] | None,
    *,
    settings: Any = None,
) -> bool:
    """
    Oct 1 paper: ELITE/EXPLODING at armed-base / v-rip / first-lift may keep negative v3.

    Matches EOD replay — micro-pullback and pad-lane flat coil still apply; random cold
    negative velocity without launch context stays rejected.
    """
    from app.config import get_settings

    s = settings or get_settings()
    if not oct_paper_structural_entry_waivers_active(s):
        return False
    if not isinstance(evidence, dict):
        return False
    tier = str(evidence.get("tier") or evidence.get("signalTier") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False
    score = _parity_number(evidence.get("explosionScore") or evidence.get("score"))
    min_score = float(getattr(s, "aggressive_min_explosion_score", 45.0) or 45.0)
    if score < min_score - 1e-6:
        return False
    armed_launch = bool(evidence.get("armedBaseLaunch") or evidence.get("ictArmedBaseLaunch"))
    elite_base_ready = bool(
        evidence.get("eliteBaseReady") or evidence.get("ictEliteBaseReady")
    )
    v_rip_ready = bool(
        evidence.get("vRipReady")
        or evidence.get("ictVRipReady")
        or "v_rip" in str(evidence.get("momentType") or "").lower()
    )
    building_rip_ready = bool(
        evidence.get("buildingRipReady") or evidence.get("ictBuildingRipReady")
    )
    flat_vertical = bool(
        evidence.get("flatThenVertical") or evidence.get("ictFlatThenVertical")
    )
    first_lift = bool(evidence.get("firstLift") or evidence.get("ictFirstLift"))
    from app.engines.open_rip_selector import open_rip_elite_structural_evidence

    structural = (
        armed_launch
        or elite_base_ready
        or v_rip_ready
        or building_rip_ready
        or flat_vertical
        or first_lift
        or open_rip_elite_structural_evidence(evidence)
    )
    if not structural:
        return False
    try:
        from app.engines.session_timing import in_open_premium_window

        if in_open_premium_window():
            return True
    except Exception:
        return True

    # After 09:45: same pad policy as #721/#722 first-lift (all session), not a separate chase lane.
    if oct_paper_first_lift_small_lift_context(evidence, settings=s):
        return True

    side = str(evidence.get("side") or "").upper()
    local = _parity_number(evidence.get("localBaseMovePct"))
    pos = _parity_number(evidence.get("sessionRangePosition"))

    # PUT slide pad + cold v3 (#717) — not CALL off-low semantics.
    if side == "PUT":
        from app.engines.put_slide_ce_mirror import put_slide_pad_context

        if not put_slide_pad_context(evidence, settings=s):
            return False
        max_late = float(
            getattr(s, "put_slide_cold_velocity_max_local_pct", 22.0) or 22.0
        )
        return local <= max_late + 1e-6

    # CALL: #730 small-lift off session low, not extended afternoon chase.
    off_low = _parity_number(evidence.get("offLowMovePct"))
    max_late_local = float(
        getattr(s, "oct_paper_elite_rip_max_local_outside_open_pct", 28.0) or 28.0
    )
    if pos > 0.55 + 1e-6:
        return False
    if off_low >= float(getattr(s, "live_paper_parity_min_off_session_low_pct", 6.0) or 6.0) - 1e-6:
        return local <= max_late_local + 1e-6
    return local <= max_late_local + 1e-6


def oct_paper_first_lift_negative_velocity_ok(
    evidence: Mapping[str, Any] | None,
    *,
    live_v3: float,
    v9: float = 0.0,
    settings: Any = None,
) -> bool:
    """
    Oct 1 / Oct 5 paper: ELITE open rip at pad may pass readiness while 3s velocity is negative.

    Matches ``rank_trade_evidence`` + EOD replay — not a blanket cold-tick waiver.
    """
    from app.config import get_settings

    s = settings or get_settings()
    if not bool(
        getattr(s, "oct_paper_first_lift_negative_velocity_waiver_enabled", True)
    ):
        return False
    if not oct_paper_structural_entry_waivers_active(s):
        return False
    if not isinstance(evidence, dict):
        return False
    if live_v3 >= -1e-9:
        return True
    if oct_paper_elite_rip_context(evidence, settings=s):
        return True
    from app.engines.pad_lane_capture import pad_lane_cold_velocity_ok

    if pad_lane_cold_velocity_ok(evidence, live_v3, v9):
        return True
    side = str(evidence.get("side") or "").upper()
    if side == "PUT":
        from app.engines.put_slide_ce_mirror import put_slide_cold_velocity_ok

        if put_slide_cold_velocity_ok(evidence, live_v3, v9):
            return True
    return False


def oct_paper_structural_pad_context(
    evidence: Mapping[str, Any] | None,
    *,
    settings: Any = None,
    readiness_reason: str = "",
) -> bool:
    """Oct 1/5 pad entry — first-lift small lift (#734) or structural elite rip (#730)."""
    if not isinstance(evidence, dict):
        return False
    return oct_paper_first_lift_small_lift_context(
        evidence,
        settings=settings,
        readiness_reason=readiness_reason,
    ) or oct_paper_elite_rip_context(evidence, settings=settings)


def structural_pad_entry_lane_active(
    evidence: Mapping[str, Any] | None,
    *,
    settings: Any = None,
    readiness_reason: str = "",
) -> bool:
    """
    Pad / mid-rip entry lane under Frozen Oct — not extended session chase.

    CE: rally off low or local-base pad band. PE: slide pad (put_slide mirror).
    Includes flip V/FTV structural moments when tier/score qualify.
    """
    from app.config import get_settings

    s = settings or get_settings()
    if not oct_paper_structural_entry_waivers_active(s):
        return False
    if not bool(getattr(s, "structural_pad_entry_lane_enabled", True)):
        return False
    if not isinstance(evidence, dict):
        return False
    rr = str(
        readiness_reason
        or evidence.get("firstLiftReadinessReason")
        or evidence.get("ictBaseReadinessReason")
        or ""
    )
    if oct_paper_structural_pad_context(evidence, settings=s, readiness_reason=rr):
        return True
    from app.engines.chop_worst_flip_capture import flip_structural_evidence

    if not flip_structural_evidence(evidence, readiness_reason=rr):
        return False
    tier = str(evidence.get("tier") or evidence.get("signalTier") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False
    score = _parity_number(evidence.get("explosionScore") or evidence.get("score"))
    min_score = float(getattr(s, "aggressive_min_explosion_score", 45.0) or 45.0)
    if score < min_score - 1e-6:
        return False
    side = str(evidence.get("side") or "").upper()
    if side == "PUT":
        from app.engines.put_slide_ce_mirror import put_slide_pad_context

        return put_slide_pad_context(evidence, settings=s)
    if side == "CALL":
        off_low = _parity_number(evidence.get("offLowMovePct"))
        min_off = float(
            getattr(s, "live_paper_parity_min_off_session_low_pct", 6.0) or 6.0
        )
        local = _parity_number(evidence.get("localBaseMovePct"))
        min_local = float(
            getattr(s, "oct_paper_first_lift_small_lift_min_local_pct", 2.0) or 2.0
        )
        max_local = float(
            getattr(s, "oct_paper_first_lift_small_lift_max_local_pct", 40.0) or 40.0
        )
        location_ok = (off_low >= min_off - 1e-6) or (
            min_local <= local <= max_local + 1e-6
        )
        if not location_ok:
            return False
        from app.engines.oct1_pad_location import oct1_premium_location_chase_core

        pos_raw = evidence.get("sessionRangePosition")
        if pos_raw is None or str(pos_raw).strip() == "":
            return False
        pos = _parity_number(pos_raw)
        dd = _parity_number(evidence.get("drawdownFromHighPct"))
        dd_present = (
            evidence.get("drawdownFromHighPct") is not None
            and str(evidence.get("drawdownFromHighPct")).strip() != ""
        )
        chase_blocked, _chase_reason = oct1_premium_location_chase_core(
            side,
            pos,
            dd,
            evidence,
            settings=s,
            dd_present=dd_present,
        )
        return not chase_blocked
    return False


def oct_paper_replica_elite_funnel_waived(
    evidence: Mapping[str, Any] | None,
    *,
    settings: Any = None,
) -> bool:
    """
    Oct 1 replica — ELITE/EXPLODING radar rows pass post-Oct readiness gates when
    not extended premium chase. Used when pad flags are missing on the alert dict
    but the name is still a top-tier structural candidate.
    """
    s = settings or get_settings()
    if not oct_paper_replica_active(s):
        return False
    if not oct_paper_structural_entry_waivers_active(s):
        return False
    if not isinstance(evidence, dict):
        return False
    tier = str(evidence.get("tier") or evidence.get("signalTier") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False
    score = _parity_number(evidence.get("explosionScore") or evidence.get("score"))
    min_score = float(getattr(s, "aggressive_min_explosion_score", 45.0) or 45.0)
    if score < min_score - 1e-6:
        return False
    pos_raw = evidence.get("sessionRangePosition")
    if pos_raw is None or str(pos_raw).strip() == "":
        return True
    side = str(evidence.get("side") or "").upper()
    pos = _parity_number(pos_raw)
    dd = _parity_number(evidence.get("drawdownFromHighPct"))
    dd_present = (
        evidence.get("drawdownFromHighPct") is not None
        and str(evidence.get("drawdownFromHighPct")).strip() != ""
    )
    from app.engines.oct1_pad_location import oct1_premium_location_chase_core

    chase_blocked, _chase_reason = oct1_premium_location_chase_core(
        side,
        pos,
        dd,
        evidence,
        settings=s,
        dd_present=dd_present,
    )
    return not chase_blocked


def oct_paper_funnel_readiness_waived(
    evidence: Mapping[str, Any] | None,
    *,
    settings: Any = None,
    readiness_reason: str = "",
) -> bool:
    """
    Oct 1 / replica stack — structural pad/first-lift may pass readiness gates
    that post-Oct additions added (mid-rip coil, base-move band, ichimoku, etc.).
    """
    s = settings or get_settings()
    if not oct_paper_structural_entry_waivers_active(s):
        return False
    if not isinstance(evidence, dict):
        return False
    rr = str(
        readiness_reason
        or evidence.get("firstLiftReadinessReason")
        or evidence.get("ictBaseReadinessReason")
        or ""
    )
    if oct_paper_structural_pad_context(evidence, settings=s, readiness_reason=rr):
        return True
    if structural_pad_entry_lane_active(
        evidence, settings=s, readiness_reason=rr,
    ):
        return True
    return oct_paper_replica_elite_funnel_waived(evidence, settings=s)


def oct_paper_exec_strict_bypass(
    alert: Mapping[str, Any] | None,
    *,
    settings: Any = None,
) -> bool:
    """Order-path strict first-lift / premium-fade / MTF — match Oct 1 paper pad fills."""
    from app.config import get_settings

    s = settings or get_settings()
    if not oct_paper_structural_entry_waivers_active(s):
        return False
    if not bool(getattr(s, "oct_paper_exec_strict_bypass_enabled", True)):
        return False
    return oct_paper_structural_pad_context(alert, settings=s)


def oct_paper_first_lift_entry_window_hi_relax(
    alert: Mapping[str, Any] | None,
    *,
    default_hi: float,
    settings: Any = None,
) -> float:
    """Oct 1 paper: first-lift at pad may sit above default 65% window when still expanding."""
    from app.config import get_settings

    s = settings or get_settings()
    if not oct_paper_structural_entry_waivers_active(s):
        return default_hi
    if not isinstance(alert, dict):
        return default_hi
    if not oct_paper_first_lift_small_lift_context(alert, settings=s):
        return default_hi
    cap = float(
        getattr(s, "oct_paper_first_lift_small_lift_session_expansion_max_local_pct", 55.0)
        or 55.0
    )
    try:
        from app.engines.session_timing import in_open_premium_window

        if in_open_premium_window():
            cap = max(
                cap,
                float(getattr(s, "oct_paper_open_moment_max_local_pct", 70.0) or 70.0),
            )
    except Exception:
        pass
    return max(default_hi, cap)


def oct_paper_same_side_reentry_after_loss_waived(
    *,
    prior_loss_trade: Any,
    strike: float,
    alert: Mapping[str, Any] | None,
    settings: Any = None,
) -> bool:
    """Oct 5 afternoon vertical — new strike same side after loss if structural pad rip."""
    from app.config import get_settings

    s = settings or get_settings()
    if not oct_paper_entry_loosening_active(s):
        return False
    if not bool(getattr(s, "oct_paper_same_side_reentry_waiver_enabled", True)):
        return False
    if prior_loss_trade is None:
        return False
    try:
        prior_strike = float(getattr(prior_loss_trade, "strike", 0) or 0)
    except (TypeError, ValueError):
        prior_strike = 0.0
    if prior_strike > 0 and abs(prior_strike - float(strike or 0)) < 1e-6:
        return False
    return oct_paper_structural_pad_context(alert, settings=s)


def oct_paper_peak_keep_exit_parity_active(settings: Any | None = None) -> bool:
    """When true, skip implicit stage-trail ladder on first-lift legs (Oct 1 peak-keep holds)."""
    from app.config import get_settings

    s = settings or get_settings()
    if not trading_rules_match_paper(s):
        return False
    return bool(getattr(s, "oct_paper_peak_keep_exit_parity_enabled", True))


def _strict_bool(value: Any, default: bool = False) -> bool:
    """Only real bools count — MagicMock attrs must not flip parity on in tests."""
    if isinstance(value, bool):
        return value
    return default


def live_paper_parity_active(settings: Any | None = None) -> bool:
    from app.config import get_settings

    s = settings or get_settings()
    return _strict_bool(getattr(s, "live_paper_parity_enabled", False)) or _strict_bool(
        getattr(s, "live_trade_selection_parity_with_paper", False)
    )


def entry_gates_match_paper(settings: Any | None = None) -> bool:
    """True when live entry/selection gates should match paper (parity flags or Frozen Oct live)."""
    from app.config import get_settings

    s = settings or get_settings()
    if live_paper_parity_active(s):
        return True
    return (
        _strict_bool(getattr(s, "october_frozen_profile_enabled", False))
        and _strict_bool(getattr(s, "enable_live_trading", False))
        and _strict_bool(getattr(s, "auto_trading_enabled", False))
    )


def trading_rules_match_paper(settings: Any | None = None) -> bool:
    """
    Frozen Oct / parity rule stack — live with entry_gates_match_paper, or paper with same profile.

    Use for sizing book, selection helpers, and live-only exit narrowings that paper skips.
    Also skips live-only entry/session narrowings (chop-live wire, whipsaw pause, power-hour
    top-only session block, expiry worst-day declining halt) so live matches Oct 1 paper.
    Does not simulate broker fills (execution still differs on live).
    """
    from app.config import get_settings

    s = settings or get_settings()
    if not _strict_bool(getattr(s, "enable_live_trading", False)):
        return live_paper_parity_active(s) or _strict_bool(
            getattr(s, "october_frozen_profile_enabled", False)
        )
    return entry_gates_match_paper(s)


def oct_paper_replica_active(settings: Any | None = None) -> bool:
    """
    Oct 1 / Oct 5 paper replica — radar, selection and entry as those sessions ran.

    Turns off post-Oct 5 entry loosenings (#718+ parity waivers), the pad guard
    (#699/#701/#707), the ₹18–350 radar scan band (#714) and strict ATM/ITM-only
    execution (#692). Skips live-only session gates (#719) like Oct 1/5 paper.
    Exits (peak-keep, adaptive SL, N×/k× fast fade) stay current.
    """
    from app.config import get_settings

    s = settings or get_settings()
    return _strict_bool(getattr(s, "oct_paper_replica_enabled", False))


def oct_paper_entry_loosening_active(settings: Any | None = None) -> bool:
    """
    Post-Oct 5 entry/selection waivers keyed off trading_rules_match_paper.

    False under the Oct paper replica — use ``oct_paper_skip_live_only_session_gates``
    for Oct 1/5 session parity and ``oct_paper_structural_entry_waivers_active`` for
    first-lift / pad lane. Exit and sizing paths keep using trading_rules_match_paper.
    """
    from app.config import get_settings

    s = settings or get_settings()
    if oct_paper_replica_active(s):
        return False
    return trading_rules_match_paper(s)


def oct_paper_structural_entry_waivers_active(settings: Any | None = None) -> bool:
    """
    Oct 1 first-lift / elite-rip / structural pad entry waivers (Frozen October stack).

    Stays on under ``oct_paper_replica`` — replica only disables *post-Oct 5* loosening
    (``oct_paper_entry_loosening_active``), not pad-lane first-lift detection.
    """
    from app.config import get_settings

    s = settings or get_settings()
    return trading_rules_match_paper(s)


def oct_paper_skip_live_only_session_gates(settings: Any | None = None) -> bool:
    """
    Oct 1 / Oct 5 paper — skip live-only session/selector narrowings (#718 / #719).

    When true: no chop-live wire, whipsaw pause, power-hour top-only halt, expiry
    worst-day declining halt, or live-entry-score gate. Matches paper on those days;
    anti-chase guards (vertical chase, pad location, post-win mirror chase) stay on.

    True under ``oct_paper_replica`` or ``oct_paper_entry_loosening_active``.
    """
    from app.config import get_settings

    s = settings or get_settings()
    if oct_paper_replica_active(s):
        return True
    return oct_paper_entry_loosening_active(s)


def legacy_live_entry_narrowings_active(settings: Any | None = None) -> bool:
    """
    True when live-only entry/session narrowings may run (legacy stack or live without paper rules).

    Prefer this over bare ``enable_live_trading`` for rule forks — Oct mirror live keeps this false.
    """
    from app.config import get_settings

    s = settings or get_settings()
    if not _strict_bool(getattr(s, "enable_live_trading", False)):
        return False
    return not trading_rules_match_paper(s)


def legacy_live_narrow_stack_active(settings: Any | None = None) -> bool:
    """
    Old ₹10k-style live-only stack (best-trades-only, structural hold, chop-live wire).

    Hard-disabled when Frozen October or paper-mirror rules are active. Opt-in only via
    legacy_live_narrow_stack_enabled (deploy/env.live-10k.overlay).
    """
    from app.config import get_settings

    s = settings or get_settings()
    if not _strict_bool(getattr(s, "enable_live_trading", False)):
        return False
    if trading_rules_match_paper(s):
        return False
    if _strict_bool(getattr(s, "october_frozen_profile_enabled", False)):
        return False
    return _strict_bool(getattr(s, "legacy_live_narrow_stack_enabled", False))


def live_paper_profile_summary(settings: Any | None = None) -> dict[str, Any]:
    """HUD / readiness: Oct 1 / 5 paper stack when live is armed with parity."""
    from app.config import get_settings

    s = settings or get_settings()
    parity = live_paper_parity_active(s)
    gates = entry_gates_match_paper(s)
    rules = trading_rules_match_paper(s)
    loosening = oct_paper_entry_loosening_active(s)
    structural_waivers = oct_paper_structural_entry_waivers_active(s)
    skip_live_session_gates = oct_paper_skip_live_only_session_gates(s)
    cap_inr = float(getattr(s, "fallback_capital_inr", 0) or 0)
    from app.engines.sep917_legacy_profile import (
        atm_itm_fixed_premium_band_only,
        strict_atm_itm_execution,
    )

    return {
        "active": parity,
        "entryGatesMatchPaper": gates,
        "tradingRulesMatchPaper": rules,
        "octPaperReplica": {
            "enabled": oct_paper_replica_active(s),
            "postOct5EntryLooseningActive": loosening,
            "structuralEntryWaiversActive": structural_waivers,
            "skipLiveOnlySessionGates": skip_live_session_gates,
            "radarFixedPremiumBandOnly": atm_itm_fixed_premium_band_only(s),
            "strictAtmItmExecution": strict_atm_itm_execution(s),
            "padEntryGuardEnabled": bool(
                getattr(s, "live_paper_parity_pad_entry_guard_enabled", True)
            ),
        },
        "bookMatchesOctPaperReferenceLots": cap_inr
        >= float(getattr(s, "oct_paper_reference_capital_inr", 149_000.0) or 149_000.0),
        "legacyLiveNarrowStackActive": legacy_live_narrow_stack_active(s),
        "liveBestTradesOnlyEnabled": bool(getattr(s, "live_best_trades_only_enabled", True)),
        "worstDayBlocksLive": bool(getattr(s, "worst_day_blocks_live", True)),
        "liveHoldToStructuralSl": bool(getattr(s, "live_hold_to_structural_sl", False)),
        "useUpstoxCapitalForSizing": bool(getattr(s, "use_upstox_capital_for_sizing", False)),
        "sizesFromPaperBook": (
            gates
            and not should_use_live_broker_capital_for_summary(s)
            and cap_inr
            >= float(getattr(s, "oct_paper_reference_capital_inr", 149_000.0) or 149_000.0)
        ),
        "octPaperBehaviorParity": {
            "negativeVelocityWaiver": bool(
                getattr(s, "oct_paper_first_lift_negative_velocity_waiver_enabled", True)
            )
            and structural_waivers,
            "peakKeepExitParity": oct_paper_peak_keep_exit_parity_active(s),
            "execStrictBypass": bool(
                getattr(s, "oct_paper_exec_strict_bypass_enabled", True)
            )
            and structural_waivers,
            "structuralPadSelectorWaivers": structural_waivers,
            "otmTradeablePreserveOnStamp": structural_waivers,
        },
        "parityHudNote": (
            "entryGatesMatchPaper means parity env flags — not Oct 1 lot-for-lot replay. "
            "See octPaperBehaviorParity and bookMatchesOctPaperReferenceLots."
        ),
        "sep917LegacyProfileEnabled": bool(getattr(s, "sep917_legacy_profile_enabled", True)),
        "topMomentsOnlyEnabled": bool(getattr(s, "top_moments_only_enabled", False)),
        "paperSimpleProfitMode": bool(getattr(s, "paper_simple_profit_mode", False)),
        "adaptiveExitsEnabled": bool(getattr(s, "adaptive_exits_enabled", True)),
        "executedEntrySlOnlyLossExits": bool(
            getattr(s, "executed_entry_sl_only_loss_exits", True)
        ),
        "fallbackCapitalInr": float(getattr(s, "fallback_capital_inr", 0) or 0),
        "maxSizingCapitalInr": float(getattr(s, "max_sizing_capital_inr", 0) or 0),
        "padEntryGuardEnabled": bool(
            getattr(s, "live_paper_parity_pad_entry_guard_enabled", True)
        ),
        "padEntryMaxSessionRangePosition": float(
            getattr(s, "live_paper_parity_max_session_range_position", 0.52) or 0.52
        ),
    }


def should_use_live_broker_capital_for_summary(settings: Any) -> bool:
    """Avoid import cycle with capital_allocator in summary-only callers."""
    from app.engines.capital_allocator import should_use_live_broker_capital

    if entry_gates_match_paper(settings):
        return should_use_live_broker_capital()
    if not _strict_bool(getattr(settings, "enable_live_trading", False)):
        return False
    return bool(
        getattr(settings, "use_upstox_capital_for_sizing", False)
        and getattr(settings, "enable_live_trading", False)
    )


# Minimum sizing book for parity go-live (deploy/env.live-150k.overlay and env.live-200k.overlay).
_LIVE_PAPER_PROFILE_MIN_CAPITAL_INR = 149_000.0
# Frozen October small live book (deploy/env.live-50k.overlay).
_FROZEN_OCT_SMALL_BOOK_MIN_CAPITAL_INR = 45_000.0


def live_paper_profile_ok(settings: Any | None = None) -> tuple[bool, list[str]]:
    """True when env matches deploy/env.live-150k or env.live-200k overlay (Oct paper profile)."""
    from app.config import get_settings

    s = settings or get_settings()
    if not live_paper_parity_active(s):
        return False, ["live_paper_parity_disabled"]
    issues: list[str] = []
    if bool(getattr(s, "live_best_trades_only_enabled", True)):
        issues.append("live_best_trades_only_still_enabled")
    if bool(getattr(s, "worst_day_blocks_live", True)):
        issues.append("worst_day_blocks_live_still_enabled")
    if bool(getattr(s, "live_hold_to_structural_sl", False)):
        issues.append("live_hold_to_structural_sl_still_enabled")
    if bool(getattr(s, "sep917_live_checklist_enforcement_enabled", False)):
        issues.append("sep917_live_checklist_enforcement_enabled")
    if not bool(getattr(s, "sep917_legacy_profile_enabled", True)):
        issues.append("sep917_legacy_profile_disabled")
    cap = float(getattr(s, "fallback_capital_inr", 0) or 0)
    min_cap = _LIVE_PAPER_PROFILE_MIN_CAPITAL_INR
    if _strict_bool(getattr(s, "october_frozen_profile_enabled", False)):
        min_cap = _FROZEN_OCT_SMALL_BOOK_MIN_CAPITAL_INR
    if cap < min_cap:
        issues.append("fallback_capital_below_parity_min")
    if should_use_live_broker_capital_for_summary(s):
        issues.append("sizing_from_upstox_margin_not_paper_book")
    return (len(issues) == 0, issues)
