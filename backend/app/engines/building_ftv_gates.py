"""Shared BUILDING / FTV readiness helpers for entry gates."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import get_settings

BUILDING_READY_REASONS = frozenset(
    {
        "building_rip_bullish_ready",
        "building_local_base_lift_ready",
        "building_first_lift_ready",
        "building_first_lift_preauthorized",
    }
)

PAD_LANE_READY_REASONS = frozenset(
    {
        "slow_grind_sudden_lift_ready",
        "slow_grind_armed_trough_ready",
        "slow_grind_consolidation_base_ready",
        "fast_bullish_local_base_ready",
        "v_rip_session_low_ready",
        "squeeze_release_ready",
        "index_led_option_lag_ready",
        "stealth_cvd_coil_ready",
        "micro_pullback_retest_ready",
        "premium_fvg_pad_ready",
        "double_dip_vbase_ready",
        "early_radar_pad_ready",
        "building_coil_pad_ready",
        # Early base-entry lanes (enabled): let a BUILDING coil/ignition through the
        # elite-only tier gate when its lane fires — otherwise these lanes only take effect
        # once the contract is already ELITE/EXPLODING, which defeats catching it while it is
        # still slow/building. Each lane already carries its own quality/score dud filter.
        "coil_armed_low_score_base_entry",
        "early_momentum_ignition_at_base",
    }
)

ARMED_BASE_GRADE_A_READY_REASONS = frozenset(
    {"armed_base_option_led_ready", "building_armed_prelaunch_ready"}
)


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _building_armed_base_worst_day_waived(alert: dict[str, Any]) -> bool:
    """Local-base pad on WORST days — Aug28 morning PUT winners."""
    settings = get_settings()
    if not bool(getattr(settings, "building_armed_base_worst_day_waive_enabled", True)):
        return False
    base_rel = _number(
        alert.get("ictBaseRelativeMovePct") or alert.get("localBaseMovePct")
    )
    lo = float(
        getattr(settings, "building_armed_base_worst_day_waive_min_base_rel_pct", 10.0)
        or 10.0
    )
    hi = float(
        getattr(settings, "building_armed_base_worst_day_waive_max_base_rel_pct", 25.0)
        or 25.0
    )
    vol = _number(alert.get("volumeSurge"))
    min_vol = float(
        getattr(settings, "building_armed_base_worst_day_waive_min_volume_surge", 2.0)
        or 2.0
    )
    return (
        lo <= base_rel <= hi + 1e-6
        and vol >= min_vol
        and bool(alert.get("ictBaseArmed"))
    )


def _building_coil_pad_worst_day_waived(alert: dict[str, Any]) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "building_coil_pad_worst_day_waive_enabled", True)):
        return False
    from app.engines.early_radar_pad_capture import building_coil_pad_lift_signal

    if not building_coil_pad_lift_signal(alert, settings):
        return False
    base_rel = _number(
        alert.get("ictBaseRelativeMovePct") or alert.get("localBaseMovePct")
    )
    lo = float(
        getattr(settings, "building_coil_pad_min_local_move_pct", 10.0) or 10.0
    )
    hi = float(
        getattr(settings, "building_coil_pad_max_local_move_pct", 25.0) or 25.0
    )
    vol_awake = bool(
        alert.get("volumeAwaken")
        or alert.get("ictVolumeAwakening")
        or _number(alert.get("volumeSurge")) >= 1.0
    )
    return lo <= base_rel <= hi + 1e-6 and vol_awake and bool(alert.get("ictBaseArmed"))


def _building_armed_base_worst_day_blocked(
    *,
    state: Any = None,
    snapshots: Optional[dict[str, Any]] = None,
) -> bool:
    """Block BUILDING armed-base on DEFENSIVE / BREAKOUT_ONLY / PAUSED sessions."""
    settings = get_settings()
    if not bool(getattr(settings, "worst_day_block_building_ict", True)):
        return False
    try:
        from app.engines.worst_day_itm_fade import worst_day_defensive_session_active
        from app.engines.worst_day_guard import session_entry_policy
        from app.engines.dual_mode_strategy import resolve_trading_session_mode
        from app.models.schemas import AutoTraderState as _ATS

        snaps = snapshots or {}
        st = state if state is not None else _ATS()
        if snaps:
            if worst_day_defensive_session_active(st, snaps):
                return True
            policy, _ = session_entry_policy(st, snaps)
            if policy in ("BREAKOUT_ONLY", "PAUSED"):
                return True
            mode, _ = resolve_trading_session_mode(st, snaps)
            if mode == "DEFENSIVE":
                return True
    except Exception:
        return True
    return False


def building_armed_base_grade_a_live_ok(
    alert: Optional[dict[str, Any]],
    snap: Any = None,
    *,
    readiness_reason: str = "",
    ranking: Optional[dict[str, Any]] = None,
    state: Any = None,
    snapshots: Optional[dict[str, Any]] = None,
) -> bool:
    """Allow grade-A BUILDING through live selector when option-led armed base is ready.

    Aug28 NIFTY PUT 24200/24100: armed_base_option_led_ready + grade A at ~10–15%
    baseRel blocked by tier_not_elite_exploding until EXPLODING ~11:20. Archive week
    (Aug24–28): in-window BUILDING grade-A early paths ~75% MFE winners, 3/40 false starts.
    """
    settings = get_settings()
    if not bool(getattr(settings, "building_armed_base_grade_a_live_enabled", True)):
        return False
    if not isinstance(alert, dict):
        return False
    tier = str(alert.get("tier") or "").upper()
    if tier not in ("BUILDING", "WATCH"):
        return False
    if tier == "WATCH":
        from app.engines.early_radar_pad_capture import building_armed_prelaunch_pad_lane

        if not building_armed_prelaunch_pad_lane(alert, settings):
            return False
    rr = str(
        readiness_reason
        or alert.get("ictBaseReadinessReason")
        or alert.get("readyReason")
        or ""
    )
    if rr not in ARMED_BASE_GRADE_A_READY_REASONS:
        return False
    if _building_armed_base_worst_day_blocked(state=state, snapshots=snapshots):
        if not (
            isinstance(alert, dict)
            and (
                _building_armed_base_worst_day_waived(alert)
                or _building_coil_pad_worst_day_waived(alert)
            )
        ):
            return False
    base_rel = _number(
        alert.get("ictBaseRelativeMovePct") or alert.get("localBaseMovePct")
    )
    grade = ""
    if isinstance(ranking, dict):
        grade = str(ranking.get("grade") or "").upper()
    if not grade:
        try:
            from app.engines.trade_ranking import rank_trade_evidence

            evidence = {
                "mode": "explosion",
                "tier": str(alert.get("tier") or "").upper(),
                "explosionScore": _number(
                    alert.get("explosionScore") or alert.get("score")
                ),
                "tqs": _number(getattr(snap, "tradeQualityScore", 0) if snap else 0),
                "velocity3s": _number(alert.get("velocity3s")),
                "velocity9s": _number(alert.get("velocity9s")),
                "localBaseMovePct": base_rel,
                "flatThenVertical": bool(alert.get("ictFlatThenVertical")),
                "activeBreakout": bool(alert.get("ictBreakout")),
                "armedBaseLaunch": bool(
                    alert.get("ictArmedBaseLaunch") or alert.get("ictBaseArmed")
                ),
                "firstLift": bool(alert.get("ictFirstLift")),
                "vRipReady": bool(alert.get("ictVRipReady")),
                "buildingRipReady": bool(alert.get("ictBuildingRipReady")),
                "orderflowPositive": bool(
                    alert.get("volumeAwaken")
                    or alert.get("ictVolumeAwakening")
                    or alert.get("optionCvdBuying")
                ),
            }
            ranking = rank_trade_evidence(evidence)
            grade = str(ranking.get("grade") or "").upper()
        except Exception:
            grade = ""
    min_grade = str(
        getattr(settings, "building_armed_base_grade_a_min_grade", "B") or "B"
    ).upper()
    if tier == "WATCH":
        min_grade = str(
            getattr(settings, "building_armed_prelaunch_min_grade", "C") or "C"
        ).upper()
    grade_order = {"S": 4, "A": 3, "B": 2, "C": 1, "REJECT": 0}
    if grade_order.get(grade, 0) < grade_order.get(min_grade, 2):
        return False
    vol = _number(alert.get("volumeSurge"))
    from app.engines.local_base_chart_bypass import local_base_entry_window

    if tier == "WATCH":
        entry_min = float(
            getattr(settings, "building_armed_prelaunch_min_base_rel_pct", 5.0) or 5.0
        )
        chase_max = float(
            getattr(settings, "building_armed_prelaunch_max_base_rel_pct", 18.0) or 18.0
        )
    else:
        entry_min = float(
            getattr(settings, "ict_armed_base_launch_min_move_pct", 5.0) or 5.0
        )
        chase_max = float(
            getattr(settings, "ict_armed_base_launch_max_move_pct", 15.0) or 15.0
        )
        if bool(getattr(settings, "building_armed_base_grade_a_use_local_base_window", True)):
            lb_min, lb_max = local_base_entry_window("BUILDING", vol)
            entry_min = min(entry_min, lb_min)
            chase_max = max(chase_max, lb_max)
        max_rel = float(
            getattr(settings, "building_armed_base_grade_a_max_base_rel_pct", 0.0) or 0.0
        )
        if max_rel > 0:
            chase_max = min(chase_max, max_rel)
    if base_rel <= 0 or not (entry_min <= base_rel <= chase_max):
        return False
    return True


def building_armed_base_grade_a_top_moment_ok(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    *,
    readiness_reason: str = "",
) -> bool:
    """Top-moment gate companion — FTV moment for grade-A BUILDING armed-base live."""
    alert_like = {
        "tier": evidence.get("tier"),
        "ictBaseRelativeMovePct": evidence.get("localBaseMovePct"),
        "localBaseMovePct": evidence.get("localBaseMovePct"),
        "volumeSurge": evidence.get("volumeSurge"),
        "explosionScore": evidence.get("explosionScore"),
        "ictBaseArmed": bool(
            evidence.get("ictBaseArmed") or evidence.get("baseArmed")
        ),
        "volumeAwaken": bool(
            evidence.get("volumeAwaken") or evidence.get("ictVolumeAwakening")
        ),
        "ictBaseReadinessReason": readiness_reason
        or evidence.get("ictBaseReadinessReason")
        or evidence.get("firstLiftReadinessReason"),
    }
    return building_armed_base_grade_a_live_ok(
        alert_like,
        readiness_reason=readiness_reason,
        ranking=dict(ranking),
    )

def building_coil_pad_grade_a_live_ok(
    alert: Optional[dict[str, Any]],
    snap: Any = None,
    *,
    readiness_reason: str = "",
    ranking: Optional[dict[str, Any]] = None,
    state: Any = None,
    snapshots: Optional[dict[str, Any]] = None,
) -> bool:
    """Allow grade-A BUILDING coil pad (10–25% local base) through live selector."""
    settings = get_settings()
    if not bool(getattr(settings, "building_coil_pad_entry_enabled", True)):
        return False
    if not isinstance(alert, dict):
        return False
    if str(alert.get("tier") or "").upper() != "BUILDING":
        return False
    rr = str(
        readiness_reason
        or alert.get("ictBaseReadinessReason")
        or alert.get("readyReason")
        or ""
    )
    from app.engines.early_radar_pad_capture import (
        BUILDING_COIL_PAD_READY,
        alert_has_building_coil_pad,
    )

    if rr != BUILDING_COIL_PAD_READY and not alert_has_building_coil_pad(alert):
        return False
    if _building_armed_base_worst_day_blocked(state=state, snapshots=snapshots):
        if not (
            isinstance(alert, dict)
            and (
                _building_armed_base_worst_day_waived(alert)
                or _building_coil_pad_worst_day_waived(alert)
            )
        ):
            return False
    local_move = _number(
        alert.get("ictBaseRelativeMovePct") or alert.get("localBaseMovePct")
    )
    min_local = float(
        getattr(settings, "building_coil_pad_min_local_move_pct", 10.0) or 10.0
    )
    max_local = float(
        getattr(settings, "building_coil_pad_max_local_move_pct", 25.0) or 25.0
    )
    if local_move <= 0 or not (min_local <= local_move <= max_local + 1e-6):
        return False
    grade = ""
    if isinstance(ranking, dict):
        grade = str(ranking.get("grade") or "").upper()
    if not grade:
        try:
            from app.engines.trade_ranking import rank_trade_evidence

            evidence = {
                "mode": "explosion",
                "tier": "BUILDING",
                "localBaseMovePct": local_move,
                "velocity3s": _number(alert.get("velocity3s")),
                "velocity9s": _number(alert.get("velocity9s")),
                "buildingCoilPad": True,
                "volumeAwaken": bool(
                    alert.get("volumeAwaken") or alert.get("ictVolumeAwakening")
                ),
                "explosionScore": _number(
                    alert.get("explosionScore") or alert.get("score")
                ),
            }
            grade = str(rank_trade_evidence(evidence).get("grade") or "").upper()
        except Exception:
            grade = ""
    min_grade = str(
        getattr(settings, "building_coil_pad_min_grade", "B") or "B"
    ).upper()
    if bool(getattr(settings, "building_coil_pad_floor_grade_enabled", True)):
        vol_awake = bool(
            alert.get("volumeAwaken")
            or alert.get("ictVolumeAwakening")
            or _number(alert.get("volumeSurge")) >= 1.0
        )
        if (
            (rr == BUILDING_COIL_PAD_READY or bool(alert.get("buildingCoilPadReady")))
            and vol_awake
            and grade == "C"
        ):
            grade = "B"
    grade_order = {"S": 4, "A": 3, "B": 2, "C": 1, "REJECT": 0}
    if grade_order.get(grade, 0) < grade_order.get(min_grade, 2):
        return False
    return True


def building_coil_pad_grade_a_top_moment_ok(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    *,
    readiness_reason: str = "",
) -> bool:
    """Top-moment gate companion — FTV moment for BUILDING coil pad."""
    from app.engines.early_radar_pad_capture import BUILDING_COIL_PAD_READY

    alert_like = {
        "tier": evidence.get("tier"),
        "ictBaseRelativeMovePct": evidence.get("localBaseMovePct"),
        "localBaseMovePct": evidence.get("localBaseMovePct"),
        "buildingCoilPad": evidence.get("buildingCoilPad"),
        "buildingCoilPadReady": bool(
            evidence.get("buildingCoilPad")
            or readiness_reason == BUILDING_COIL_PAD_READY
        ),
        "ictBaseArmed": bool(evidence.get("ictBaseArmed") or evidence.get("armedBaseLaunch")),
        "velocity3s": evidence.get("velocity3s"),
        "velocity9s": evidence.get("velocity9s"),
        "volumeAwaken": bool(
            evidence.get("volumeAwaken") or evidence.get("orderflowPositive")
        ),
        "volumeSurge": evidence.get("volumeSurge"),
        "explosionScore": evidence.get("explosionScore"),
        "ictBaseReadinessReason": readiness_reason
        or evidence.get("firstLiftReadinessReason"),
    }
    return building_coil_pad_grade_a_live_ok(
        alert_like,
        readiness_reason=readiness_reason,
        ranking=dict(ranking),
    )

def alert_has_building_rip_signal(alert: Optional[dict[str, Any]]) -> bool:
    """True when radar stamped a BUILDING rip (including after EXPLODING promote)."""
    if not isinstance(alert, dict):
        return False
    if bool(alert.get("ictBuildingRipReady") or alert.get("buildingRipReady")):
        return True
    if bool(alert.get("buildingLiftHelping") or alert.get("buildingRipHelpersOk")):
        return True
    reason = str(alert.get("reason") or "")
    if "buildingRip" in reason:
        return True
    ready_reason = str(
        alert.get("ictBaseReadinessReason") or alert.get("readyReason") or ""
    )
    return ready_reason in BUILDING_READY_REASONS or ready_reason.startswith(
        "buildingRip"
    )


def building_rip_ready_reason(
    *,
    alert: Optional[dict[str, Any]] = None,
    readiness_reason: str = "",
) -> str:
    rr = str(readiness_reason or "")
    if rr in BUILDING_READY_REASONS or rr.startswith("buildingRip"):
        return rr
    if isinstance(alert, dict):
        stamped = str(alert.get("ictBaseReadinessReason") or "")
        if stamped in BUILDING_READY_REASONS or stamped.startswith("buildingRip"):
            return stamped
    if alert_has_building_rip_signal(alert):
        return "building_rip_bullish_ready"
    return ""


def pad_lane_ready_reason(
    *,
    alert: Optional[dict[str, Any]] = None,
    readiness_reason: str = "",
) -> str:
    rr = str(readiness_reason or "")
    if rr in PAD_LANE_READY_REASONS:
        return rr
    if isinstance(alert, dict):
        stamped = str(alert.get("ictBaseReadinessReason") or "")
        if stamped in PAD_LANE_READY_REASONS:
            return stamped
        if bool(
            alert.get("slowGrindSuddenLiftReady")
            or alert.get("ictSlowGrindSuddenLift")
        ):
            stamped = str(alert.get("ictBaseReadinessReason") or "")
            if stamped == "slow_grind_armed_trough_ready":
                return "slow_grind_armed_trough_ready"
            if stamped == "slow_grind_consolidation_base_ready":
                return "slow_grind_consolidation_base_ready"
            return "slow_grind_sudden_lift_ready"
        if bool(
            alert.get("fastBullishLocalBaseReady")
            or alert.get("bullishLocalBaseActive")
        ):
            return "fast_bullish_local_base_ready"
        if bool(alert.get("squeezeReleaseReady") or alert.get("ictSqueezeRelease")):
            return "squeeze_release_ready"
        if bool(alert.get("indexLedOptionLagReady") or alert.get("ictIndexLedOptionLag")):
            return "index_led_option_lag_ready"
        if bool(alert.get("stealthCvdCoilReady") or alert.get("ictStealthCvdCoil")):
            return "stealth_cvd_coil_ready"
        if bool(alert.get("microPullbackRetestReady") or alert.get("ictMicroPullbackRetest")):
            return "micro_pullback_retest_ready"
        if bool(alert.get("premiumFvgPadReady") or alert.get("ictPremiumFvgPad")):
            return "premium_fvg_pad_ready"
        if bool(alert.get("doubleDipVbaseReady") or alert.get("ictDoubleDipVbase")):
            return "double_dip_vbase_ready"
        if bool(alert.get("earlyRadarPadCapture") or alert.get("ictEarlyRadarPadCapture")):
            return "early_radar_pad_ready"
        if bool(alert.get("buildingCoilPad") or alert.get("buildingCoilPadReady")):
            return "building_coil_pad_ready"
        stamped = str(alert.get("ictBaseReadinessReason") or alert.get("readyReason") or "")
        if bool(alert.get("ictVRipReady") or alert.get("vRipReady")):
            if stamped.startswith("v_rip_session_low") or stamped == "v_rip_session_low_ready":
                return stamped or "v_rip_session_low_ready"
    return ""


def pad_lane_bypasses_fake_trap(
    *,
    alert: Optional[dict[str, Any]] = None,
    readiness_reason: str = "",
    candidate: Any = None,
) -> bool:
    """Selector / pretrade — pad-lane pre-lift takes bypass fake-trap like BUILDING rip."""
    if candidate is not None and not isinstance(alert, dict):
        raw = getattr(candidate, "alert", None)
        alert = raw if isinstance(raw, dict) else None
        meta = getattr(candidate, "pretrade_meta", None) or {}
        if isinstance(meta, dict) and not readiness_reason:
            readiness_reason = str(
                meta.get("ictBaseReadinessReason")
                or meta.get("firstLiftReadinessReason")
                or ""
            )
    return bool(pad_lane_ready_reason(alert=alert, readiness_reason=readiness_reason))


def building_rip_bypasses_fake_trap(
    *,
    alert: Optional[dict[str, Any]] = None,
    readiness_reason: str = "",
    candidate: Any = None,
) -> bool:
    """Selector / pretrade / order path — same soft bypass for helper BUILDING rips."""
    settings = get_settings()
    if not bool(getattr(settings, "building_rip_bypasses_fake_trap", True)):
        return False
    if candidate is not None and not isinstance(alert, dict):
        raw = getattr(candidate, "alert", None)
        alert = raw if isinstance(raw, dict) else None
        meta = getattr(candidate, "pretrade_meta", None) or {}
        if isinstance(meta, dict) and not readiness_reason:
            readiness_reason = str(
                meta.get("ictBaseReadinessReason")
                or meta.get("firstLiftReadinessReason")
                or ""
            )
    return bool(
        building_rip_ready_reason(alert=alert, readiness_reason=readiness_reason)
        or alert_has_building_rip_signal(alert)
        or pad_lane_ready_reason(alert=alert, readiness_reason=readiness_reason)
    )


def top_must_take_bypasses_fake_trap(
    *,
    must_take: bool = False,
    alert: Optional[dict[str, Any]] = None,
    candidate: Any = None,
    snap: Any = None,
) -> bool:
    """Soft bypass for top ELITE/EXPLODING must-take when index helpers confirm.

    Fake-trap still *evaluates* (meta stamps); selector/pretrade may continue.
    Hard counter-trend / DEFENSIVE / mid-rip coil remain enforced elsewhere.
    """
    if not must_take:
        return False
    settings = get_settings()
    if not bool(getattr(settings, "top_must_take_bypasses_fake_trap", True)):
        return False
    if candidate is not None and not isinstance(alert, dict):
        raw = getattr(candidate, "alert", None)
        alert = raw if isinstance(raw, dict) else None
    try:
        from app.engines.index_tick_helpers import (
            evaluate_index_tick_helpers,
            index_helpers_confirm_from_alert,
        )

        if index_helpers_confirm_from_alert(alert):
            return True
        # Always allow must-take soft bypass when setting is on — index helpers
        # are preferred but near-base ATM/ITM ELITE already cleared must-take.
        if bool(
            getattr(settings, "top_must_take_fake_trap_requires_index", False)
        ):
            resolved_snap = snap
            if resolved_snap is None and candidate is not None:
                resolved_snap = getattr(candidate, "snap", None)
            side = ""
            if isinstance(alert, dict):
                side = str(alert.get("side") or "")
            if not side and candidate is not None:
                side = str(getattr(candidate, "side", "") or "")
            if resolved_snap is not None and side:
                idx = evaluate_index_tick_helpers(
                    snap=resolved_snap, side=side, alert=alert,
                )
                return bool(idx.confirming or idx.tick_align)
            return False
        return True
    except Exception:
        return bool(
            not getattr(settings, "top_must_take_fake_trap_requires_index", False)
        )


def building_rip_bypasses_extended_chase(
    *,
    alert: Optional[dict[str, Any]] = None,
    readiness_reason: str = "",
    candidate: Any = None,
) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "building_rip_bypasses_extended_chase", True)):
        return False
    return building_rip_bypasses_fake_trap(
        alert=alert,
        readiness_reason=readiness_reason,
        candidate=candidate,
    ) or pad_lane_bypasses_fake_trap(
        alert=alert,
        readiness_reason=readiness_reason,
        candidate=candidate,
    )
