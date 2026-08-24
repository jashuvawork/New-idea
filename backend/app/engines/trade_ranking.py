"""Comparable causal trade ranking from evidence available before entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


GRADE_PRIORITY = {"REJECT": 0, "C": 1, "B": 2, "A": 3, "S": 4}


@dataclass(frozen=True)
class FtvAuthorization:
    """Causal entry authorization plus its maximum sizing sleeve."""

    mode: str | None
    reason: str
    max_capital_pct: float | None = None
    exceptional_extension: bool = False

    @property
    def allowed(self) -> bool:
        return self.mode is not None


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _first_lift_local_base_micro_pullback(
    evidence: Mapping[str, Any],
    *,
    enabled: bool = True,
    min_velocity_3s: float = -1.2,
    min_velocity_9s: float = -0.5,
    min_local_base_move_pct: float = 2.0,
    max_local_base_move_pct: float = 25.0,
) -> bool:
    """Shallow velocity dip on confirmed first-lift/V-rip at local base."""
    if not enabled:
        return False
    v3 = _number(evidence.get("velocity3s"))
    v9 = _number(evidence.get("velocity9s"))
    if v3 >= 0 and v9 >= 0:
        return False
    if v3 < min_velocity_3s or v9 < min_velocity_9s:
        return False
    move = _number(evidence.get("localBaseMovePct"))
    if not (min_local_base_move_pct <= move <= max_local_base_move_pct):
        return False
    tier = str(evidence.get("tier") or "").upper()
    if tier not in {"ELITE", "EXPLODING"}:
        return False
    if not bool(evidence.get("firstLift") or evidence.get("vRipReady")):
        return False
    if bool(
        evidence.get("midRipCoil")
        or evidence.get("faded")
        or evidence.get("exhaustedReentry")
    ):
        return False
    timing = str(evidence.get("timingAssessment") or "").upper()
    timing_action = str(evidence.get("timingAction") or "").lower()
    if timing_action in {"block", "reject"} or timing in {
        "FAILED_LAUNCH",
        "FADED",
        "FADING",
        "EXHAUSTED",
        "NEGATIVE",
        "REJECT",
        "BLOCKED",
    }:
        return False
    if not bool(evidence.get("flatThenVertical") and evidence.get("activeBreakout")):
        return False
    if not bool(evidence.get("volumeAwaken") or evidence.get("orderflowPositive")):
        return False
    return True


def ranking_sort_key(ranking: Mapping[str, Any]) -> tuple[int, float]:
    """Comparable causal ordering: grade first, then evidence score."""
    return (
        int(_number(ranking.get("gradePriority"))),
        _number(ranking.get("rankScore")),
    )


def resolve_policy_day_mode(state: Any = None, *, day_mode: str = "") -> str:
    """Best-effort dayMode for policy gates (session limits → state → explicit)."""
    if day_mode:
        return str(day_mode)
    try:
        from app.engines.daily_18pct_strategy import get_session_limits

        limits = get_session_limits()
        if limits is not None:
            dm = str(getattr(limits, "dayMode", "") or "")
            if dm:
                return dm
    except Exception:
        pass
    if state is not None:
        for attr in ("dayMode", "day_mode"):
            raw = getattr(state, attr, None)
            if raw:
                return str(raw)
        ds = getattr(state, "dailyStrategy", None) or {}
        if isinstance(ds, dict):
            dm = str(ds.get("dayMode") or "")
            if dm:
                return dm
    return ""


def _day_mode_is_expiry_worst(day_mode: str) -> bool:
    joined = str(day_mode or "").upper()
    if "EXPIRY WORST" in joined:
        return True
    return "EXPIRY" in joined and "WORST" in joined


def _day_mode_is_worst(day_mode: str) -> bool:
    return "WORST" in str(day_mode or "").upper()


def ftv_authorization_policy(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    *,
    snapshot_available: bool = False,
    atm_itm_allowed: bool = True,
    allocation_rank: int | None = None,
    require_allocation_rank_one: bool = False,
    day_mode: str = "",
    top_ftv_a_enabled: bool = True,
    top_ftv_a_min_explosion_score: float = 90.0,
    top_ftv_a_min_quality: float = 70.0,
    top_ftv_a_min_tqs: float = 50.0,
    top_ftv_a_min_velocity_3s: float = 2.5,
    top_ftv_a_min_velocity_9s: float = 1.75,
    top_ftv_a_normal_max_move_pct: float = 25.0,
    top_ftv_a_max_capital_pct: float = 0.90,
    top_ftv_a_exceptional_min_explosion_score: float = 95.0,
    top_ftv_a_exceptional_min_quality: float = 85.0,
    top_ftv_a_exceptional_min_tqs: float = 55.0,
    top_ftv_a_exceptional_min_velocity_3s: float = 5.0,
    top_ftv_a_exceptional_min_velocity_9s: float = 2.5,
    top_ftv_a_exceptional_max_move_pct: float = 40.0,
    top_ftv_a_index_helpers_waive_cvd_accel: bool = True,
    ftv_s_strict_min_explosion_score: float = 85.0,
    ftv_s_strict_min_quality: float = 70.0,
    ftv_s_strict_min_velocity_3s: float = 2.5,
    ftv_s_strict_min_velocity_9s: float = 1.75,
    ftv_s_strict_require_cvd_buying: bool = True,
    ftv_s_strict_min_local_base_move_pct: float = 5.0,
    ftv_s_strict_max_local_base_move_pct: float = 25.0,
    winner_local_base_enabled: bool = True,
    winner_local_base_min_explosion_score: float = 75.0,
    winner_local_base_min_quality: float = 70.0,
    winner_local_base_min_tqs: float = 50.0,
    winner_local_base_min_velocity_3s: float = 2.2,
    winner_local_base_min_velocity_9s: float = 1.5,
    winner_local_base_min_local_base_move_pct: float = 5.0,
    winner_local_base_max_local_base_move_pct: float = 25.0,
    winner_local_base_max_capital_pct: float = 0.35,
    winner_local_base_require_cvd_on_worst: bool = True,
    winner_local_base_early_ftv_fresh_enabled: bool = True,
    ftv_policy_expiry_worst_block_enabled: bool = True,
    ftv_policy_expiry_worst_min_tier: str = "ELITE",
    ftv_policy_expiry_worst_min_quality: float = 85.0,
    ftv_policy_expiry_worst_min_score: float = 90.0,
    ftv_policy_expiry_worst_min_velocity_3s: float = 3.0,
    building_rip_ftv_enabled: bool = True,
    building_rip_ftv_min_explosion_score: float = 48.0,
    building_rip_ftv_min_velocity_3s: float = 1.2,
    building_rip_ftv_min_local_base_move_pct: float = 2.0,
    building_rip_ftv_max_local_base_move_pct: float = 55.0,
    building_rip_ftv_max_capital_pct: float = 0.90,
    top_moments_only_enabled: bool = True,
    top_moments_min_grade: str = "A",
    first_lift_local_base_micro_pullback_enabled: bool = True,
    first_lift_local_base_micro_pullback_min_velocity_3s: float = -1.2,
    first_lift_local_base_micro_pullback_min_velocity_9s: float = -0.5,
    first_lift_trade_min_score: float = 62.0,
    first_lift_helper_confirm_min_quality: float = 50.0,
) -> FtvAuthorization:
    """Pure causal authorization for strict S, top FTV A, winner, and BUILDING rip."""
    blocked = lambda reason: FtvAuthorization(None, reason)
    if str(evidence.get("mode") or "").lower() != "explosion":
        return blocked("ftv_elite_top_only_requires_explosion")

    actual_ftv = bool(
        (
            evidence.get("flatThenVertical")
            and evidence.get("activeBreakout")
        )
        or evidence.get("eliteBaseReady")
        or evidence.get("armedBaseLaunch")
        or evidence.get("vRipReady")
        or evidence.get("buildingRipReady")
    )
    if not actual_ftv:
        return blocked("ftv_elite_top_only_requires_ftv")

    micro_pullback = _first_lift_local_base_micro_pullback(
        evidence,
        enabled=first_lift_local_base_micro_pullback_enabled,
        min_velocity_3s=first_lift_local_base_micro_pullback_min_velocity_3s,
        min_velocity_9s=first_lift_local_base_micro_pullback_min_velocity_9s,
        min_local_base_move_pct=winner_local_base_min_local_base_move_pct,
        max_local_base_move_pct=winner_local_base_max_local_base_move_pct,
    )

    timing = str(evidence.get("timingAssessment") or "").upper()
    timing_action = str(evidence.get("timingAction") or "").lower()
    cold_velocity = (
        _number(evidence.get("velocity3s")) < 0
        or _number(evidence.get("velocity9s")) < 0
    )
    if (
        str(ranking.get("grade") or "").upper() == "REJECT"
        or evidence.get("faded")
        or evidence.get("exhaustedReentry")
        or (cold_velocity and not micro_pullback)
        or timing_action in {"block", "reject"}
        or timing in {
            "FAILED_LAUNCH",
            "FADED",
            "FADING",
            "EXHAUSTED",
            "NEGATIVE",
            "REJECT",
            "BLOCKED",
        }
    ):
        return blocked("ftv_elite_top_only_timing_blocked")
    if snapshot_available and not atm_itm_allowed:
        return blocked("ftv_elite_top_only_requires_atm_itm")

    def _expiry_worst_policy_ok(
        *,
        tier: str,
        quality: float,
        score: float,
        v3: float,
    ) -> FtvAuthorization | None:
        """None = pass; FtvAuthorization = blocked."""
        if not (
            ftv_policy_expiry_worst_block_enabled
            and _day_mode_is_expiry_worst(day_mode)
        ):
            return None
        min_tier = str(ftv_policy_expiry_worst_min_tier or "ELITE").upper()
        tier_rank = {"WATCH": 1, "BUILDING": 2, "EXPLODING": 3, "ELITE": 4}
        if tier_rank.get(str(tier or "").upper(), 0) < tier_rank.get(min_tier, 4):
            return blocked(
                f"ftv_expiry_worst_requires_{min_tier.lower()}"
            )
        if quality < float(ftv_policy_expiry_worst_min_quality or 85.0):
            return blocked("ftv_expiry_worst_quality_below_floor")
        if score < float(ftv_policy_expiry_worst_min_score or 90.0):
            return blocked("ftv_expiry_worst_score_below_floor")
        if v3 < float(ftv_policy_expiry_worst_min_velocity_3s or 3.0):
            return blocked("ftv_expiry_worst_velocity_3s_below_floor")
        return None

    grade = str(ranking.get("grade") or "").upper()
    if grade == "S":
        if not bool(ranking.get("topRankEligible")):
            return blocked("ftv_elite_top_only_requires_top_rank_eligible")
        if require_allocation_rank_one and allocation_rank != 1:
            return blocked("ftv_elite_top_only_requires_allocation_rank_1")
        # Elite-base preauth (2–5% pad) is already structured; armed/first-lift
        # S must still clear top local-base floors so mid EXPLODING cannot slip in.
        preauthorized = str(ranking.get("executionAuthorization") or "") == "S_PREAUTHORIZED"
        tier = str(evidence.get("tier") or "").upper()
        explosion_score = _number(evidence.get("explosionScore"))
        quality = _number(evidence.get("flatVerticalQuality"))
        v3 = _number(evidence.get("velocity3s"))
        if not preauthorized:
            if tier not in {"ELITE", "EXPLODING"}:
                return blocked("ftv_s_strict_requires_elite_or_exploding")
            move = _number(evidence.get("localBaseMovePct"))
            s_early_ftv = bool(
                winner_local_base_early_ftv_fresh_enabled
                and evidence.get("flatThenVertical")
                and evidence.get("activeBreakout")
                and (
                    evidence.get("orderflowPositive")
                    or evidence.get("volumeAwaken")
                    or evidence.get("displacement")
                    or evidence.get("armedBaseSustainedLift")
                )
                and ftv_s_strict_min_local_base_move_pct
                <= move
                <= ftv_s_strict_max_local_base_move_pct
            )
            if not bool(
                evidence.get("armedBaseLaunch")
                or evidence.get("firstLift")
                or evidence.get("eliteBaseReady")
                or evidence.get("vRipReady")
                or evidence.get("buildingRipReady")
                or evidence.get("armedBaseSustainedLift")
                or s_early_ftv
            ):
                return blocked("ftv_s_strict_requires_local_base_trigger")
            if move < ftv_s_strict_min_local_base_move_pct:
                return blocked("ftv_s_strict_local_base_too_early")
            if move > ftv_s_strict_max_local_base_move_pct:
                return blocked("ftv_s_strict_local_base_chase")
            if explosion_score < ftv_s_strict_min_explosion_score:
                return blocked("ftv_s_strict_explosion_score_below_floor")
            if quality < ftv_s_strict_min_quality:
                return blocked("ftv_s_strict_quality_below_floor")
            if v3 < ftv_s_strict_min_velocity_3s:
                return blocked("ftv_s_strict_velocity_3s_below_floor")
            if _number(evidence.get("velocity9s")) < ftv_s_strict_min_velocity_9s:
                return blocked("ftv_s_strict_velocity_9s_below_floor")
            if ftv_s_strict_require_cvd_buying and not (
                bool(evidence.get("cvdBuying"))
                or bool(evidence.get("orderflowPositive"))
            ):
                return blocked("ftv_s_strict_requires_buying_confirmation")
        expiry_block = _expiry_worst_policy_ok(
            tier=tier, quality=quality, score=explosion_score, v3=v3,
        )
        if expiry_block is not None:
            return expiry_block
        return FtvAuthorization("S_STRICT", "ok")

    move = _number(evidence.get("localBaseMovePct"))
    tier = str(evidence.get("tier") or "").upper()
    explosion_score = _number(evidence.get("explosionScore"))
    quality = _number(evidence.get("flatVerticalQuality"))
    tqs = _number(evidence.get("tqs"))
    v3 = _number(evidence.get("velocity3s"))
    v9 = _number(evidence.get("velocity9s"))
    # Armed / first-lift / elite are preferred. Early FTV + heat inside the
    # catch pad also counts as fresh — closes the 12–15% dead zone where radar
    # already shows the rip but flag continuity has gaps.
    flag_fresh = bool(
        evidence.get("firstLift")
        or evidence.get("armedBaseLaunch")
        or evidence.get("eliteBaseReady")
        or evidence.get("armedBaseSustainedLift")
    )
    early_ftv_heat = bool(
        evidence.get("orderflowPositive")
        or evidence.get("volumeAwaken")
        or evidence.get("displacement")
        or evidence.get("armedBaseSustainedLift")
    )
    early_ftv_fresh = bool(
        winner_local_base_early_ftv_fresh_enabled
        and evidence.get("flatThenVertical")
        and evidence.get("activeBreakout")
        and early_ftv_heat
        and winner_local_base_min_local_base_move_pct
        <= move
        <= winner_local_base_max_local_base_move_pct
    )
    fresh_trigger = flag_fresh or early_ftv_fresh
    timing_blocked = timing in {"CHASE", "CHASING", "LATE", "FAILED_LAUNCH"}

    top_ftv_a_reason = "top_ftv_a_disabled"
    if top_ftv_a_enabled:
        top_ftv_a_reason = "ok"
        if move > top_ftv_a_exceptional_max_move_pct:
            top_ftv_a_reason = "top_ftv_a_extension_above_40pct"
        elif grade != "A":
            top_ftv_a_reason = "top_ftv_a_requires_a_grade"
        elif tier not in {"ELITE", "EXPLODING"}:
            top_ftv_a_reason = "top_ftv_a_requires_elite_or_exploding"
        elif not bool(evidence.get("flatThenVertical") and evidence.get("activeBreakout")):
            top_ftv_a_reason = "top_ftv_a_requires_active_ftv"
        elif not fresh_trigger:
            top_ftv_a_reason = "top_ftv_a_requires_fresh_causal_trigger"
        elif timing_blocked:
            top_ftv_a_reason = "top_ftv_a_timing_blocked"
        elif not bool(evidence.get("cvdBuying")):
            top_ftv_a_reason = "top_ftv_a_requires_option_cvd_buying"
        elif not bool(evidence.get("cvdAcceleration")) and not (
            top_ftv_a_index_helpers_waive_cvd_accel
            and bool(
                evidence.get("indexHelpersConfirm")
                or evidence.get("indexTickSpike")
                or (
                    evidence.get("indexTickAlign")
                    and (
                        evidence.get("indexMomAlign")
                        or evidence.get("indexSqueezeAlign")
                    )
                )
            )
        ):
            top_ftv_a_reason = "top_ftv_a_requires_option_cvd_acceleration"
        elif explosion_score < top_ftv_a_min_explosion_score:
            top_ftv_a_reason = "top_ftv_a_explosion_score_below_floor"
        elif quality < top_ftv_a_min_quality:
            top_ftv_a_reason = "top_ftv_a_quality_below_floor"
        elif tqs < top_ftv_a_min_tqs:
            top_ftv_a_reason = "top_ftv_a_tqs_below_floor"
        elif v3 < top_ftv_a_min_velocity_3s:
            top_ftv_a_reason = "top_ftv_a_velocity_3s_below_floor"
        elif v9 < top_ftv_a_min_velocity_9s:
            top_ftv_a_reason = "top_ftv_a_velocity_9s_below_floor"
        else:
            exceptional = move > top_ftv_a_normal_max_move_pct
            if exceptional and not (
                explosion_score >= top_ftv_a_exceptional_min_explosion_score
                and quality >= top_ftv_a_exceptional_min_quality
                and tqs >= top_ftv_a_exceptional_min_tqs
                and v3 >= top_ftv_a_exceptional_min_velocity_3s
                and v9 >= top_ftv_a_exceptional_min_velocity_9s
            ):
                top_ftv_a_reason = "top_ftv_a_extended_requires_exceptional_acceleration"
            elif require_allocation_rank_one and allocation_rank != 1:
                top_ftv_a_reason = "top_ftv_a_requires_allocation_rank_1"
            else:
                expiry_block = _expiry_worst_policy_ok(
                    tier=tier, quality=quality, score=explosion_score, v3=v3,
                )
                if expiry_block is not None:
                    return expiry_block
                return FtvAuthorization(
                    "TOP_FTV_A",
                    "ok_exceptional_extension" if exceptional else "ok",
                    max_capital_pct=top_ftv_a_max_capital_pct,
                    exceptional_extension=exceptional,
                )

    # Historical winner shape: ELITE/EXPLODING at local base with real heat.
    # Ordinary sleeve only; does not require CVD acceleration. Disabled when the
    # TOP_FTV_A fallback master switch is off (strict-S-only mode).
    if winner_local_base_enabled and top_ftv_a_enabled:
        winner_ok = (
            grade in {"A", "B"}
            and tier in {"ELITE", "EXPLODING"}
            and fresh_trigger
            and not timing_blocked
            and bool(evidence.get("orderflowPositive"))
            and winner_local_base_min_local_base_move_pct
            <= move
            <= winner_local_base_max_local_base_move_pct
            and explosion_score >= winner_local_base_min_explosion_score
            and quality >= winner_local_base_min_quality
            and tqs >= winner_local_base_min_tqs
            and v3 >= winner_local_base_min_velocity_3s
            and v9 >= winner_local_base_min_velocity_9s
        )
        if top_moments_only_enabled and grade == "B":
            winner_ok = False
        if winner_ok:
            if (
                winner_local_base_require_cvd_on_worst
                and _day_mode_is_worst(day_mode)
                and not bool(evidence.get("cvdBuying"))
            ):
                return blocked("winner_local_base_worst_requires_cvd_buying")
            if require_allocation_rank_one and allocation_rank != 1:
                return blocked("winner_local_base_requires_allocation_rank_1")
            expiry_block = _expiry_worst_policy_ok(
                tier=tier, quality=quality, score=explosion_score, v3=v3,
            )
            if expiry_block is not None:
                return expiry_block
            return FtvAuthorization(
                "WINNER_LOCAL_BASE",
                "ok",
                max_capital_pct=winner_local_base_max_capital_pct,
            )

    # First-lift / V-rip at local base with micro velocity pullback — ICT pad
    # already confirmed; shallow dip is base retest, not failed launch.
    if (
        first_lift_local_base_micro_pullback_enabled
        and micro_pullback
        and str(ranking.get("grade") or "").upper() in {"A", "B"}
        and tier in {"ELITE", "EXPLODING"}
        and explosion_score >= first_lift_trade_min_score
        and quality >= first_lift_helper_confirm_min_quality
    ):
        if require_allocation_rank_one and allocation_rank != 1:
            return blocked("first_lift_local_base_requires_allocation_rank_1")
        expiry_block = _expiry_worst_policy_ok(
            tier=tier, quality=quality, score=explosion_score, v3=v3,
        )
        if expiry_block is not None:
            return expiry_block
        return FtvAuthorization(
            "FIRST_LIFT_LOCAL_BASE",
            "ok_micro_pullback",
            max_capital_pct=winner_local_base_max_capital_pct,
        )

    # BUILDING sudden lift with helpers — do not wait for ELITE/EXPLODING.
    # Readiness already proved mid-rip/local-base heat; CHASE timing is OK here.
    if building_rip_ftv_enabled and bool(evidence.get("buildingRipReady")):
        helpers_ok = bool(
            evidence.get("buildingRipHelpersOk")
            or evidence.get("buildingLiftHelping")
            or evidence.get("cvdBuying")
            or evidence.get("cvdAcceleration")
            or evidence.get("orderflowPositive")
            or evidence.get("volumeAwaken")
            or evidence.get("displacement")
        )
        building_rip_ok = (
            grade in {"A", "B", "S"}
            and tier in {"BUILDING", "EXPLODING", "ELITE"}
            and building_rip_ftv_min_local_base_move_pct
            <= move
            <= building_rip_ftv_max_local_base_move_pct
            and v3 >= building_rip_ftv_min_velocity_3s
            and explosion_score >= building_rip_ftv_min_explosion_score
            and helpers_ok
            and timing not in {"FAILED_LAUNCH", "FADED", "FADING", "EXHAUSTED"}
        )
        if top_moments_only_enabled and grade == "B":
            building_rip_ok = False
        if building_rip_ok:
            if require_allocation_rank_one and allocation_rank != 1:
                return blocked("building_rip_ftv_requires_allocation_rank_1")
            expiry_block = _expiry_worst_policy_ok(
                tier=tier, quality=quality, score=explosion_score, v3=v3,
            )
            if expiry_block is not None:
                return expiry_block
            return FtvAuthorization(
                "BUILDING_RIP_FTV",
                "ok",
                max_capital_pct=building_rip_ftv_max_capital_pct,
            )

    if not top_ftv_a_enabled:
        return blocked("ftv_elite_top_only_requires_s")
    return blocked(top_ftv_a_reason)


def ftv_policy_settings(settings: Any) -> dict[str, Any]:
    """Adapt Settings to pure-policy keyword arguments."""
    names = (
        "top_ftv_a_enabled",
        "top_ftv_a_min_explosion_score",
        "top_ftv_a_min_quality",
        "top_ftv_a_min_tqs",
        "top_ftv_a_min_velocity_3s",
        "top_ftv_a_min_velocity_9s",
        "top_ftv_a_normal_max_move_pct",
        "top_ftv_a_max_capital_pct",
        "top_ftv_a_exceptional_min_explosion_score",
        "top_ftv_a_exceptional_min_quality",
        "top_ftv_a_exceptional_min_tqs",
        "top_ftv_a_exceptional_min_velocity_3s",
        "top_ftv_a_exceptional_min_velocity_9s",
        "top_ftv_a_exceptional_max_move_pct",
        "top_ftv_a_index_helpers_waive_cvd_accel",
        "ftv_s_strict_min_explosion_score",
        "ftv_s_strict_min_quality",
        "ftv_s_strict_min_velocity_3s",
        "ftv_s_strict_min_velocity_9s",
        "ftv_s_strict_require_cvd_buying",
        "ftv_s_strict_min_local_base_move_pct",
        "ftv_s_strict_max_local_base_move_pct",
        "winner_local_base_enabled",
        "winner_local_base_min_explosion_score",
        "winner_local_base_min_quality",
        "winner_local_base_min_tqs",
        "winner_local_base_min_velocity_3s",
        "winner_local_base_min_velocity_9s",
        "winner_local_base_min_local_base_move_pct",
        "winner_local_base_max_local_base_move_pct",
        "winner_local_base_max_capital_pct",
        "winner_local_base_require_cvd_on_worst",
        "winner_local_base_early_ftv_fresh_enabled",
        "ftv_policy_expiry_worst_block_enabled",
        "ftv_policy_expiry_worst_min_tier",
        "ftv_policy_expiry_worst_min_quality",
        "ftv_policy_expiry_worst_min_score",
        "ftv_policy_expiry_worst_min_velocity_3s",
        "building_rip_ftv_enabled",
        "building_rip_ftv_min_explosion_score",
        "building_rip_ftv_min_velocity_3s",
        "building_rip_ftv_min_local_base_move_pct",
        "building_rip_ftv_max_local_base_move_pct",
        "building_rip_ftv_max_capital_pct",
        "top_moments_only_enabled",
        "top_moments_min_grade",
        "first_lift_local_base_micro_pullback_enabled",
        "first_lift_local_base_micro_pullback_min_velocity_3s",
        "first_lift_local_base_micro_pullback_min_velocity_9s",
        "first_lift_trade_min_score",
        "first_lift_helper_confirm_min_quality",
    )
    return {name: getattr(settings, name) for name in names}


def rank_trade_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Grade one trade without using outcomes, exits, or future P&L."""
    try:
        from app.config import get_settings

        settings = get_settings()
        micro_pullback = _first_lift_local_base_micro_pullback(
            evidence,
            enabled=bool(
                getattr(settings, "first_lift_local_base_micro_pullback_enabled", True)
            ),
            min_velocity_3s=float(
                getattr(
                    settings,
                    "first_lift_local_base_micro_pullback_min_velocity_3s",
                    -1.2,
                )
                or -1.2
            ),
            min_velocity_9s=float(
                getattr(
                    settings,
                    "first_lift_local_base_micro_pullback_min_velocity_9s",
                    -0.5,
                )
                or -0.5
            ),
            min_local_base_move_pct=float(
                getattr(settings, "winner_local_base_min_local_base_move_pct", 2.0) or 2.0
            ),
            max_local_base_move_pct=float(
                getattr(settings, "winner_local_base_max_local_base_move_pct", 25.0) or 25.0
            ),
        )
    except Exception:
        micro_pullback = _first_lift_local_base_micro_pullback(evidence)

    mode = str(evidence.get("mode") or "").lower()
    tier = str(evidence.get("tier") or "").upper()
    explosion_score = max(0.0, min(100.0, _number(evidence.get("explosionScore"))))
    tqs = max(0.0, min(100.0, _number(evidence.get("tqs"))))
    chart = max(0.0, min(100.0, _number(evidence.get("chartConfidence"))))
    v3 = _number(evidence.get("velocity3s"))
    v9 = _number(evidence.get("velocity9s"))
    local_move = max(0.0, _number(evidence.get("localBaseMovePct")))
    first_lift = bool(evidence.get("firstLift"))
    armed_launch = bool(evidence.get("armedBaseLaunch"))
    elite_base_ready = bool(evidence.get("eliteBaseReady"))
    if bool(evidence.get("midRipCoil")):
        elite_base_ready = False
    v_rip_ready = bool(evidence.get("vRipReady")) and not bool(
        evidence.get("midRipCoil")
    )
    building_rip_ready = bool(evidence.get("buildingRipReady")) and not bool(
        evidence.get("midRipCoil")
    )
    flat_vertical = bool(evidence.get("flatThenVertical"))
    active_breakout = bool(evidence.get("activeBreakout"))
    orderflow = bool(evidence.get("orderflowPositive"))
    cvd_buying = bool(evidence.get("cvdBuying"))
    cvd_acceleration = bool(evidence.get("cvdAcceleration"))
    flat_vertical_quality = max(
        0.0, min(100.0, _number(evidence.get("flatVerticalQuality")))
    )
    exhausted = bool(evidence.get("exhaustedReentry"))
    faded = bool(evidence.get("faded"))
    timing = str(evidence.get("timingAssessment") or "").upper()
    timing_action = str(evidence.get("timingAction") or "").lower()

    score = 25.0 + explosion_score * 0.30 + tqs * 0.10 + chart * 0.10
    reasons: list[str] = []
    penalties: list[dict[str, Any]] = []

    if tier == "ELITE":
        score += 6.0
        reasons.append("elite_signal")
    elif tier == "EXPLODING":
        score += 3.0
        reasons.append("exploding_signal")

    if v3 > 0:
        score += min(10.0, v3 * 3.0)
        reasons.append(f"positive_v3_{v3:.2f}")
    elif v3 < 0:
        if micro_pullback:
            score -= 5.0
            penalties.append(
                {
                    "code": "first_lift_micro_pullback",
                    "points": 5.0,
                    "value": round(v3, 2),
                }
            )
            reasons.append(f"first_lift_micro_pullback_v3_{v3:.2f}")
        else:
            score -= 30.0
            penalties.append({"code": "negative_velocity", "points": 30.0, "value": round(v3, 2)})
    else:
        penalties.append({"code": "missing_or_flat_velocity", "points": 0.0, "value": 0.0})
    if v9 > 0:
        score += min(5.0, v9)
        reasons.append(f"positive_v9_{v9:.2f}")

    if armed_launch:
        score += 12.0
        reasons.append("fresh_armed_base_launch")
    elif elite_base_ready:
        score += 12.0
        reasons.append("elite_base_ready")
    elif v_rip_ready:
        score += 10.0
        reasons.append("v_rip_session_low")
    elif building_rip_ready:
        score += 9.0
        reasons.append("building_rip_bullish")
    elif first_lift:
        score += 8.0
        reasons.append("fresh_first_lift")
    elif flat_vertical:
        score += 6.0
        reasons.append("flat_then_vertical")
    if orderflow:
        score += 6.0
        reasons.append("positive_orderflow")

    if 15.0 <= local_move <= 35.0:
        score += 6.0
        reasons.append(f"local_base_sweet_spot_{local_move:.1f}%")
    elif local_move > 40.0 and not building_rip_ready:
        extension_penalty = min(45.0, (local_move - 40.0) * 1.4)
        score -= extension_penalty
        penalties.append(
            {
                "code": "extended_from_local_base",
                "points": round(extension_penalty, 1),
                "value": round(local_move, 1),
            }
        )
    elif building_rip_ready and local_move > 55.0:
        extension_penalty = min(45.0, (local_move - 55.0) * 1.4)
        score -= extension_penalty
        penalties.append(
            {
                "code": "extended_building_rip",
                "points": round(extension_penalty, 1),
                "value": round(local_move, 1),
            }
        )

    rejected = False
    if timing == "FAILED_LAUNCH" or timing_action == "block" and v3 < 0:
        rejected = True
        penalties.append({"code": "failed_launch", "points": 45.0})
        score -= 45.0
    if v3 < 0 and not micro_pullback:
        rejected = True
    if exhausted:
        rejected = True
        penalties.append({"code": "exhausted_post_peak_reentry", "points": 60.0})
        score -= 60.0
    if bool(evidence.get("midRipCoil")):
        rejected = True
        penalties.append({"code": "mid_rip_armed_coil", "points": 50.0})
        score -= 50.0

    elite_preauthorized = bool(
        elite_base_ready
        and tier in ("EXPLODING", "ELITE")
        and explosion_score >= 45.0
        and tqs >= 50.0
        and 2.0 <= local_move < 5.0
    )
    # Aug19 76900 PE: elite_base_ready at 2.6% off a mid-rip coil while off-low
    # was already ~42%. Never S-preauthorize when session-trough expansion says chase.
    off_low = max(0.0, _number(evidence.get("offLowMovePct")))
    if elite_preauthorized and off_low >= 30.0 and off_low > local_move + 10.0:
        elite_preauthorized = False
        penalties.append(
            {
                "code": "mid_rip_false_early_pad",
                "points": 40.0,
                "value": round(off_low, 1),
            }
        )
        score -= 40.0
    # Top S at local base only — armed launch alone must not mint grade S for
    # mid EXPLODING (score ~70, quality B). Elite-base preauth (2–5%) stays.
    armed_top_local = bool(
        armed_launch
        and tier in ("ELITE", "EXPLODING")
        and explosion_score >= 85.0
        # Confirmed flat->vertical STRUCTURE, or an explicit high FTV quality score, proves
        # the launch pad. Requiring the numeric quality alone dropped genuine S launches
        # whose alert only stamped the structure flag (aug18 EXPLODING armed launch).
        and (flat_vertical_quality >= 70.0 or flat_vertical)
        and v3 >= 2.5
        and v9 >= 1.75
        and orderflow
        and 5.0 <= local_move <= 25.0
        and not rejected
    )
    s_quality = bool(
        mode == "explosion"
        and (armed_top_local or elite_preauthorized)
        and orderflow
        and not rejected
        and local_move <= 40.0
        and (
            armed_top_local
            or (v3 >= 1.5 and v9 >= 1.5)
        )
    )
    fresh_positive = bool(
        mode == "explosion"
        and (
            first_lift
            or flat_vertical
            or armed_launch
            or elite_base_ready
            or v_rip_ready
            or building_rip_ready
        )
        and v3 > 0
        and not rejected
        and local_move <= (55.0 if building_rip_ready else 40.0)
    )
    score = max(0.0, min(100.0, score))
    if rejected:
        grade = "REJECT"
        score = min(score, 19.0)
    elif s_quality:
        grade = "S"
        score = max(score, 90.0)
    elif fresh_positive and score >= 70.0:
        grade = "A"
    elif score >= 60.0:
        grade = "B"
    else:
        grade = "C"

    return {
        "rankScore": round(score, 1),
        "grade": grade,
        "gradePriority": GRADE_PRIORITY[grade],
        "signalTier": tier or None,
        "reasons": reasons,
        "penalties": penalties,
        "topRankEligible": s_quality,
        "fullSleeveEligible": s_quality,
        "executionAuthorization": (
            "S_PREAUTHORIZED" if elite_preauthorized and s_quality else None
        ),
        "causalOnly": True,
        "evidence": {
            "mode": mode,
            "tier": tier or None,
            "velocity3s": round(v3, 3),
            "velocity9s": round(v9, 3),
            "localBaseMovePct": round(local_move, 2),
            "firstLift": first_lift,
            "eliteBaseReady": elite_base_ready,
            "vRipReady": v_rip_ready,
            "buildingRipReady": building_rip_ready,
            "buildingRipHelpersOk": bool(
                evidence.get("buildingRipHelpersOk")
                or evidence.get("buildingLiftHelping")
            ),
            "buildingLiftHelping": bool(evidence.get("buildingLiftHelping")),
            "armedBaseLaunch": armed_launch,
            "armedBaseSustainedLift": bool(evidence.get("armedBaseSustainedLift")),
            "flatThenVertical": flat_vertical,
            "activeBreakout": active_breakout,
            "orderflowPositive": orderflow,
            "volumeAwaken": bool(evidence.get("volumeAwaken")),
            "displacement": bool(evidence.get("displacement")),
            "cvdBuying": cvd_buying,
            "cvdAcceleration": cvd_acceleration,
            "indexHelpersConfirm": bool(evidence.get("indexHelpersConfirm")),
            "indexTickSpike": bool(evidence.get("indexTickSpike")),
            "indexTickAlign": bool(evidence.get("indexTickAlign")),
            "indexMomAlign": bool(evidence.get("indexMomAlign")),
            "indexSqueezeAlign": bool(evidence.get("indexSqueezeAlign")),
            "indexSpotMove3s": _number(evidence.get("indexSpotMove3s")),
            "indexSpotMove9s": _number(evidence.get("indexSpotMove9s")),
            "explosionScore": round(explosion_score, 2),
            "flatVerticalQuality": round(flat_vertical_quality, 2),
            "tqs": round(tqs, 2),
            "timingAssessment": timing or None,
            "timingAction": timing_action or None,
            "firstLiftLocalBaseMicroPullback": micro_pullback,
            "exhaustedReentry": exhausted,
            "faded": faded,
        },
    }


