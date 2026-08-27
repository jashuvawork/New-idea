"""Comparable causal trade ranking from evidence available before entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.engines.pad_lane_capture import (
    pad_lane_cold_velocity_ok as _pad_lane_cold_velocity_ok,
    pad_lane_pre_lift as _pad_lane_pre_lift,
)


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


def _allocation_rank_blocks_ftv(
    *,
    require_allocation_rank_one: bool,
    allocation_rank: int | None,
    evidence: Mapping[str, Any],
) -> bool:
    """True when rank-1 is required and pad-lane waiver does not apply."""
    if not require_allocation_rank_one or allocation_rank == 1:
        return False
    from app.engines.pad_lane_capture import pad_lane_ftv_waives_allocation_rank_one

    return not pad_lane_ftv_waives_allocation_rank_one(evidence)


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


def _first_lift_local_base_flat_velocity(
    evidence: Mapping[str, Any],
    *,
    enabled: bool = True,
    min_local_base_move_pct: float = 2.0,
    max_local_base_move_pct: float = 25.0,
    max_velocity_3s: float = 0.85,
) -> bool:
    """ICT-confirmed first lift or V-rip at local base when the velocity snapshot is flat.

    Radar already stamped volumeAwaken + flat→vertical structure; v3 below the
    volume-awake floor is snapshot lag / slow lift start at the pad — not a dead
    launch. Aug25 SENSEX PUT 77200 (v3=0.65) and NIFTY PUT 24300 (v3=0.32) were
    blocked by top_ftv_a_velocity_3s_below_floor despite peak ≥25% at lb 20–25%.
    """
    if not enabled:
        return False
    v3 = _number(evidence.get("velocity3s"))
    if v3 < 0 or v3 >= max_velocity_3s:
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


def _shallow_otm_local_base_ftv_waives_atm_itm(evidence: Mapping[str, Any]) -> bool:
    """#428 shallow OTM stamp — ELITE flat→vertical at local base may execute 1-step OTM."""
    if not bool(evidence.get("shallowOtmLocalBaseTradeable")):
        return False
    tier = str(evidence.get("tier") or "").upper()
    if tier not in {"ELITE", "EXPLODING"}:
        return False
    move = max(
        _number(evidence.get("localBaseMovePct")),
        _number(evidence.get("ictBaseRelativeMovePct")),
    )
    if not (2.0 <= move <= 25.0 + 1e-6):
        return False
    top_moment = bool(
        evidence.get("armedBaseLaunch")
        or evidence.get("ictArmedBaseLaunch")
        or (
            evidence.get("flatThenVertical")
            and (
                evidence.get("activeBreakout")
                or evidence.get("volumeAwaken")
                or evidence.get("orderflowPositive")
            )
        )
    )
    if not top_moment:
        return False
    if bool(
        evidence.get("faded")
        or evidence.get("exhaustedReentry")
        or evidence.get("midRipCoil")
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


def _top_ftv_a_pad_capture_lane(
    evidence: Mapping[str, Any],
    *,
    move: float,
    pad_min_move_pct: float,
    pad_max_move_pct: float,
) -> bool:
    """Early local-base pad where v-rip / volume heat already proved causal lift."""
    if not (pad_min_move_pct <= move <= pad_max_move_pct):
        return False
    return bool(
        evidence.get("vRipReady")
        or evidence.get("volumeAwaken")
        or evidence.get("ictVolumeAwakening")
        or evidence.get("fastBullishLocalBase")
        or evidence.get("slowGrindSuddenLift")
        or evidence.get("squeezeRelease")
        or evidence.get("indexLedOptionLag")
        or evidence.get("stealthCvdCoil")
        or evidence.get("microPullbackRetest")
        or evidence.get("premiumFvgPad")
        or evidence.get("doubleDipVbase")
    )


def _top_ftv_a_effective_velocity_floors(
    evidence: Mapping[str, Any],
    *,
    move: float,
    default_min_v3: float,
    default_min_v9: float,
    pad_min_move_pct: float,
    pad_max_move_pct: float,
    v_rip_min_velocity_3s: float,
    v_rip_min_velocity_9s: float,
    v_rip_pad_min_move_pct: float,
    v_rip_volume_awake_min_velocity_3s: float,
) -> tuple[float, float]:
    if not _top_ftv_a_pad_capture_lane(
        evidence,
        move=move,
        pad_min_move_pct=pad_min_move_pct,
        pad_max_move_pct=pad_max_move_pct,
    ):
        return default_min_v3, default_min_v9
    min_v3 = default_min_v3
    min_v9 = default_min_v9
    volume_awake = bool(
        evidence.get("volumeAwaken") or evidence.get("orderflowPositive")
    )
    if volume_awake and move + 1e-6 >= v_rip_pad_min_move_pct:
        min_v3 = min(min_v3, v_rip_volume_awake_min_velocity_3s)
        min_v9 = min(min_v9, v_rip_min_velocity_9s)
    elif evidence.get("vRipReady"):
        min_v3 = min(min_v3, v_rip_min_velocity_3s)
        min_v9 = min(min_v9, v_rip_min_velocity_9s)
    return min_v3, min_v9


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
    top_ftv_a_pad_velocity_min_move_pct: float = 8.0,
    top_ftv_a_pad_velocity_max_move_pct: float = 25.0,
    top_ftv_a_pad_waive_cvd_when_volume_awake: bool = True,
    ict_v_rip_min_velocity_3s: float = 1.2,
    ict_v_rip_min_velocity_9s: float = 0.8,
    ict_v_rip_pad_min_move_pct: float = 2.0,
    ict_v_rip_volume_awake_min_velocity_3s: float = 0.85,
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
    building_rip_ftv_min_explosion_score: float = 12.0,
    building_rip_ftv_min_velocity_3s: float = 1.2,
    building_rip_ftv_min_local_base_move_pct: float = 2.0,
    building_rip_ftv_max_local_base_move_pct: float = 55.0,
    building_rip_ftv_max_capital_pct: float = 0.90,
    slow_grind_ftv_enabled: bool = True,
    slow_grind_ftv_min_explosion_score: float = 12.0,
    slow_grind_ftv_min_flat_quality: float = 50.0,
    slow_grind_ftv_armed_trough_min_explosion_score: float = 5.0,
    slow_grind_ftv_consolidation_base_min_explosion_score: float = 12.0,
    slow_grind_ftv_consolidation_base_min_flat_quality: float = 35.0,
    slow_grind_ftv_max_capital_pct: float = 0.90,
    fast_bullish_ftv_enabled: bool = True,
    fast_bullish_ftv_min_explosion_score: float = 12.0,
    fast_bullish_ftv_min_velocity_3s: float = 0.5,
    fast_bullish_ftv_max_capital_pct: float = 0.90,
    squeeze_release_ftv_enabled: bool = True,
    squeeze_release_ftv_min_explosion_score: float = 12.0,
    squeeze_release_ftv_max_capital_pct: float = 0.90,
    index_led_option_lag_ftv_enabled: bool = True,
    index_led_option_lag_ftv_min_explosion_score: float = 12.0,
    index_led_option_lag_ftv_max_capital_pct: float = 0.90,
    stealth_cvd_coil_ftv_enabled: bool = True,
    stealth_cvd_coil_ftv_min_explosion_score: float = 12.0,
    stealth_cvd_coil_ftv_max_capital_pct: float = 0.90,
    micro_pullback_retest_ftv_enabled: bool = True,
    micro_pullback_retest_ftv_min_explosion_score: float = 12.0,
    micro_pullback_retest_ftv_max_capital_pct: float = 0.90,
    premium_fvg_pad_ftv_enabled: bool = True,
    premium_fvg_pad_ftv_min_explosion_score: float = 12.0,
    premium_fvg_pad_ftv_max_capital_pct: float = 0.90,
    double_dip_vbase_ftv_enabled: bool = True,
    double_dip_vbase_ftv_min_explosion_score: float = 12.0,
    double_dip_vbase_ftv_max_capital_pct: float = 0.90,
    early_radar_pad_ftv_enabled: bool = True,
    early_radar_pad_ftv_min_explosion_score: float = 5.0,
    early_radar_pad_ftv_max_capital_pct: float = 0.90,
    early_radar_pad_max_off_low_pct: float = 15.0,
    top_moments_only_enabled: bool = True,
    top_moments_min_grade: str = "A",
    first_lift_local_base_micro_pullback_enabled: bool = True,
    first_lift_local_base_micro_pullback_min_velocity_3s: float = -1.2,
    first_lift_local_base_micro_pullback_min_velocity_9s: float = -0.5,
    first_lift_local_base_flat_velocity_enabled: bool = True,
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
        or _pad_lane_pre_lift(evidence)
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
    flat_velocity_lag = _first_lift_local_base_flat_velocity(
        evidence,
        enabled=first_lift_local_base_flat_velocity_enabled,
        min_local_base_move_pct=winner_local_base_min_local_base_move_pct,
        max_local_base_move_pct=winner_local_base_max_local_base_move_pct,
        max_velocity_3s=ict_v_rip_volume_awake_min_velocity_3s,
    )

    timing = str(evidence.get("timingAssessment") or "").upper()
    timing_action = str(evidence.get("timingAction") or "").lower()
    slow_grind_flat = bool(
        evidence.get("slowGrindSuddenLift")
        and -0.8 <= _number(evidence.get("velocity3s")) <= 1.5
    )
    pad_lane_flat = _pad_lane_cold_velocity_ok(
        evidence,
        _number(evidence.get("velocity3s")),
        _number(evidence.get("velocity9s")),
    )
    cold_velocity = (
        _number(evidence.get("velocity3s")) < 0
        or _number(evidence.get("velocity9s")) < 0
    )
    if evidence.get("faded") or evidence.get("exhaustedReentry"):
        return blocked("ftv_elite_top_only_timing_blocked")
    if (
        str(ranking.get("grade") or "").upper() == "REJECT"
        or (cold_velocity and not micro_pullback and not slow_grind_flat and not pad_lane_flat)
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
        from app.engines.pad_lane_capture import pad_lane_ftv_waives_timing_block

        if not pad_lane_ftv_waives_timing_block(evidence):
            return blocked("ftv_elite_top_only_timing_blocked")
    if snapshot_available and not atm_itm_allowed:
        if not _shallow_otm_local_base_ftv_waives_atm_itm(evidence):
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
        from app.engines.pad_lane_capture import pad_lane_expiry_worst_waive

        if pad_lane_expiry_worst_waive(evidence):
            return None
        from app.engines.grade_a_ftv_capture import grade_a_ftv_expiry_worst_waive

        if grade_a_ftv_expiry_worst_waive(evidence):
            return None
        from app.engines.top_ftv_v_expiry_bypass import top_ftv_v_expiry_worst_waive

        if top_ftv_v_expiry_worst_waive(evidence):
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
        if _allocation_rank_blocks_ftv(
            require_allocation_rank_one=require_allocation_rank_one,
            allocation_rank=allocation_rank,
            evidence=evidence,
        ):
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
                or evidence.get("slowGrindSuddenLift")
                or evidence.get("fastBullishLocalBase")
                or evidence.get("armedBaseSustainedLift")
                or _pad_lane_pre_lift(evidence)
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
        or evidence.get("fastBullishLocalBase")
        or evidence.get("slowGrindSuddenLift")
        or evidence.get("squeezeRelease")
        or evidence.get("indexLedOptionLag")
        or evidence.get("stealthCvdCoil")
        or evidence.get("microPullbackRetest")
        or evidence.get("premiumFvgPad")
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
    effective_min_v3, effective_min_v9 = _top_ftv_a_effective_velocity_floors(
        evidence,
        move=move,
        default_min_v3=top_ftv_a_min_velocity_3s,
        default_min_v9=top_ftv_a_min_velocity_9s,
        pad_min_move_pct=top_ftv_a_pad_velocity_min_move_pct,
        pad_max_move_pct=top_ftv_a_pad_velocity_max_move_pct,
        v_rip_min_velocity_3s=ict_v_rip_min_velocity_3s,
        v_rip_min_velocity_9s=ict_v_rip_min_velocity_9s,
        v_rip_pad_min_move_pct=ict_v_rip_pad_min_move_pct,
        v_rip_volume_awake_min_velocity_3s=ict_v_rip_volume_awake_min_velocity_3s,
    )
    pad_capture_lane = _top_ftv_a_pad_capture_lane(
        evidence,
        move=move,
        pad_min_move_pct=top_ftv_a_pad_velocity_min_move_pct,
        pad_max_move_pct=top_ftv_a_pad_velocity_max_move_pct,
    )
    cvd_buying_ok = bool(evidence.get("cvdBuying"))
    if (
        not cvd_buying_ok
        and pad_capture_lane
        and top_ftv_a_pad_waive_cvd_when_volume_awake
        and bool(evidence.get("volumeAwaken") or evidence.get("ictVolumeAwakening"))
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
        cvd_buying_ok = True

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
        elif not cvd_buying_ok:
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
        elif v3 < effective_min_v3:
            top_ftv_a_reason = "top_ftv_a_velocity_3s_below_floor"
        elif v9 < effective_min_v9:
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
            elif _allocation_rank_blocks_ftv(
                require_allocation_rank_one=require_allocation_rank_one,
                allocation_rank=allocation_rank,
                evidence=evidence,
            ):
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
            if _allocation_rank_blocks_ftv(
                require_allocation_rank_one=require_allocation_rank_one,
                allocation_rank=allocation_rank,
                evidence=evidence,
            ):
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

    from app.engines.explosion_detector import effective_first_lift_trade_min_score

    peak_move_pct = _number(
        evidence.get("peakMovePct") or evidence.get("dailyMovePct") or 0
    )
    effective_first_lift_min = effective_first_lift_trade_min_score(
        tier=tier,
        peak_move_pct=peak_move_pct,
        first_lift_ready=bool(evidence.get("firstLift")),
        v_rip_ready=bool(evidence.get("vRipReady")),
        local_base_move_pct=move,
        default_min=first_lift_trade_min_score,
    )

    # First-lift / V-rip at local base with micro velocity pullback — ICT pad
    # already confirmed; shallow dip is base retest, not failed launch.
    if (
        first_lift_local_base_micro_pullback_enabled
        and micro_pullback
        and str(ranking.get("grade") or "").upper() in {"A", "B"}
        and tier in {"ELITE", "EXPLODING"}
        and explosion_score >= effective_first_lift_min
        and quality >= first_lift_helper_confirm_min_quality
    ):
        if _allocation_rank_blocks_ftv(
            require_allocation_rank_one=require_allocation_rank_one,
            allocation_rank=allocation_rank,
            evidence=evidence,
        ):
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

    # First-lift at local base when velocity snapshot is flat — ICT pad already
    # confirmed via volumeAwaken; do not wait for a hot v3 print on the next tick.
    if (
        first_lift_local_base_flat_velocity_enabled
        and flat_velocity_lag
        and grade in {"A", "B"}
        and tier in {"ELITE", "EXPLODING"}
        and explosion_score >= effective_first_lift_min
        and quality >= first_lift_helper_confirm_min_quality
    ):
        if _allocation_rank_blocks_ftv(
            require_allocation_rank_one=require_allocation_rank_one,
            allocation_rank=allocation_rank,
            evidence=evidence,
        ):
            return blocked("first_lift_local_base_requires_allocation_rank_1")
        expiry_block = _expiry_worst_policy_ok(
            tier=tier, quality=quality, score=explosion_score, v3=v3,
        )
        if expiry_block is not None:
            return expiry_block
        return FtvAuthorization(
            "FIRST_LIFT_LOCAL_BASE",
            "ok_flat_velocity_lag",
            max_capital_pct=winner_local_base_max_capital_pct,
        )

    # Pre-lift slow-coil pad — flat velocity, impending signals, BUILDING tier OK.
    slow_grind_pad = bool(evidence.get("slowGrindSuddenLift"))
    slow_grind_armed_trough = bool(evidence.get("slowGrindArmedTrough"))
    slow_grind_consolidation = bool(evidence.get("slowGrindConsolidationBase"))
    if slow_grind_ftv_enabled and slow_grind_pad:
        if slow_grind_armed_trough:
            slow_grind_ok = (
                str(ranking.get("grade") or "").upper() != "REJECT"
                and tier in {"WATCH", "BUILDING", "EXPLODING", "ELITE"}
                and explosion_score >= slow_grind_ftv_armed_trough_min_explosion_score
                and v3 >= -0.8
                and v3 <= 1.5
                and timing not in {"FAILED_LAUNCH", "FADED", "FADING", "EXHAUSTED"}
            )
        elif slow_grind_consolidation:
            slow_grind_ok = (
                str(ranking.get("grade") or "").upper() != "REJECT"
                and tier in {"WATCH", "BUILDING"}
                and explosion_score >= slow_grind_ftv_consolidation_base_min_explosion_score
                and quality >= slow_grind_ftv_consolidation_base_min_flat_quality
                and v3 >= -0.8
                and v3 <= 1.5
                and timing not in {"FAILED_LAUNCH", "FADED", "FADING", "EXHAUSTED"}
            )
        else:
            slow_grind_ok = (
                grade in {"A", "B", "S"}
                and tier in {"BUILDING", "EXPLODING", "ELITE"}
                and explosion_score >= slow_grind_ftv_min_explosion_score
                and quality >= slow_grind_ftv_min_flat_quality
                and v3 >= -0.8
                and v3 <= 1.5
                and timing not in {"FAILED_LAUNCH", "FADED", "FADING", "EXHAUSTED"}
            )
            if top_moments_only_enabled and grade == "B":
                slow_grind_ok = False
        if slow_grind_ok:
            if _allocation_rank_blocks_ftv(
                require_allocation_rank_one=require_allocation_rank_one,
                allocation_rank=allocation_rank,
                evidence=evidence,
            ):
                return blocked("slow_grind_ftv_requires_allocation_rank_1")
            expiry_block = _expiry_worst_policy_ok(
                tier=tier, quality=quality, score=explosion_score, v3=v3,
            )
            if expiry_block is not None:
                return expiry_block
            return FtvAuthorization(
                "SLOW_GRIND_FTV",
                "ok",
                max_capital_pct=slow_grind_ftv_max_capital_pct,
            )

    # Fast-bullish pad — momentum turn + volume awakening as lift starts.
    fast_bullish_pad = bool(evidence.get("fastBullishLocalBase"))
    if fast_bullish_ftv_enabled and fast_bullish_pad:
        fast_bullish_ok = (
            grade in {"A", "B", "S"}
            and tier in {"BUILDING", "EXPLODING", "ELITE"}
            and explosion_score >= fast_bullish_ftv_min_explosion_score
            and v3 >= fast_bullish_ftv_min_velocity_3s
            and timing not in {"FAILED_LAUNCH", "FADED", "FADING", "EXHAUSTED"}
        )
        if top_moments_only_enabled and grade == "B":
            fast_bullish_ok = False
        if fast_bullish_ok:
            if _allocation_rank_blocks_ftv(
                require_allocation_rank_one=require_allocation_rank_one,
                allocation_rank=allocation_rank,
                evidence=evidence,
            ):
                return blocked("fast_bullish_ftv_requires_allocation_rank_1")
            expiry_block = _expiry_worst_policy_ok(
                tier=tier, quality=quality, score=explosion_score, v3=v3,
            )
            if expiry_block is not None:
                return expiry_block
            return FtvAuthorization(
                "FAST_BULLISH_FTV",
                "ok",
                max_capital_pct=fast_bullish_ftv_max_capital_pct,
            )

    def _pad_lane_ftv_auth(
        *,
        enabled: bool,
        flag: bool,
        mode: str,
        min_score: float,
        max_capital: float,
        min_v3: float | None = None,
        max_v3: float | None = None,
        block_prefix: str,
    ) -> FtvAuthorization | None:
        if not (enabled and flag):
            return None
        ok = (
            grade in {"A", "B", "S"}
            and tier in {"BUILDING", "EXPLODING", "ELITE"}
            and explosion_score >= min_score
            and timing not in {"FAILED_LAUNCH", "FADED", "FADING", "EXHAUSTED"}
        )
        if min_v3 is not None and v3 < min_v3:
            ok = False
        if max_v3 is not None and v3 > max_v3:
            ok = False
        if top_moments_only_enabled and grade == "B":
            ok = False
        if not ok:
            return None
        if _allocation_rank_blocks_ftv(
            require_allocation_rank_one=require_allocation_rank_one,
            allocation_rank=allocation_rank,
            evidence=evidence,
        ):
            return blocked(f"{block_prefix}_requires_allocation_rank_1")
        expiry_block = _expiry_worst_policy_ok(
            tier=tier, quality=quality, score=explosion_score, v3=v3,
        )
        if expiry_block is not None:
            return expiry_block
        return FtvAuthorization(mode, "ok", max_capital_pct=max_capital)

    for auth in (
        _pad_lane_ftv_auth(
            enabled=squeeze_release_ftv_enabled,
            flag=bool(evidence.get("squeezeRelease")),
            mode="SQUEEZE_RELEASE_FTV",
            min_score=squeeze_release_ftv_min_explosion_score,
            max_capital=squeeze_release_ftv_max_capital_pct,
            max_v3=1.5,
            block_prefix="squeeze_release_ftv",
        ),
        _pad_lane_ftv_auth(
            enabled=index_led_option_lag_ftv_enabled,
            flag=bool(evidence.get("indexLedOptionLag")),
            mode="INDEX_LED_OPTION_LAG_FTV",
            min_score=index_led_option_lag_ftv_min_explosion_score,
            max_capital=index_led_option_lag_ftv_max_capital_pct,
            max_v3=1.2,
            block_prefix="index_led_option_lag_ftv",
        ),
        _pad_lane_ftv_auth(
            enabled=stealth_cvd_coil_ftv_enabled,
            flag=bool(evidence.get("stealthCvdCoil")),
            mode="STEALTH_CVD_COIL_FTV",
            min_score=stealth_cvd_coil_ftv_min_explosion_score,
            max_capital=stealth_cvd_coil_ftv_max_capital_pct,
            min_v3=-0.5,
            max_v3=1.0,
            block_prefix="stealth_cvd_coil_ftv",
        ),
        _pad_lane_ftv_auth(
            enabled=micro_pullback_retest_ftv_enabled,
            flag=bool(evidence.get("microPullbackRetest")),
            mode="MICRO_PULLBACK_RETEST_FTV",
            min_score=micro_pullback_retest_ftv_min_explosion_score,
            max_capital=micro_pullback_retest_ftv_max_capital_pct,
            min_v3=-1.2,
            max_v3=0.5,
            block_prefix="micro_pullback_retest_ftv",
        ),
        _pad_lane_ftv_auth(
            enabled=premium_fvg_pad_ftv_enabled,
            flag=bool(evidence.get("premiumFvgPad")),
            mode="PREMIUM_FVG_PAD_FTV",
            min_score=premium_fvg_pad_ftv_min_explosion_score,
            max_capital=premium_fvg_pad_ftv_max_capital_pct,
            max_v3=2.0,
            block_prefix="premium_fvg_pad_ftv",
        ),
        _pad_lane_ftv_auth(
            enabled=double_dip_vbase_ftv_enabled,
            flag=bool(evidence.get("doubleDipVbase")),
            mode="DOUBLE_DIP_VBASE_FTV",
            min_score=double_dip_vbase_ftv_min_explosion_score,
            max_capital=double_dip_vbase_ftv_max_capital_pct,
            min_v3=-0.8,
            max_v3=1.5,
            block_prefix="double_dip_vbase_ftv",
        ),
        _pad_lane_ftv_auth(
            enabled=early_radar_pad_ftv_enabled,
            flag=bool(evidence.get("earlyRadarPadCapture")),
            mode="EARLY_RADAR_PAD_FTV",
            min_score=early_radar_pad_ftv_min_explosion_score,
            max_capital=early_radar_pad_ftv_max_capital_pct,
            min_v3=-0.8,
            max_v3=1.5,
            block_prefix="early_radar_pad_ftv",
        ),
    ):
        if auth is not None:
            return auth

    if early_radar_pad_ftv_enabled and bool(evidence.get("earlyRadarPadCapture")):
        off_low = _number(evidence.get("offLowMovePct"))
        early_pad_ok = (
            str(ranking.get("grade") or "").upper() != "REJECT"
            and tier in {"WATCH", "BUILDING", "EXPLODING", "ELITE"}
            and explosion_score >= early_radar_pad_ftv_min_explosion_score
            and off_low <= early_radar_pad_max_off_low_pct + 5.0
            and -0.8 <= v3 <= 1.5
            and timing not in {"FAILED_LAUNCH", "FADED", "FADING", "EXHAUSTED"}
        )
        if early_pad_ok:
            if _allocation_rank_blocks_ftv(
                require_allocation_rank_one=require_allocation_rank_one,
                allocation_rank=allocation_rank,
                evidence=evidence,
            ):
                return blocked("early_radar_pad_ftv_requires_allocation_rank_1")
            expiry_block = _expiry_worst_policy_ok(
                tier=tier, quality=quality, score=explosion_score, v3=v3,
            )
            if expiry_block is not None:
                return expiry_block
            return FtvAuthorization(
                "EARLY_RADAR_PAD_FTV",
                "ok",
                max_capital_pct=early_radar_pad_ftv_max_capital_pct,
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
            if _allocation_rank_blocks_ftv(
                require_allocation_rank_one=require_allocation_rank_one,
                allocation_rank=allocation_rank,
                evidence=evidence,
            ):
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
        "top_ftv_a_pad_velocity_min_move_pct",
        "top_ftv_a_pad_velocity_max_move_pct",
        "top_ftv_a_pad_waive_cvd_when_volume_awake",
        "ict_v_rip_min_velocity_3s",
        "ict_v_rip_min_velocity_9s",
        "ict_v_rip_pad_min_move_pct",
        "ict_v_rip_volume_awake_min_velocity_3s",
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
        "slow_grind_ftv_enabled",
        "slow_grind_ftv_min_explosion_score",
        "slow_grind_ftv_min_flat_quality",
        "slow_grind_ftv_armed_trough_min_explosion_score",
        "slow_grind_ftv_consolidation_base_min_explosion_score",
        "slow_grind_ftv_consolidation_base_min_flat_quality",
        "slow_grind_ftv_max_capital_pct",
        "fast_bullish_ftv_enabled",
        "fast_bullish_ftv_min_explosion_score",
        "fast_bullish_ftv_min_velocity_3s",
        "fast_bullish_ftv_max_capital_pct",
        "squeeze_release_ftv_enabled",
        "squeeze_release_ftv_min_explosion_score",
        "squeeze_release_ftv_max_capital_pct",
        "index_led_option_lag_ftv_enabled",
        "index_led_option_lag_ftv_min_explosion_score",
        "index_led_option_lag_ftv_max_capital_pct",
        "stealth_cvd_coil_ftv_enabled",
        "stealth_cvd_coil_ftv_min_explosion_score",
        "stealth_cvd_coil_ftv_max_capital_pct",
        "micro_pullback_retest_ftv_enabled",
        "micro_pullback_retest_ftv_min_explosion_score",
        "micro_pullback_retest_ftv_max_capital_pct",
        "premium_fvg_pad_ftv_enabled",
        "premium_fvg_pad_ftv_min_explosion_score",
        "premium_fvg_pad_ftv_max_capital_pct",
        "double_dip_vbase_ftv_enabled",
        "double_dip_vbase_ftv_min_explosion_score",
        "double_dip_vbase_ftv_max_capital_pct",
        "early_radar_pad_ftv_enabled",
        "early_radar_pad_ftv_min_explosion_score",
        "early_radar_pad_ftv_max_capital_pct",
        "early_radar_pad_max_off_low_pct",
        "top_moments_only_enabled",
        "top_moments_min_grade",
        "first_lift_local_base_micro_pullback_enabled",
        "first_lift_local_base_micro_pullback_min_velocity_3s",
        "first_lift_local_base_micro_pullback_min_velocity_9s",
        "first_lift_local_base_flat_velocity_enabled",
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
        flat_velocity_lag = _first_lift_local_base_flat_velocity(
            evidence,
            enabled=bool(
                getattr(settings, "first_lift_local_base_flat_velocity_enabled", True)
            ),
            min_local_base_move_pct=float(
                getattr(settings, "winner_local_base_min_local_base_move_pct", 2.0) or 2.0
            ),
            max_local_base_move_pct=float(
                getattr(settings, "winner_local_base_max_local_base_move_pct", 25.0) or 25.0
            ),
            max_velocity_3s=float(
                getattr(settings, "ict_v_rip_volume_awake_min_velocity_3s", 0.85) or 0.85
            ),
        )
    except Exception:
        micro_pullback = _first_lift_local_base_micro_pullback(evidence)
        flat_velocity_lag = _first_lift_local_base_flat_velocity(evidence)

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
    fast_bullish_local_base = bool(evidence.get("fastBullishLocalBase")) and not bool(
        evidence.get("midRipCoil")
    )
    slow_grind_sudden_lift = bool(evidence.get("slowGrindSuddenLift")) and not bool(
        evidence.get("midRipCoil")
    )
    squeeze_release = bool(evidence.get("squeezeRelease")) and not bool(
        evidence.get("midRipCoil")
    )
    index_led_option_lag = bool(evidence.get("indexLedOptionLag")) and not bool(
        evidence.get("midRipCoil")
    )
    stealth_cvd_coil = bool(evidence.get("stealthCvdCoil")) and not bool(
        evidence.get("midRipCoil")
    )
    micro_pullback_retest = bool(evidence.get("microPullbackRetest")) and not bool(
        evidence.get("midRipCoil")
    )
    premium_fvg_pad = bool(evidence.get("premiumFvgPad")) and not bool(
        evidence.get("midRipCoil")
    )
    double_dip_vbase = bool(evidence.get("doubleDipVbase")) and not bool(
        evidence.get("midRipCoil")
    )
    early_radar_pad = bool(evidence.get("earlyRadarPadCapture")) and not bool(
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
        pad_flat = _pad_lane_cold_velocity_ok(evidence, v3, v9)
        if micro_pullback or pad_flat:
            score -= 5.0
            code = "first_lift_micro_pullback" if micro_pullback else "pad_lane_flat_coil"
            penalties.append({"code": code, "points": 5.0, "value": round(v3, 2)})
            reasons.append(f"{code}_v3_{v3:.2f}")
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
    elif double_dip_vbase:
        score += 11.0
        reasons.append("double_dip_vbase")
    elif early_radar_pad:
        score += 12.0
        reasons.append("early_radar_pad_ftv")
    elif fast_bullish_local_base:
        score += 11.0
        reasons.append("fast_bullish_local_base")
    elif slow_grind_sudden_lift:
        score += 12.0
        reasons.append("slow_grind_sudden_lift")
    elif squeeze_release:
        score += 11.0
        reasons.append("squeeze_release")
    elif index_led_option_lag:
        score += 11.0
        reasons.append("index_led_option_lag")
    elif stealth_cvd_coil:
        score += 10.0
        reasons.append("stealth_cvd_coil")
    elif micro_pullback_retest:
        score += 9.0
        reasons.append("micro_pullback_retest")
    elif premium_fvg_pad:
        score += 11.0
        reasons.append("premium_fvg_pad")
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
    if v3 < 0 and not micro_pullback and not _pad_lane_cold_velocity_ok(
        evidence, v3, v9
    ):
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
            or slow_grind_sudden_lift
            or fast_bullish_local_base
            or squeeze_release
            or index_led_option_lag
            or stealth_cvd_coil
            or micro_pullback_retest
            or premium_fvg_pad
            or double_dip_vbase
            or early_radar_pad
        )
        and (
            v3 > 0
            or flat_velocity_lag
            or _pad_lane_cold_velocity_ok(evidence, v3, v9)
            or (fast_bullish_local_base and v3 >= 0)
        )
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

    from app.engines.pad_lane_capture import pad_lane_grade_floor_applies

    if pad_lane_grade_floor_applies(evidence) and not exhausted and not bool(
        evidence.get("midRipCoil")
    ):
        if grade in {"REJECT", "C"}:
            grade = "A"
            score = max(score, 70.0)

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
            "fastBullishLocalBase": fast_bullish_local_base,
            "slowGrindSuddenLift": slow_grind_sudden_lift,
            "squeezeRelease": squeeze_release,
            "indexLedOptionLag": index_led_option_lag,
            "stealthCvdCoil": stealth_cvd_coil,
            "microPullbackRetest": micro_pullback_retest,
            "premiumFvgPad": premium_fvg_pad,
            "doubleDipVbase": double_dip_vbase,
            "earlyRadarPadCapture": early_radar_pad,
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
            "firstLiftLocalBaseFlatVelocity": flat_velocity_lag,
            "exhaustedReentry": exhausted,
            "faded": faded,
            "shallowOtmLocalBaseTradeable": bool(
                evidence.get("shallowOtmLocalBaseTradeable")
            ),
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
        "peakMovePct": (
            alert.get("peakMovePct")
            or (getattr(event, "peak_move_pct", 0) if event else 0)
            or alert.get("dailyMovePct")
            or 0
        ),
        "dailyMovePct": alert.get("dailyMovePct") or 0,
        "offLowMovePct": (
            alert.get("offLowMovePct")
            or pretrade.get("offLowMovePct")
        ),
        "firstLift": alert.get("ictFirstLift"),
        "eliteBaseReady": alert.get("ictEliteBaseReady"),
        "vRipReady": alert.get("ictVRipReady"),
        "fastBullishLocalBase": bool(
            alert.get("bullishLocalBaseActive")
            or alert.get("fastBullishLocalBaseReady")
        ),
        "slowGrindSuddenLift": bool(
            alert.get("slowGrindSuddenLiftReady")
            or alert.get("ictSlowGrindSuddenLift")
        ),
        "slowGrindArmedTrough": bool(
            alert.get("slowGrindArmedTrough")
            or alert.get("ictSlowGrindArmedTrough")
        ),
        "slowGrindConsolidationBase": bool(
            alert.get("slowGrindConsolidationBase")
            or alert.get("ictSlowGrindConsolidationBase")
        ),
        "squeezeRelease": bool(
            alert.get("squeezeReleaseReady") or alert.get("ictSqueezeRelease")
        ),
        "indexLedOptionLag": bool(
            alert.get("indexLedOptionLagReady") or alert.get("ictIndexLedOptionLag")
        ),
        "stealthCvdCoil": bool(
            alert.get("stealthCvdCoilReady") or alert.get("ictStealthCvdCoil")
        ),
        "microPullbackRetest": bool(
            alert.get("microPullbackRetestReady") or alert.get("ictMicroPullbackRetest")
        ),
        "premiumFvgPad": bool(
            alert.get("premiumFvgPadReady") or alert.get("ictPremiumFvgPad")
        ),
        "doubleDipVbase": bool(
            alert.get("doubleDipVbaseReady") or alert.get("ictDoubleDipVbase")
        ),
        "earlyRadarPadCapture": bool(
            alert.get("earlyRadarPadCapture") or alert.get("ictEarlyRadarPadCapture")
        ),
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
        "shallowOtmLocalBaseTradeable": bool(
            alert.get("shallowOtmLocalBaseTradeable")
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
