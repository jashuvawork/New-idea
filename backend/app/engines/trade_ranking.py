"""Comparable causal trade ranking from evidence available before entry."""

from __future__ import annotations

from typing import Any, Mapping


GRADE_PRIORITY = {"REJECT": 0, "C": 1, "B": 2, "A": 3, "S": 4}


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


def ftv_elite_top_policy(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    *,
    snapshot_available: bool = False,
    atm_itm_allowed: bool = True,
    allocation_rank: int | None = None,
    require_allocation_rank_one: bool = False,
) -> tuple[bool, str]:
    """Pure causal authorization for the hard FTV elite-top execution policy."""
    if str(evidence.get("mode") or "").lower() != "explosion":
        return False, "ftv_elite_top_only_requires_explosion"

    actual_ftv = bool(
        (
            evidence.get("flatThenVertical")
            and evidence.get("activeBreakout")
        )
        or evidence.get("eliteBaseReady")
        or evidence.get("armedBaseLaunch")
    )
    if not actual_ftv:
        return False, "ftv_elite_top_only_requires_ftv"

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
        return False, "ftv_elite_top_only_timing_blocked"

    if str(ranking.get("grade") or "").upper() != "S":
        return False, "ftv_elite_top_only_requires_s"
    if not bool(ranking.get("topRankEligible")):
        return False, "ftv_elite_top_only_requires_top_rank_eligible"
    if snapshot_available and not atm_itm_allowed:
        return False, "ftv_elite_top_only_requires_atm_itm"
    if require_allocation_rank_one and allocation_rank != 1:
        return False, "ftv_elite_top_only_requires_allocation_rank_1"
    return True, "ok"


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
        and tier in ("BUILDING", "EXPLODING", "ELITE")
        and explosion_score >= 45.0
        and tqs >= 50.0
        and 2.0 <= local_move < 5.0
    )
    s_quality = bool(
        mode == "explosion"
        and (armed_launch or elite_preauthorized)
        and v3 >= 1.5
        and v9 >= 1.5
        and orderflow
        and not rejected
        and local_move <= 40.0
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
) -> dict[str, Any]:
    """Adapt a selector candidate to the pure causal scorecard."""
    alert = candidate.alert if isinstance(getattr(candidate, "alert", None), dict) else {}
    event = getattr(candidate, "explosion_event", None)
    pretrade = getattr(candidate, "pretrade_meta", None) or {}
    timing = pretrade.get("timingAssessment") or {}
    if not isinstance(timing, Mapping):
        timing = {"assessment": timing}
    chart_confidence = 0.0
    try:
        from app.engines.chart_exit_levels import chart_trade_confidence

        chart_confidence, _ = chart_trade_confidence(candidate.snap, candidate.side)
    except Exception:
        chart_confidence = 0.0
    volume_surge = _number(getattr(event, "volume_surge", 0) if event else 0)
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
