"""Hold trades longer when psychology setup supports letting runners run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import OptimizedProfile, PaperTrade, SymbolSnapshot
from app.engines.confidence_hold import trade_entry_score


@dataclass
class PsychologyExitTuning:
    micro_min_best_points: float
    min_hold_before_micro_seconds: int
    micro_giveback_points: float
    trail_keep_ratio: float
    max_hold_multiplier: float


def _psychology_label(trade: PaperTrade) -> str:
    ctx = trade.entryContext or {}
    label = ctx.get("psychology") or ctx.get("psychologyLabel") or ""
    return str(label).upper()


def psychology_setup_active(trade: PaperTrade) -> bool:
    """FEAR/CAUTION psychology at entry — defensive chop setups worth holding."""
    settings = get_settings()
    if not settings.psychology_hold_enabled:
        return False
    label = _psychology_label(trade)
    allowed = {x.strip().upper() for x in settings.psychology_hold_labels_csv.split(",") if x.strip()}
    if label not in allowed:
        return False
    score = trade_entry_score(trade)
    return score >= settings.psychology_hold_min_score


def psychology_setup_from_snap(snap: SymbolSnapshot, candidate_score: float) -> bool:
    settings = get_settings()
    if not settings.psychology_hold_enabled:
        return False
    ps = snap.psychology or {}
    label = str(ps.get("label", "NEUTRAL")).upper()
    allowed = {x.strip().upper() for x in settings.psychology_hold_labels_csv.split(",") if x.strip()}
    if label not in allowed:
        return False
    return candidate_score >= settings.psychology_hold_min_score


def psychology_exit_tuning(trade: PaperTrade) -> Optional[PsychologyExitTuning]:
    if not psychology_setup_active(trade):
        return None
    settings = get_settings()
    return PsychologyExitTuning(
        micro_min_best_points=settings.psychology_hold_micro_min_best_points,
        min_hold_before_micro_seconds=settings.psychology_hold_min_hold_before_micro_seconds,
        micro_giveback_points=settings.psychology_hold_micro_giveback_points,
        trail_keep_ratio=settings.psychology_hold_trail_keep_ratio,
        max_hold_multiplier=settings.psychology_hold_max_hold_multiplier,
    )


def apply_psychology_hold_profile(
    trade: PaperTrade,
    profile: OptimizedProfile,
) -> OptimizedProfile:
    tuning = psychology_exit_tuning(trade)
    if not tuning:
        return profile
    mult = tuning.max_hold_multiplier
    return OptimizedProfile(
        targetPoints=round(profile.targetPoints * 1.08, 2),
        stopPoints=profile.stopPoints,
        microTargetPoints=round(max(profile.microTargetPoints, 3.5), 2),
        maxHoldSeconds=int(profile.maxHoldSeconds * mult),
        sessionLabel=f"{profile.sessionLabel}_psy_hold",
    )


def psychology_hold_summary() -> dict[str, Any]:
    settings = get_settings()
    return {
        "enabled": settings.psychology_hold_enabled,
        "labels": settings.psychology_hold_labels_csv,
        "minScore": settings.psychology_hold_min_score,
    }
