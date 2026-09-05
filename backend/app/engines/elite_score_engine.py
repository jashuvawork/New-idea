"""Unified EliteScore pipeline — setup type, stage, score, and entry gate.

Setup types (priority FTV > V > EXPLOSIVE) are distinct from the legacy
velocity tier labels ELITE/EXPLODING.  EliteScore blends causal rank, FTV
quality, momentum, structure, and near-base window into a 0–100 score.

Live entry rule (hybrid model):
  - Setup ∈ {FTV, V, EXPLOSIVE}
  - EliteScore ≥ min (default 90)
  - Stage ≥ ARMED
  - Near-base ≤ max local move (default 25%)
  - Timing ∈ {GOOD, OK}
  - Weekly cap enforced separately via elite_trade_budget
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.engines.top_moment_gate import classify_top_moment_type

STAGE_RANK = {"BASE": 0, "ARMED": 1, "TRIGGERED": 2, "EXPANDING": 3}
SETUP_PRIORITY = {"FTV": 0, "V": 1, "EXPLOSIVE": 2, "OTHER": 9}
VALID_SETUPS = frozenset({"FTV", "V", "EXPLOSIVE"})
GOOD_TIMING = frozenset({"GOOD", "OK"})


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def infer_setup_type(
    evidence: Mapping[str, Any],
    moment: Optional[str] = None,
) -> str:
    """Return FTV | V | EXPLOSIVE | OTHER from causal evidence."""
    if bool(evidence.get("vRipReady")) and not bool(evidence.get("midRipCoil")):
        return "V"
    if bool(evidence.get("flatThenVertical")):
        return "FTV"
    if moment is None:
        moment = classify_top_moment_type(evidence)
    if moment == "V":
        return "V"
    if moment == "FTV":
        return "FTV"
    tier = str(evidence.get("tier") or "").upper()
    if tier in ("ELITE", "EXPLODING") or moment in ("ELITE", "EXPLODING"):
        return "EXPLOSIVE"
    if bool(evidence.get("buildingRipReady")) or bool(evidence.get("displacement")):
        return "EXPLOSIVE"
    return "OTHER"


def infer_stage(evidence: Mapping[str, Any]) -> str:
    """Return BASE | ARMED | TRIGGERED | EXPANDING."""
    tier = str(evidence.get("tier") or "").upper()
    v3 = _number(evidence.get("velocity3s"))
    if tier in ("ELITE", "EXPLODING") or v3 >= 3.0:
        return "EXPANDING"
    if (
        bool(evidence.get("firstLift"))
        or bool(evidence.get("activeBreakout"))
        or bool(evidence.get("displacement"))
    ):
        return "TRIGGERED"
    if bool(evidence.get("armedBaseLaunch")) or bool(evidence.get("eliteBaseReady")):
        return "ARMED"
    if bool(evidence.get("baseArmed")):
        return "BASE"
    return "BASE"


def elite_score_band(score: float) -> str:
    if score >= 95:
        return "ELITE A+"
    if score >= 90:
        return "ELITE"
    if score >= 80:
        return "WATCH"
    return "NO TRADE"


def compute_elite_score(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    *,
    setup: Optional[str] = None,
) -> tuple[float, str, dict[str, float]]:
    """Unified 0–100 EliteScore from causal rank + FTV quality + flow."""
    if setup is None:
        setup = infer_setup_type(evidence)

    parts: dict[str, float] = {}
    rank_score = _number(ranking.get("rankScore"))
    fv_q = _number(evidence.get("flatVerticalQuality"))
    exp_score = _number(evidence.get("explosionScore"))
    local = _number(evidence.get("localBaseMovePct"))
    grade = str(ranking.get("grade") or "C").upper()

    parts["causalRank"] = round(min(40.0, rank_score * 0.4), 1)
    parts["ftvQuality"] = round(min(25.0, fv_q * 0.25), 1)
    parts["momentum"] = round(min(15.0, exp_score * 0.15), 1)
    parts["setupType"] = {"FTV": 12.0, "V": 9.0, "EXPLOSIVE": 6.0}.get(setup, 0.0)

    struct = 0.0
    if evidence.get("armedBaseLaunch") or evidence.get("eliteBaseReady"):
        struct += 5.0
    if evidence.get("baseArmed"):
        struct += 3.0
    if evidence.get("volumeAwaken") or evidence.get("indexHelpersConfirm"):
        struct += 4.0
    parts["structureFlow"] = min(10.0, struct)

    parts["gradeLift"] = {"S": 8.0, "A": 5.0, "B": 0.0, "C": -5.0}.get(grade, -8.0)

    if 5.0 <= local <= 20.0:
        parts["nearBase"] = 5.0
    elif local <= 25.0:
        parts["nearBase"] = 2.0
    elif local > 40.0:
        parts["nearBase"] = -12.0
    elif local > 30.0:
        parts["nearBase"] = -6.0
    else:
        parts["nearBase"] = 0.0

    total = max(0.0, min(100.0, sum(parts.values())))
    return round(total, 1), elite_score_band(total), parts


def build_elite_assessment(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    *,
    moment: Optional[str] = None,
) -> dict[str, Any]:
    """Full EliteScore assessment for observability and gating."""
    if moment is None:
        moment = classify_top_moment_type(evidence)
    setup = infer_setup_type(evidence, moment=moment)
    stage = infer_stage(evidence)
    score, band, parts = compute_elite_score(evidence, ranking, setup=setup)
    timing = str(evidence.get("timingAssessment") or "").upper()
    local = _number(evidence.get("localBaseMovePct"))

    return {
        "setup": setup,
        "stage": stage,
        "stageRank": STAGE_RANK.get(stage, 0),
        "setupPriority": SETUP_PRIORITY.get(setup, 9),
        "momentType": moment,
        "eliteScore": score,
        "eliteBand": band,
        "scoreParts": parts,
        "localBasePct": round(local, 2),
        "timing": timing,
        "grade": str(ranking.get("grade") or "").upper(),
    }


def _timing_ok(evidence: Mapping[str, Any]) -> bool:
    timing = str(evidence.get("timingAssessment") or "").upper()
    timing_action = str(evidence.get("timingAction") or "").lower()
    if timing_action in {"block", "reject"}:
        return False
    if timing in {
        "FAILED_LAUNCH",
        "FADED",
        "FADING",
        "EXHAUSTED",
        "NEGATIVE",
        "REJECT",
        "BLOCKED",
        "CHASE",
        "LATE",
    }:
        return False
    return timing in GOOD_TIMING


def elite_must_take(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    assessment: Mapping[str, Any],
    *,
    settings: Any = None,
) -> bool:
    """Grade-S FTV at elite flat-vertical quality near base — bypass weekly cap."""
    from app.config import get_settings

    settings = settings or get_settings()
    if not bool(getattr(settings, "elite_trade_must_take_enabled", True)):
        return False
    min_grade = str(getattr(settings, "elite_trade_must_take_min_grade", "S") or "S").upper()
    if str(ranking.get("grade") or "").upper() != min_grade:
        return False
    if str(assessment.get("setup") or "") != "FTV":
        return False
    fvq = _number(evidence.get("flatVerticalQuality"))
    min_fvq = float(getattr(settings, "elite_trade_must_take_min_fvq", 85.0) or 85.0)
    if fvq < min_fvq:
        return False
    local = _number(evidence.get("localBaseMovePct"))
    max_local = float(
        getattr(settings, "elite_trade_must_take_max_local_base_pct", 15.0) or 15.0
    )
    return local <= max_local + 1e-6


def elite_entry_allowed(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    *,
    settings: Any = None,
    readiness_reason: str = "",
) -> tuple[bool, str, dict[str, Any]]:
    """True when candidate passes the unified EliteScore entry rule."""
    from app.config import get_settings

    settings = settings or get_settings()

    from app.engines.building_ftv_gates import (
        building_armed_base_grade_a_top_moment_ok,
        building_coil_pad_grade_a_top_moment_ok,
    )

    if building_armed_base_grade_a_top_moment_ok(
        evidence, ranking, readiness_reason=readiness_reason,
    ) or building_coil_pad_grade_a_top_moment_ok(
        evidence, ranking, readiness_reason=readiness_reason,
    ):
        assessment = build_elite_assessment(evidence, ranking)
        assessment = {
            **assessment,
            "mustTake": elite_must_take(evidence, ranking, assessment, settings=settings),
            "legacyBypass": "building_ftv_gate",
        }
        return True, "ok", assessment

    assessment = build_elite_assessment(evidence, ranking)

    min_score = float(getattr(settings, "elite_trade_min_score", 90.0) or 90.0)
    max_local = float(getattr(settings, "elite_trade_max_local_base_pct", 25.0) or 25.0)
    min_stage = str(getattr(settings, "elite_trade_min_stage", "ARMED") or "ARMED").upper()
    min_stage_rank = STAGE_RANK.get(min_stage, STAGE_RANK["ARMED"])

    setup = str(assessment.get("setup") or "")
    if setup not in VALID_SETUPS:
        return False, "elite_setup_not_ftv_v_or_explosive", assessment

    score = float(assessment.get("eliteScore") or 0)
    if score < min_score - 1e-6:
        return False, f"elite_score_below_{min_score:g}", assessment

    if int(assessment.get("stageRank") or 0) < min_stage_rank:
        return False, f"elite_stage_below_{min_stage.lower()}", assessment

    local = _number(assessment.get("localBasePct"))
    if local > max_local + 1e-6:
        return False, "elite_chase_past_local_base_window", assessment

    if not _timing_ok(evidence):
        return False, "elite_timing_not_good_or_ok", assessment

    assessment = {
        **assessment,
        "mustTake": elite_must_take(evidence, ranking, assessment, settings=settings),
    }
    return True, "ok", assessment
