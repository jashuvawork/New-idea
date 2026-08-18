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


def ranking_sort_key(ranking: Mapping[str, Any]) -> tuple[int, float]:
    """Comparable causal ordering: grade first, then evidence score."""
    return (
        int(_number(ranking.get("gradePriority"))),
        _number(ranking.get("rankScore")),
    )


def ftv_authorization_policy(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    *,
    snapshot_available: bool = False,
    atm_itm_allowed: bool = True,
    allocation_rank: int | None = None,
    require_allocation_rank_one: bool = False,
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
    ftv_s_strict_min_explosion_score: float = 85.0,
    ftv_s_strict_min_quality: float = 70.0,
    ftv_s_strict_min_velocity_3s: float = 2.5,
    ftv_s_strict_min_velocity_9s: float = 1.75,
    ftv_s_strict_require_cvd_buying: bool = True,
    ftv_s_strict_min_local_base_move_pct: float = 5.0,
    ftv_s_strict_max_local_base_move_pct: float = 25.0,
) -> FtvAuthorization:
    """Pure causal authorization for strict S and winner-like top FTV A."""
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
    )
    if not actual_ftv:
        return blocked("ftv_elite_top_only_requires_ftv")

    timing = str(evidence.get("timingAssessment") or "").upper()
    timing_action = str(evidence.get("timingAction") or "").lower()
    if (
        str(ranking.get("grade") or "").upper() == "REJECT"
        or evidence.get("faded")
        or evidence.get("exhaustedReentry")
        or _number(evidence.get("velocity3s")) < 0
        or _number(evidence.get("velocity9s")) < 0
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

    grade = str(ranking.get("grade") or "").upper()
    if grade == "S":
        if not bool(ranking.get("topRankEligible")):
            return blocked("ftv_elite_top_only_requires_top_rank_eligible")
        if require_allocation_rank_one and allocation_rank != 1:
            return blocked("ftv_elite_top_only_requires_allocation_rank_1")
        # Elite-base preauth (2–5% pad) is already structured; armed/first-lift
        # S must still clear top local-base floors so mid EXPLODING cannot slip in.
        preauthorized = str(ranking.get("executionAuthorization") or "") == "S_PREAUTHORIZED"
        if not preauthorized:
            tier = str(evidence.get("tier") or "").upper()
            if tier not in {"ELITE", "EXPLODING"}:
                return blocked("ftv_s_strict_requires_elite_or_exploding")
            if not bool(
                evidence.get("armedBaseLaunch")
                or evidence.get("firstLift")
                or evidence.get("eliteBaseReady")
            ):
                return blocked("ftv_s_strict_requires_local_base_trigger")
            move = _number(evidence.get("localBaseMovePct"))
            if move < ftv_s_strict_min_local_base_move_pct:
                return blocked("ftv_s_strict_local_base_too_early")
            if move > ftv_s_strict_max_local_base_move_pct:
                return blocked("ftv_s_strict_local_base_chase")
            if _number(evidence.get("explosionScore")) < ftv_s_strict_min_explosion_score:
                return blocked("ftv_s_strict_explosion_score_below_floor")
            if _number(evidence.get("flatVerticalQuality")) < ftv_s_strict_min_quality:
                return blocked("ftv_s_strict_quality_below_floor")
            if _number(evidence.get("velocity3s")) < ftv_s_strict_min_velocity_3s:
                return blocked("ftv_s_strict_velocity_3s_below_floor")
            if _number(evidence.get("velocity9s")) < ftv_s_strict_min_velocity_9s:
                return blocked("ftv_s_strict_velocity_9s_below_floor")
            if ftv_s_strict_require_cvd_buying and not (
                bool(evidence.get("cvdBuying"))
                or bool(evidence.get("orderflowPositive"))
            ):
                return blocked("ftv_s_strict_requires_buying_confirmation")
        return FtvAuthorization("S_STRICT", "ok")

    if not top_ftv_a_enabled:
        return blocked("ftv_elite_top_only_requires_s")
    move = _number(evidence.get("localBaseMovePct"))
    if move > top_ftv_a_exceptional_max_move_pct:
        return blocked("top_ftv_a_extension_above_40pct")
    if grade != "A":
        return blocked("top_ftv_a_requires_a_grade")

    tier = str(evidence.get("tier") or "").upper()
    if tier not in {"ELITE", "EXPLODING"}:
        return blocked("top_ftv_a_requires_elite_or_exploding")
    if not bool(evidence.get("flatThenVertical") and evidence.get("activeBreakout")):
        return blocked("top_ftv_a_requires_active_ftv")
    if not bool(
        evidence.get("firstLift")
        or evidence.get("armedBaseLaunch")
        or evidence.get("eliteBaseReady")
    ):
        return blocked("top_ftv_a_requires_fresh_causal_trigger")
    timing_blocked = timing in {"CHASE", "CHASING", "LATE", "FAILED_LAUNCH"}
    if timing_blocked:
        return blocked("top_ftv_a_timing_blocked")
    if not bool(evidence.get("cvdBuying")):
        return blocked("top_ftv_a_requires_option_cvd_buying")
    if not bool(evidence.get("cvdAcceleration")):
        return blocked("top_ftv_a_requires_option_cvd_acceleration")

    explosion_score = _number(evidence.get("explosionScore"))
    quality = _number(evidence.get("flatVerticalQuality"))
    tqs = _number(evidence.get("tqs"))
    v3 = _number(evidence.get("velocity3s"))
    v9 = _number(evidence.get("velocity9s"))
    if explosion_score < top_ftv_a_min_explosion_score:
        return blocked("top_ftv_a_explosion_score_below_floor")
    if quality < top_ftv_a_min_quality:
        return blocked("top_ftv_a_quality_below_floor")
    if tqs < top_ftv_a_min_tqs:
        return blocked("top_ftv_a_tqs_below_floor")
    if v3 < top_ftv_a_min_velocity_3s:
        return blocked("top_ftv_a_velocity_3s_below_floor")
    if v9 < top_ftv_a_min_velocity_9s:
        return blocked("top_ftv_a_velocity_9s_below_floor")
    exceptional = move > top_ftv_a_normal_max_move_pct
    if exceptional and not (
        explosion_score >= top_ftv_a_exceptional_min_explosion_score
        and quality >= top_ftv_a_exceptional_min_quality
        and tqs >= top_ftv_a_exceptional_min_tqs
        and v3 >= top_ftv_a_exceptional_min_velocity_3s
        and v9 >= top_ftv_a_exceptional_min_velocity_9s
    ):
        return blocked("top_ftv_a_extended_requires_exceptional_acceleration")
    if require_allocation_rank_one and allocation_rank != 1:
        return blocked("top_ftv_a_requires_allocation_rank_1")
    return FtvAuthorization(
        "TOP_FTV_A",
        "ok_exceptional_extension" if exceptional else "ok",
        max_capital_pct=top_ftv_a_max_capital_pct,
        exceptional_extension=exceptional,
    )


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
        "ftv_s_strict_min_explosion_score",
        "ftv_s_strict_min_quality",
        "ftv_s_strict_min_velocity_3s",
        "ftv_s_strict_min_velocity_9s",
        "ftv_s_strict_require_cvd_buying",
        "ftv_s_strict_min_local_base_move_pct",
        "ftv_s_strict_max_local_base_move_pct",
    )
    return {name: getattr(settings, name) for name in names}


