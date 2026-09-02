"""Day-type min grade policy for top-moment gate.

Historical research (Aug19/24 + Sep01 archives, 134 top moments):
- BEARISH/BULLISH directional days: ~5% grade-blocked at min A; loosen to B.
- MOMENTUM RALLY / CHOP+RALLY (fast velocity window): loosen to B; grade C when
  ELITE/EXPLODING + strong v3 + causal FTV shape (Sep2 afternoon pattern).
- CHOP / EXPIRY WORST: keep min A — grade C adds noise on chop days.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

# Default min grade by day mode (never loosens below configured base unless listed).
_DAY_TYPE_MIN_GRADE: dict[str, str] = {
    "MOMENTUM RALLY": "B",
    "CHOP + RALLY": "B",
    "BULLISH DAY": "B",
    "BEARISH DAY": "B",
    "LEAN BULLISH": "B",
    "LEAN BEARISH": "B",
    "MIXED DAY": "B",
    "CHOP DAY": "A",
    "CHOP (PRE-10)": "A",
    "EXPIRY DAY": "A",
    "EXPIRY WORST": "A",
    "NORMAL": "A",
    "NO_DATA": "A",
}

# Large-loss pause bypass by day mode (all sessions; EXPIRY WORST blocked).
_LARGE_LOSS_PAUSE_STRICT_MODES = frozenset({"CHOP DAY", "CHOP (PRE-10)"})
_LARGE_LOSS_PAUSE_BLOCK_MODES = frozenset({"EXPIRY WORST"})

_GRADE_RANK = {"S": 0, "A": 1, "B": 2, "C": 3, "REJECT": 9}


def _grade_rank(grade: str) -> int:
    return _GRADE_RANK.get(str(grade or "").upper(), 9)


def _looser_grade(current: str, candidate: str) -> str:
    """Return the lower (more permissive) of two min-grade floors."""
    cur, cand = str(current or "A").upper(), str(candidate or "A").upper()
    if _grade_rank(cand) > _grade_rank(cur):
        return cand
    return cur


def _parse_csv_set(raw: str) -> frozenset[str]:
    return frozenset(s.strip().upper() for s in str(raw or "").split(",") if s.strip())


def resolve_day_type_min_grade(
    *,
    min_grade: str = "A",
    day_mode: str = "",
    settings: Any = None,
) -> str:
    """Effective min grade from day mode + base config."""
    from app.config import get_settings

    settings = settings or get_settings()
    effective = str(
        min_grade or getattr(settings, "top_moments_min_grade", "A") or "A"
    ).upper()

    if not bool(getattr(settings, "top_moments_day_type_grade_policy_enabled", True)):
        return effective

    mode = str(day_mode or "").strip().upper()
    if not mode:
        return effective

    # Explicit per-mode overrides from config (optional future tuning).
    override_map = getattr(settings, "top_moments_day_type_min_grade_map", None)
    if isinstance(override_map, dict) and mode in override_map:
        mapped = str(override_map[mode] or "").upper()
        if mapped in {"S", "A", "B", "C"}:
            return _looser_grade(effective, mapped)

    mapped = _DAY_TYPE_MIN_GRADE.get(mode)
    if mapped:
        return _looser_grade(effective, mapped)

    return effective


def large_loss_pause_bypass_for_day_mode(
    day_mode: str,
    *,
    settings: Any = None,
) -> dict[str, Any]:
    """
    Per day-mode policy for lifting large-loss pause.

    Returns dict with keys: allowed, reason (if blocked), minScore, tiersCsv, strict.
    """
    from app.config import get_settings

    settings = settings or get_settings()
    mode = str(day_mode or "").strip().upper()
    block_csv = str(
        getattr(settings, "session_large_loss_pause_bypass_block_modes_csv", "EXPIRY WORST")
        or "EXPIRY WORST"
    )
    blocked = _parse_csv_set(block_csv) | _LARGE_LOSS_PAUSE_BLOCK_MODES
    if mode in blocked:
        return {
            "allowed": False,
            "reason": f"large_loss_pause_blocked_{mode.lower().replace(' ', '_')}",
            "strict": False,
        }

    default_min = float(getattr(settings, "loss_streak_elite_bypass_min_score", 90.0) or 90.0)
    default_tiers = str(
        getattr(settings, "loss_streak_elite_bypass_tiers_csv", "ELITE,EXPLODING") or "ELITE,EXPLODING"
    )

    if mode in _LARGE_LOSS_PAUSE_STRICT_MODES:
        chop_min = float(
            getattr(settings, "session_large_loss_pause_chop_min_score", 95.0) or 95.0
        )
        chop_tiers = str(
            getattr(settings, "session_large_loss_pause_chop_tiers_csv", "ELITE") or "ELITE"
        )
        return {
            "allowed": True,
            "minScore": chop_min,
            "tiersCsv": chop_tiers,
            "strict": True,
        }

    # MOMENTUM RALLY, BULLISH/BEARISH, MIXED, NORMAL, EXPIRY DAY, CHOP+RALLY, etc.
    return {
        "allowed": True,
        "minScore": default_min,
        "tiersCsv": default_tiers,
        "strict": False,
    }


def fast_moving_grade_c_waiver(
    evidence: Mapping[str, Any],
    ranking: Mapping[str, Any],
    moment: Optional[str],
    *,
    day_mode: str = "",
    settings: Any = None,
) -> bool:
    """Grade-C ELITE/EXPLODING causal moments on fast-moving day types."""
    from app.config import get_settings

    settings = settings or get_settings()
    if not bool(getattr(settings, "top_moments_fast_day_grade_c_enabled", True)):
        return False

    grade = str(ranking.get("grade") or "").upper()
    if grade != "C":
        return False

    mode = str(day_mode or "").strip().upper()
    allowed_modes = _parse_csv_set(
        str(
            getattr(
                settings,
                "top_moments_fast_day_grade_c_modes_csv",
                "MOMENTUM RALLY,CHOP + RALLY,BULLISH DAY,BEARISH DAY",
            )
            or ""
        )
    )
    if mode not in allowed_modes:
        return False

    top_moment_types = frozenset({"ELITE", "EXPLODING", "FTV", "V"})
    if moment not in top_moment_types:
        return False

    tier = str(evidence.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False

    score = float(ranking.get("rankScore") or 0)
    min_score = float(
        getattr(settings, "top_moments_fast_day_min_rank_score", 50.0) or 50.0
    )
    if score < min_score:
        return False

    v3 = float(evidence.get("velocity3s") or 0)
    min_v3 = float(
        getattr(settings, "top_moments_fast_day_min_velocity_3s", 2.0) or 2.0
    )
    if v3 < min_v3:
        return False

    if bool(evidence.get("vRipReady")):
        return True
    if bool(evidence.get("flatThenVertical") and evidence.get("activeBreakout")):
        return True
    return bool(
        evidence.get("slowGrindSuddenLift")
        or evidence.get("slowGrindConsolidationBase")
        or evidence.get("fastBullishLocalBase")
        or evidence.get("squeezeRelease")
        or evidence.get("indexLedOptionLag")
        or evidence.get("stealthCvdCoil")
        or evidence.get("microPullbackRetest")
        or evidence.get("premiumFvgPad")
        or evidence.get("doubleDipVbase")
        or evidence.get("buildingCoilPad")
    )