def rank_entry_candidate(
    candidate: Any,
    *,
    exhausted_reentry: bool = False,
    faded: bool = False,
    snapshot: Any = None,
) -> dict[str, Any]:
    """Adapt a selector candidate to the pure causal scorecard."""
    alert = candidate.alert if isinstance(getattr(candidate, "alert", None), dict) else {}
    event = getattr(candidate, "explosion_event", None)
    pretrade = getattr(candidate, "pretrade_meta", None) or {}
    live_snapshot = snapshot or getattr(candidate, "snap", None)
    timing = pretrade.get("timingAssessment") or {}
    if not isinstance(timing, Mapping):
        timing = {"assessment": timing}
    chart_confidence = 0.0
    try:
        from app.engines.chart_exit_levels import chart_trade_confidence

        chart_confidence, _ = chart_trade_confidence(live_snapshot, candidate.side)
    except Exception:
        chart_confidence = 0.0
    volume_surge = _number(getattr(event, "volume_surge", 0) if event else 0)
    cvd_buying = False
    cvd_acceleration = False
    try:
        from app.engines.advanced_indicators import (
            option_cvd_acceleration_confirms_buying,
            option_cvd_confirms_buying,
        )

        cvd_buying = option_cvd_confirms_buying(
            live_snapshot, candidate.strike, candidate.side
        )
        cvd_acceleration = option_cvd_acceleration_confirms_buying(
            live_snapshot, candidate.strike, candidate.side
        )
    except Exception:
        pass
    evidence = {
        "mode": getattr(candidate, "mode", "") or ("explosion" if event else ""),
        "tier": (
            getattr(candidate, "tier", "")
            or alert.get("tier")
            or (getattr(event, "tier", "") if event else "")
        ),
        "explosionScore": (
            getattr(event, "explosion_score", 0) if event else getattr(candidate, "confidence", 0)
        ),
        "tqs": getattr(candidate, "tqs", 0),
        "flatVerticalQuality": (
            alert.get("flatVerticalQuality")
            or alert.get("ictFlatVerticalQuality")
            or 0
        ),
        "chartConfidence": chart_confidence,
        "velocity3s": getattr(event, "velocity_3s", 0) if event else alert.get("velocity3s"),
        "velocity9s": getattr(event, "velocity_9s", 0) if event else alert.get("velocity9s"),
        "localBaseMovePct": (
            alert.get("localBaseMovePct")
            or alert.get("ictBaseRelativeMovePct")
            or pretrade.get("ictBaseRelativeMovePct")
        ),
        "offLowMovePct": (
            alert.get("offLowMovePct")
            or pretrade.get("offLowMovePct")
        ),
        "firstLift": alert.get("ictFirstLift"),
        "eliteBaseReady": alert.get("ictEliteBaseReady"),
        "vRipReady": alert.get("ictVRipReady"),
        "buildingRipReady": alert.get("ictBuildingRipReady"),
        "buildingRipHelpersOk": bool(
            alert.get("buildingRipHelpersOk") or alert.get("buildingLiftHelping")
        ),
        "buildingLiftHelping": bool(alert.get("buildingLiftHelping")),
        "armedBaseLaunch": alert.get("ictArmedBaseLaunch"),
        "armedBaseSustainedLift": alert.get("ictArmedBaseSustainedLift"),
        "flatThenVertical": alert.get("ictFlatThenVertical"),
        "activeBreakout": alert.get("ictBreakout"),
        "midRipCoil": bool(
            alert.get("ictMidRipCoil") or alert.get("midRipCoil")
        ),
        "orderflowPositive": bool(
            alert.get("ictVolumeAwakening")
            or alert.get("volumeAwaken")
            or alert.get("cvdBuying")
            or alert.get("cvdAcceleration")
            or volume_surge >= 1.2
        ),
        "volumeAwaken": bool(
            alert.get("ictVolumeAwakening") or alert.get("volumeAwaken")
        ),
        "displacement": bool(alert.get("ictDisplacement")),
        "cvdBuying": cvd_buying,
        "cvdAcceleration": cvd_acceleration,
        "indexHelpersConfirm": bool(alert.get("indexHelpersConfirm")),
        "indexTickSpike": bool(alert.get("indexTickSpike")),
        "indexTickAlign": bool(alert.get("indexTickAlign")),
        "indexMomAlign": bool(alert.get("indexMomAlign")),
        "indexSqueezeAlign": bool(alert.get("indexSqueezeAlign")),
        "indexSpotMove3s": alert.get("indexSpotMove3s"),
        "indexSpotMove9s": alert.get("indexSpotMove9s"),
        "timingAssessment": timing.get("assessment"),
        "timingAction": timing.get("action"),
        "exhaustedReentry": exhausted_reentry,
        "faded": bool(
            faded
            or alert.get("fadedRip")
            or alert.get("fadedVerticalRip")
            or alert.get("fadedRipCaution")
        ),
    }
    # Live index helpers when alert not yet stamped (ELITE/EXPLODING path).
    if live_snapshot is not None and not evidence.get("indexHelpersConfirm"):
        try:
            from app.engines.index_tick_helpers import (
                evaluate_index_tick_helpers,
                stamp_index_tick_helpers,
            )

            idx = evaluate_index_tick_helpers(
                snap=live_snapshot,
                side=getattr(candidate, "side", ""),
                alert=alert,
            )
            stamp_index_tick_helpers(alert, idx)
            evidence["indexHelpersConfirm"] = bool(idx.confirming)
            evidence["indexTickSpike"] = bool(idx.tick_spike)
            evidence["indexTickAlign"] = bool(idx.tick_align)
            evidence["indexMomAlign"] = bool(idx.mom_align)
            evidence["indexSqueezeAlign"] = bool(idx.squeeze_align)
            evidence["indexSpotMove3s"] = idx.velocity_3s
            evidence["indexSpotMove9s"] = idx.velocity_9s
        except Exception:
            pass
    return rank_trade_evidence(evidence)
