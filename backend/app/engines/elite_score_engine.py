"""Unified EliteScore pipeline — setup type, stage, score, and entry gate.

Setup types (priority FTV > V > EXPLOSIVE) are distinct from the legacy
velocity tier labels ELITE/EXPLODING.  EliteScore blends causal rank, FTV
quality, momentum, structure, and near-base window into a 0–100 score.

Live entry rule (hybrid model):
  - Setup ∈ {FTV, V, EXPLOSIVE}
  - EliteScore ≥ min (default 90)
  - Stage ≥ ARMED
  - Near-base ≤ max local move (default 20%; CALL default 10%)
  - Timing ∈ {GOOD, OK}
  - CALL blocked on MOMENTUM RALLY when elite_call_block_momentum_rally_enabled
  - PUT blocked on BULLISH DAY when elite_put_block_bullish_day_enabled (optional PE mirror)
  - Rounded score=100 blocked when local > perfect_score_max_local (default 15%)
  - Weekly cap enforced separately via elite_trade_budget
  - MOMENTUM RALLY + dayType WORST blocked when elite_trade_block_worst_day_type_enabled
    (CHOP + RALLY + WORST still allowed — EOD: +₹214k on that bucket)
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


def resolve_elite_session_day_type(
    state: Any = None,
    snapshots: Any = None,
    *,
    day_mode: str = "",
    confidence_tier: str = "",
) -> tuple[str, str]:
    """Resolve (dayMode, dayType) for Elite gate — mirrors live chop/adaptive stack."""
    dm = str(day_mode or "").strip().upper()
    if not dm and snapshots:
        from app.engines.chop_day_guards import resolve_session_day_mode

        dm = str(resolve_session_day_mode(snapshots) or "").upper()
    if not dm and state is not None:
        ds = getattr(state, "dailyStrategy", None) or {}
        if isinstance(ds, dict):
            dm = str(ds.get("dayMode") or "").upper()

    tier = str(confidence_tier or "").upper()
    if not tier and state is not None:
        ds = getattr(state, "dailyStrategy", None) or {}
        if isinstance(ds, dict):
            tier = str(ds.get("confidenceTier") or "").upper()
    if not tier:
        try:
            from app.engines.daily_18pct_strategy import get_session_limits

            limits = get_session_limits()
            tier = str(getattr(limits, "confidenceTier", "") or "MEDIUM").upper()
        except Exception:
            tier = "MEDIUM"

    from app.engines.day_adaptive_engine import classify_day_type

    snaps = snapshots if isinstance(snapshots, dict) else {}
    day_type = classify_day_type(dm, tier, snaps, state=state)
    return dm, str(day_type or "NORMAL").upper()


_MOMENTUM_RALLY_DAY_MODE = "MOMENTUM RALLY"
_BULLISH_DAY_MODE = "BULLISH DAY"
_CHOP_DAY_MODES = frozenset({
    "CHOP DAY",
    "CHOP (PRE-10)",
    "EXPIRY WORST",
    "EXPIRY DAY",
    "CHOP + RALLY",
})
_TREND_DAY_MODES = frozenset({
    _MOMENTUM_RALLY_DAY_MODE,
    _BULLISH_DAY_MODE,
    "BEARISH DAY",
})


def _resolve_side(evidence: Mapping[str, Any], side: str = "") -> str:
    raw = side or evidence.get("side") or ""
    return str(raw).strip().upper()


def elite_side_local_base_cap(side: str, *, settings: Any = None) -> float:
    """Return max local-base % for side (CALL tighter than PUT by default)."""
    from app.config import get_settings

    settings = settings or get_settings()
    general = float(getattr(settings, "elite_trade_max_local_base_pct", 20.0) or 20.0)
    side_u = str(side or "").upper()
    if side_u == "CALL":
        call_cap = float(getattr(settings, "elite_call_max_local_base_pct", 0.0) or 0.0)
        if call_cap > 0:
            return min(general, call_cap)
    elif side_u == "PUT":
        put_cap = float(getattr(settings, "elite_put_max_local_base_pct", 0.0) or 0.0)
        if put_cap > 0:
            return min(general, put_cap)
    return general


def elite_side_day_mode_blocked(
    side: str,
    day_mode: str,
    *,
    settings: Any = None,
) -> tuple[bool, str]:
    """Side-specific day-mode blocks (CE/PE symmetric config, EOD-tuned defaults)."""
    from app.config import get_settings

    settings = settings or get_settings()
    side_u = str(side or "").upper()
    dm = str(day_mode or "").strip().upper()

    if (
        side_u == "CALL"
        and bool(getattr(settings, "elite_call_block_momentum_rally_enabled", True))
        and dm == _MOMENTUM_RALLY_DAY_MODE
    ):
        return True, "elite_call_momentum_rally_blocked"

    if (
        side_u == "PUT"
        and bool(getattr(settings, "elite_put_block_bullish_day_enabled", False))
        and dm == _BULLISH_DAY_MODE
    ):
        return True, "elite_put_bullish_day_blocked"

    return False, ""


def elite_perfect_score_blocked(
    score: float,
    local_base_pct: float,
    *,
    settings: Any = None,
) -> tuple[bool, str]:
    """Block rounded score=100 chase entries unless still near base."""
    from app.config import get_settings

    settings = settings or get_settings()
    if not bool(getattr(settings, "elite_trade_block_perfect_score_enabled", True)):
        return False, ""
    threshold = float(
        getattr(settings, "elite_trade_perfect_score_threshold", 99.95) or 99.95
    )
    max_local = float(
        getattr(settings, "elite_trade_perfect_score_max_local_pct", 15.0) or 15.0
    )
    if score >= threshold - 1e-6 and local_base_pct > max_local + 1e-6:
        return True, "elite_perfect_score_chase_blocked"
    return False, ""


def _lift_confirmed(evidence: Mapping[str, Any]) -> bool:
    return bool(
        evidence.get("firstLift")
        or evidence.get("activeBreakout")
        or evidence.get("displacement")
    )


def _effective_fvq_ceiling(
    evidence: Mapping[str, Any],
    assessment: Mapping[str, Any],
    *,
    settings: Any = None,
    side: str = "",
) -> float:
    """Default FVQ ceiling with calibrated PUT V-RIP near-base lift path."""
    from app.config import get_settings

    settings = settings or get_settings()
    ceiling = float(getattr(settings, "elite_trade_block_fvq_above", 0.0) or 0.0)
    if ceiling <= 0:
        return 0.0
    side_u = str(side or evidence.get("side") or "").upper()
    setup = str(assessment.get("setup") or infer_setup_type(evidence))
    local = _number(assessment.get("localBasePct"))
    lift_max = float(
        getattr(settings, "elite_fvq_put_v_rip_lift_max_local_pct", 15.0) or 15.0
    )
    lift_ceiling = float(
        getattr(settings, "elite_fvq_put_v_rip_lift_ceiling", 85.0) or 85.0
    )
    if (
        side_u == "PUT"
        and setup == "V"
        and _lift_confirmed(evidence)
        and local <= lift_max + 1e-6
        and lift_ceiling > ceiling + 1e-6
    ):
        return lift_ceiling
    return ceiling


def elite_fvq_chase_blocked(
    evidence: Mapping[str, Any],
    *,
    settings: Any = None,
    must_take: bool = False,
    readiness_reason: str = "",
    assessment: Mapping[str, Any] | None = None,
    side: str = "",
) -> tuple[bool, str]:
    """Block entries with flatVerticalQuality above ceiling (EOD: 80+ chase loses)."""
    from app.config import get_settings
    from app.engines.building_ftv_gates import ARMED_BASE_GRADE_A_READY_REASONS

    settings = settings or get_settings()
    if must_take:
        return False, ""
    rr = str(
        readiness_reason
        or evidence.get("firstLiftReadinessReason")
        or evidence.get("ictBaseReadinessReason")
        or ""
    )
    if rr in ARMED_BASE_GRADE_A_READY_REASONS:
        return False, ""
    assess = assessment or build_elite_assessment(evidence, {})
    ceiling = _effective_fvq_ceiling(
        evidence, assess, settings=settings, side=side,
    )
    if ceiling <= 0:
        return False, ""
    fvq = _number(evidence.get("flatVerticalQuality"))
    if fvq > ceiling + 1e-6:
        return True, "elite_fvq_chase_above_ceiling"
    return False, ""


def elite_call_chop_shallow_blocked(
    side: str,
    day_mode: str,
    local_base_pct: float,
    *,
    settings: Any = None,
) -> tuple[bool, str]:
    """Block CALL entries on chop days while still very near base."""
    from app.config import get_settings

    settings = settings or get_settings()
    if not bool(getattr(settings, "elite_call_chop_shallow_block_enabled", True)):
        return False, ""
    if str(side or "").upper() != "CALL":
        return False, ""
    dm = str(day_mode or "").strip().upper()
    if dm not in _CHOP_DAY_MODES and "CHOP" not in dm:
        return False, ""
    max_local = float(
        getattr(settings, "elite_call_chop_shallow_max_local_pct", 10.0) or 10.0
    )
    if local_base_pct <= max_local + 1e-6:
        return True, "elite_call_chop_shallow_blocked"
    return False, ""


def elite_v_rip_shallow_lift_blocked(
    evidence: Mapping[str, Any],
    assessment: Mapping[str, Any],
    *,
    settings: Any = None,
    readiness_reason: str = "",
) -> tuple[bool, str]:
    """V-RIP near base must show firstLift — tier breakout alone is not enough."""
    from app.config import get_settings
    from app.engines.building_ftv_gates import ARMED_BASE_GRADE_A_READY_REASONS

    settings = settings or get_settings()
    if not bool(getattr(settings, "elite_v_rip_shallow_require_first_lift_enabled", True)):
        return False, ""
    if str(assessment.get("setup") or "") != "V":
        return False, ""
    if bool(evidence.get("armedBaseLaunch")):
        return False, ""
    rr = str(
        readiness_reason
        or evidence.get("firstLiftReadinessReason")
        or ""
    )
    if rr in ARMED_BASE_GRADE_A_READY_REASONS:
        return False, ""
    max_local = float(
        getattr(settings, "elite_trade_shallow_lift_max_local_pct", 10.0) or 10.0
    )
    local = _number(assessment.get("localBasePct"))
    if local > max_local + 1e-6:
        return False, ""
    if bool(evidence.get("firstLift")):
        return False, ""
    return True, "elite_v_rip_shallow_first_lift_blocked"


def elite_shallow_lift_blocked(
    evidence: Mapping[str, Any],
    assessment: Mapping[str, Any],
    *,
    settings: Any = None,
) -> tuple[bool, str]:
    """Block very shallow local-base entries until stage confirms lift (not first tick)."""
    from app.config import get_settings

    settings = settings or get_settings()
    if not bool(getattr(settings, "elite_trade_shallow_lift_block_enabled", True)):
        return False, ""
    max_local = float(
        getattr(settings, "elite_trade_shallow_lift_max_local_pct", 10.0) or 10.0
    )
    local = _number(assessment.get("localBasePct"))
    if local > max_local + 1e-6:
        return False, ""
    if _lift_confirmed(evidence):
        return False, ""
    return True, "elite_shallow_first_lift_blocked"


def elite_milestone_depth_blocked(
    evidence: Mapping[str, Any],
    *,
    settings: Any = None,
) -> tuple[bool, str]:
    """Require minimum radar milestone depth when count is present on evidence."""
    from app.config import get_settings

    settings = settings or get_settings()
    min_depth = int(getattr(settings, "elite_trade_min_milestone_depth", 0) or 0)
    if min_depth <= 0:
        return False, ""
    if "milestoneCount" not in evidence:
        return False, ""
    count = int(evidence.get("milestoneCount") or 0)
    if count < min_depth:
        return True, "elite_milestone_depth_below_min"
    return False, ""


def elite_win_rate_gate_summary(*, settings: Any = None) -> dict[str, Any]:
    """Observability for deployment HUD — win-rate gate knobs."""
    from app.config import get_settings

    settings = settings or get_settings()
    return {
        "maxLocalBasePct": float(
            getattr(settings, "elite_trade_max_local_base_pct", 20.0) or 20.0
        ),
        "callMaxLocalBasePct": float(
            getattr(settings, "elite_call_max_local_base_pct", 10.0) or 10.0
        ),
        "putMaxLocalBasePct": float(
            getattr(settings, "elite_put_max_local_base_pct", 0.0) or 0.0
        ),
        "callBlockMomentumRally": bool(
            getattr(settings, "elite_call_block_momentum_rally_enabled", True)
        ),
        "putBlockBullishDay": bool(
            getattr(settings, "elite_put_block_bullish_day_enabled", False)
        ),
        "blockPerfectScore": bool(
            getattr(settings, "elite_trade_block_perfect_score_enabled", True)
        ),
        "perfectScoreMaxLocalPct": float(
            getattr(settings, "elite_trade_perfect_score_max_local_pct", 15.0) or 15.0
        ),
        "vRipOnly": bool(getattr(settings, "elite_trade_v_rip_only_enabled", True)),
        "blockFvqAbove": float(getattr(settings, "elite_trade_block_fvq_above", 80.0) or 80.0),
        "shallowLiftBlock": bool(
            getattr(settings, "elite_trade_shallow_lift_block_enabled", True)
        ),
        "shallowLiftMaxLocalPct": float(
            getattr(settings, "elite_trade_shallow_lift_max_local_pct", 10.0) or 10.0
        ),
        "minMilestoneDepth": int(getattr(settings, "elite_trade_min_milestone_depth", 0) or 0),
        "callChopShallowBlock": bool(
            getattr(settings, "elite_call_chop_shallow_block_enabled", True)
        ),
        "vRipShallowRequireFirstLift": bool(
            getattr(settings, "elite_v_rip_shallow_require_first_lift_enabled", True)
        ),
        "fvqPutVRipLiftCeiling": float(
            getattr(settings, "elite_fvq_put_v_rip_lift_ceiling", 85.0) or 85.0
        ),
        "trendDayBonusSlot": bool(
            getattr(settings, "elite_trend_day_bonus_slot_enabled", True)
        ),
    }


def elite_trend_day_bonus_allowed(
    assessment: Mapping[str, Any],
    *,
    settings: Any = None,
) -> bool:
    """True when this entry qualifies for the extra trend-day weekly slot."""
    from app.config import get_settings

    settings = settings or get_settings()
    if not bool(getattr(settings, "elite_trend_day_bonus_slot_enabled", True)):
        return False
    min_score = float(
        getattr(settings, "elite_trend_day_bonus_min_score", 98.0) or 98.0
    )
    if float(assessment.get("eliteScore") or 0) < min_score - 1e-6:
        return False
    modes_raw = str(
        getattr(settings, "elite_trend_day_bonus_day_modes", "") or ""
    )
    allowed = {
        m.strip().upper()
        for m in modes_raw.split(",")
        if m.strip()
    } or _TREND_DAY_MODES
    dm = str(assessment.get("dayMode") or "").strip().upper()
    return dm in allowed


def elite_worst_day_type_blocked(
    day_type: str,
    *,
    day_mode: str = "",
    settings: Any = None,
) -> tuple[bool, str]:
    """True when MOMENTUM RALLY + WORST dayType should block Elite entry.

    CHOP + RALLY sessions can still classify as WORST dayType but remain tradable
    (Sep EOD: that bucket was +₹214k vs MOMENTUM RALLY/WORST −₹1.45M).
    """
    from app.config import get_settings

    settings = settings or get_settings()
    if not bool(getattr(settings, "elite_trade_block_worst_day_type_enabled", True)):
        return False, ""
    if str(day_type or "").upper() != "WORST":
        return False, ""
    dm = str(day_mode or "").strip().upper()
    if dm == _MOMENTUM_RALLY_DAY_MODE:
        return True, "elite_momentum_rally_worst_blocked"
    return False, ""


def elite_entry_allowed(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    *,
    settings: Any = None,
    readiness_reason: str = "",
    day_mode: str = "",
    day_type: str = "",
    state: Any = None,
    snapshots: Any = None,
    confidence_tier: str = "",
    side: str = "",
) -> tuple[bool, str, dict[str, Any]]:
    """True when candidate passes the unified EliteScore entry rule."""
    from app.config import get_settings

    settings = settings or get_settings()

    resolved_mode, resolved_type = resolve_elite_session_day_type(
        state,
        snapshots,
        day_mode=day_mode or str(evidence.get("dayMode") or ""),
        confidence_tier=confidence_tier,
    )
    if day_type:
        resolved_type = str(day_type).upper()

    blocked, block_reason = elite_worst_day_type_blocked(
        resolved_type,
        day_mode=resolved_mode,
        settings=settings,
    )
    if blocked:
        assessment = build_elite_assessment(evidence, ranking)
        assessment = {
            **assessment,
            "dayMode": resolved_mode,
            "dayType": resolved_type,
        }
        return False, block_reason, assessment

    resolved_side = _resolve_side(
        evidence,
        side or str(ranking.get("side") or ""),
    )
    side_blocked, side_block_reason = elite_side_day_mode_blocked(
        resolved_side,
        resolved_mode,
        settings=settings,
    )
    if side_blocked:
        assessment = build_elite_assessment(evidence, ranking)
        assessment = {
            **assessment,
            "dayMode": resolved_mode,
            "dayType": resolved_type,
            "side": resolved_side,
        }
        return False, side_block_reason, assessment

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
            "dayMode": resolved_mode,
            "dayType": resolved_type,
        }
        return True, "ok", assessment

    assessment = build_elite_assessment(evidence, ranking)
    assessment = {**assessment, "dayMode": resolved_mode, "dayType": resolved_type}

    min_score = float(getattr(settings, "elite_trade_min_score", 90.0) or 90.0)
    max_local = elite_side_local_base_cap(resolved_side, settings=settings)
    min_stage = str(getattr(settings, "elite_trade_min_stage", "ARMED") or "ARMED").upper()
    min_stage_rank = STAGE_RANK.get(min_stage, STAGE_RANK["ARMED"])

    setup = str(assessment.get("setup") or "")
    if setup not in VALID_SETUPS:
        return False, "elite_setup_not_ftv_v_or_explosive", assessment

    if bool(getattr(settings, "elite_trade_v_rip_only_enabled", False)) and setup != "V":
        assessment = {**assessment, "side": resolved_side}
        return False, "elite_v_rip_only", assessment

    milestone_blocked, milestone_reason = elite_milestone_depth_blocked(
        evidence, settings=settings,
    )
    if milestone_blocked:
        assessment = {**assessment, "side": resolved_side}
        return False, milestone_reason, assessment

    score = float(assessment.get("eliteScore") or 0)
    if score < min_score - 1e-6:
        return False, f"elite_score_below_{min_score:g}", assessment

    must_take = elite_must_take(evidence, ranking, assessment, settings=settings)

    fvq_blocked, fvq_reason = elite_fvq_chase_blocked(
        evidence,
        settings=settings,
        must_take=must_take,
        readiness_reason=readiness_reason,
        assessment=assessment,
        side=resolved_side,
    )
    if fvq_blocked:
        assessment = {**assessment, "side": resolved_side, "mustTake": must_take}
        return False, fvq_reason, assessment

    chop_call_blocked, chop_call_reason = elite_call_chop_shallow_blocked(
        resolved_side,
        resolved_mode,
        _number(assessment.get("localBasePct")),
        settings=settings,
    )
    if chop_call_blocked:
        assessment = {**assessment, "side": resolved_side, "mustTake": must_take}
        return False, chop_call_reason, assessment

    v_rip_shallow_blocked, v_rip_shallow_reason = elite_v_rip_shallow_lift_blocked(
        evidence, assessment, settings=settings, readiness_reason=readiness_reason,
    )
    if v_rip_shallow_blocked:
        assessment = {**assessment, "side": resolved_side, "mustTake": must_take}
        return False, v_rip_shallow_reason, assessment

    perfect_blocked, perfect_reason = elite_perfect_score_blocked(
        score,
        _number(assessment.get("localBasePct")),
        settings=settings,
    )
    if perfect_blocked:
        assessment = {**assessment, "side": resolved_side, "mustTake": must_take}
        return False, perfect_reason, assessment

    if int(assessment.get("stageRank") or 0) < min_stage_rank:
        return False, f"elite_stage_below_{min_stage.lower()}", assessment

    shallow_blocked, shallow_reason = elite_shallow_lift_blocked(
        evidence, assessment, settings=settings,
    )
    if shallow_blocked:
        assessment = {**assessment, "side": resolved_side, "mustTake": must_take}
        return False, shallow_reason, assessment

    local = _number(assessment.get("localBasePct"))
    if local > max_local + 1e-6:
        assessment = {**assessment, "side": resolved_side, "localBaseCapPct": round(max_local, 2)}
        if resolved_side == "CALL" and max_local < float(
            getattr(settings, "elite_trade_max_local_base_pct", 20.0) or 20.0
        ):
            return False, "elite_call_chase_past_local_base_window", assessment
        if resolved_side == "PUT" and max_local < float(
            getattr(settings, "elite_trade_max_local_base_pct", 20.0) or 20.0
        ):
            return False, "elite_put_chase_past_local_base_window", assessment
        return False, "elite_chase_past_local_base_window", assessment

    if not _timing_ok(evidence):
        return False, "elite_timing_not_good_or_ok", assessment

    assessment = {
        **assessment,
        "mustTake": must_take,
        "dayMode": resolved_mode,
        "dayType": resolved_type,
        "side": resolved_side,
        "localBaseCapPct": round(max_local, 2),
        "trendDayBonusEligible": elite_trend_day_bonus_allowed(
            {**assessment, "dayMode": resolved_mode},
            settings=settings,
        ),
    }
    return True, "ok", assessment