def rank_trade_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Grade one trade without using outcomes, exits, or future P&L."""
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
    elif local_move > 40.0:
        extension_penalty = min(45.0, (local_move - 40.0) * 1.4)
        score -= extension_penalty
        penalties.append(
            {
                "code": "extended_from_local_base",
                "points": round(extension_penalty, 1),
                "value": round(local_move, 1),
            }
        )

    rejected = False
    if timing == "FAILED_LAUNCH" or timing_action == "block" and v3 < 0:
        rejected = True
        penalties.append({"code": "failed_launch", "points": 45.0})
        score -= 45.0
    if v3 < 0:
        rejected = True
    if exhausted:
        rejected = True
        penalties.append({"code": "exhausted_post_peak_reentry", "points": 60.0})
        score -= 60.0

    elite_preauthorized = bool(
        elite_base_ready
        and tier in ("EXPLODING", "ELITE")
        and explosion_score >= 45.0
        and tqs >= 50.0
        and 2.0 <= local_move < 5.0
    )
    # Top S at local base only — armed launch alone must not mint grade S for
    # mid EXPLODING (score ~70, quality B). Elite-base preauth (2–5%) stays.
    # CVD is preferred; absolute volume / orderflow proof is enough when the CVD
    # tape is sparse (armed readiness already required one of those proofs).
    armed_top_local = bool(
        armed_launch
        and tier in ("ELITE", "EXPLODING")
        and explosion_score >= 85.0
        and flat_vertical_quality >= 70.0
        and v3 >= 2.5
        and v9 >= 1.75
        and orderflow
        and (cvd_buying or orderflow)
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
        and (first_lift or flat_vertical or armed_launch or elite_base_ready)
        and v3 > 0
        and not rejected
        and local_move <= 40.0
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
            "armedBaseLaunch": armed_launch,
            "flatThenVertical": flat_vertical,
            "activeBreakout": active_breakout,
            "orderflowPositive": orderflow,
            "cvdBuying": cvd_buying,
            "cvdAcceleration": cvd_acceleration,
            "explosionScore": round(explosion_score, 2),
            "flatVerticalQuality": round(flat_vertical_quality, 2),
            "tqs": round(tqs, 2),
            "timingAssessment": timing or None,
            "timingAction": timing_action or None,
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
        "firstLift": alert.get("ictFirstLift"),
        "eliteBaseReady": alert.get("ictEliteBaseReady"),
        "armedBaseLaunch": alert.get("ictArmedBaseLaunch"),
        "flatThenVertical": alert.get("ictFlatThenVertical"),
        "activeBreakout": alert.get("ictBreakout"),
        "orderflowPositive": bool(
            alert.get("ictVolumeAwakening")
            or alert.get("volumeAwaken")
            or alert.get("cvdBuying")
            or alert.get("cvdAcceleration")
            or volume_surge >= 1.2
        ),
        "cvdBuying": cvd_buying,
        "cvdAcceleration": cvd_acceleration,
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
    return rank_trade_evidence(evidence)
