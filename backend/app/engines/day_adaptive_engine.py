"""Day-adaptive trading — right strategy mix for worst, chop, normal, and good days."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import AutoTraderState, SymbolSnapshot


@dataclass
class DayAdaptiveProfile:
    """Per-day-type playbook — what to trade and how aggressively."""

    day_type: str = "NORMAL"
    day_mode: str = "NORMAL"
    confidence_tier: str = "MEDIUM"
    preferred_modes: list[str] = field(default_factory=lambda: ["explosion", "scalp"])
    mode_bonuses: dict[str, float] = field(default_factory=dict)
    min_rank_cap: float = 72.0
    min_rank_relief: float = 0.0
    lot_scale_boost: float = 1.0
    allow_explosion: Optional[bool] = None
    allow_quick_sideways: Optional[bool] = None
    pause_regular_scalps: bool = False
    playbook: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dayType": self.day_type,
            "dayMode": self.day_mode,
            "confidenceTier": self.confidence_tier,
            "preferredModes": self.preferred_modes,
            "modeBonuses": self.mode_bonuses,
            "minRankCap": self.min_rank_cap,
            "minRankRelief": self.min_rank_relief,
            "lotScaleBoost": round(self.lot_scale_boost, 2),
            "allowExplosion": self.allow_explosion,
            "allowQuickSideways": self.allow_quick_sideways,
            "pauseRegularScalps": self.pause_regular_scalps,
            "playbook": self.playbook,
        }


def classify_day_type(
    day_mode: str,
    confidence_tier: str,
    snapshots: dict[str, SymbolSnapshot],
    state: Optional[AutoTraderState] = None,
) -> str:
    """WORST | CHOP | NORMAL | GOOD | ELITE — drives strategy routing."""
    dm = (day_mode or "NORMAL").upper()
    tier = (confidence_tier or "MEDIUM").upper()

    from app.engines.expiry_day_guards import predict_worst_expiry_day
    from app.engines.whipsaw_guards import is_bearish_sideways_session
    from app.engines.chop_day_guards import in_momentum_rally_window, is_chop_session

    if "EXPIRY WORST" in dm:
        return "WORST"
    if state is not None:
        worst, _, _ = predict_worst_expiry_day(state, snapshots)
        if worst:
            return "WORST"
    if is_bearish_sideways_session(snapshots):
        return "WORST"
    if tier == "LOW" and is_chop_session(snapshots) and not in_momentum_rally_window():
        return "WORST"

    if "CHOP" in dm or "PRE-10" in dm:
        return "CHOP"

    rally = in_momentum_rally_window() or "RALLY" in dm
    directional = any(x in dm for x in ("BULLISH", "BEARISH"))

    if tier == "ELITE" and (directional or rally):
        return "ELITE"
    if tier in ("HIGH", "ELITE") or rally or directional:
        return "GOOD"

    return "NORMAL"


def build_day_adaptive_profile(
    day_mode: str,
    confidence_tier: str,
    snapshots: dict[str, SymbolSnapshot],
    *,
    phase: str = "ACCUMULATE",
    state: Optional[AutoTraderState] = None,
) -> DayAdaptiveProfile:
    """Map day type → strategy preferences, rank caps, and lot scaling."""
    settings = get_settings()
    day_type = classify_day_type(day_mode, confidence_tier, snapshots, state=state)
    profile = DayAdaptiveProfile(
        day_type=day_type,
        day_mode=day_mode,
        confidence_tier=confidence_tier,
    )

    if day_type == "WORST":
        # Block quick_sideways only — keep scalp + momentum explosions.
        profile.preferred_modes = ["explosion", "scalp"]
        profile.mode_bonuses = {
            "explosion": 12.0,
            "scalp": 8.0,
            "slow_bounce": 4.0,
            "quick_sideways": -14.0,
            "swing": -6.0,
        }
        profile.min_rank_cap = settings.day_adaptive_worst_rank_cap
        profile.lot_scale_boost = 0.72
        profile.allow_explosion = confidence_tier in ("HIGH", "ELITE")
        profile.allow_quick_sideways = False
        profile.pause_regular_scalps = False
        profile.playbook = [
            "Worst day — scalp + elite momentum OK; no quick sideways",
            "Cap rank floor — smaller size on chop",
        ]
    elif day_type == "CHOP":
        profile.preferred_modes = ["quick_sideways", "explosion", "scalp"]
        profile.mode_bonuses = {
            "quick_sideways": 12.0,
            "explosion": 8.0 if "RALLY" in (day_mode or "").upper() else 5.0,
            "scalp": 2.0,
            "swing": 0.0,
        }
        profile.min_rank_cap = settings.day_adaptive_chop_rank_cap
        profile.lot_scale_boost = 0.82
        profile.allow_quick_sideways = True
        profile.playbook = [
            "Chop day — quick sideways + surge explosions",
            "SENSEX preferred; momentum bypass on velocity ≥2.5%",
        ]
    elif day_type == "GOOD":
        profile.preferred_modes = ["explosion", "scalp", "quick_sideways"]
        profile.mode_bonuses = {
            "explosion": 22.0,
            "scalp": 12.0,
            "quick_sideways": 6.0,
            "swing": 8.0,
        }
        profile.min_rank_relief = settings.day_adaptive_good_day_rank_relief + 4.0
        profile.lot_scale_boost = 1.12
        profile.allow_explosion = True
        profile.pause_regular_scalps = False
        profile.playbook = [
            "Good day — explosions + aligned scalps, let runners on HIGH edge",
            f"Rank relief −{profile.min_rank_relief:.0f} on quality setups",
        ]
    elif day_type == "ELITE":
        profile.preferred_modes = ["explosion", "scalp", "swing"]
        profile.mode_bonuses = {
            "explosion": 28.0,
            "scalp": 14.0,
            "quick_sideways": 8.0,
            "swing": 10.0,
        }
        profile.min_rank_relief = settings.day_adaptive_good_day_rank_relief + 6.0
        profile.lot_scale_boost = 1.22
        profile.allow_explosion = True
        profile.pause_regular_scalps = False
        profile.playbook = [
            "Elite day — full aggression on aligned momentum",
            "Explosions first; widen trails on high edge + PF",
        ]
    else:
        profile.mode_bonuses = {
            "explosion": 12.0,
            "quick_sideways": 6.0,
            "scalp": 4.0,
            "swing": 3.0,
        }
        profile.lot_scale_boost = 0.95
        profile.playbook = ["Normal session — balanced explosion + scalp mix"]

    if phase == "PROTECT":
        profile.lot_scale_boost = min(profile.lot_scale_boost, 0.85)
        profile.playbook.append("Protect phase — quality over quantity")
    elif phase == "EXTEND":
        profile.min_rank_cap = min(profile.min_rank_cap, settings.daily_18pct_high_confidence_min)
        profile.playbook.append("Target hit — extend only on HIGH+ confidence")

    if not settings.quick_sideways_enabled:
        profile.allow_quick_sideways = False
        profile.preferred_modes = [m for m in profile.preferred_modes if m != "quick_sideways"]
        profile.mode_bonuses.pop("quick_sideways", None)
        profile.playbook = [
            line for line in profile.playbook
            if "quick sideways" not in line.lower()
        ]

    return profile


def mode_rank_bonus(mode: str, profile: DayAdaptiveProfile) -> float:
    return float(profile.mode_bonuses.get(mode, 0.0))


def apply_rank_floor_adaptive(
    floor: float,
    profile: DayAdaptiveProfile,
    *,
    candidate_mode: str = "",
) -> float:
    """Cap stacked rank floors on bad days; relieve on good days."""
    adjusted = floor - profile.min_rank_relief
    if candidate_mode == "quick_sideways":
        settings = get_settings()
        adjusted = min(adjusted, settings.quick_sideways_min_rank_score + 2)
    if profile.min_rank_cap > 0:
        adjusted = min(adjusted, profile.min_rank_cap)
    return max(0.0, adjusted)


def should_pause_regular_scalps(
    profile: DayAdaptiveProfile,
    *,
    edge_pause_scalps: bool = False,
) -> bool:
    """Pause ML scalps on worst days — never block quick_sideways."""
    if profile.pause_regular_scalps:
        return True
    if profile.day_type in ("WORST", "CHOP") and edge_pause_scalps:
        return True
    return edge_pause_scalps and profile.day_type not in ("GOOD", "ELITE")


def apply_profile_to_limits(profile: DayAdaptiveProfile, limits: Any) -> None:
    """Tune daily 18% limits from day-adaptive profile."""
    if profile.allow_explosion is not None:
        limits.allowExplosion = profile.allow_explosion or limits.allowExplosion
    if profile.allow_quick_sideways is not None:
        limits.allowQuickSideways = profile.allow_quick_sideways
    if profile.lot_scale_boost != 1.0:
        limits.lotSizeMultiplier = round(
            min(1.0, limits.lotSizeMultiplier * profile.lot_scale_boost), 2,
        )
    if profile.min_rank_relief > 0:
        limits.minRankScore = max(
            48.0,
            limits.minRankScore - profile.min_rank_relief,
        )


def resolve_day_adaptive(
    snapshots: dict[str, SymbolSnapshot],
    state: AutoTraderState,
    *,
    day_mode: str,
    confidence_tier: str,
    phase: str = "ACCUMULATE",
) -> DayAdaptiveProfile:
    settings = get_settings()
    if not settings.day_adaptive_enabled:
        return DayAdaptiveProfile(day_type="NORMAL", day_mode=day_mode, confidence_tier=confidence_tier)
    profile = build_day_adaptive_profile(
        day_mode, confidence_tier, snapshots, phase=phase, state=state,
    )
    if settings.dual_mode_enabled:
        from app.engines.dual_mode_strategy import apply_aggressive_profile_boost, resolve_trading_session_mode

        mode, _ = resolve_trading_session_mode(
            state, snapshots, day_mode=day_mode, confidence_tier=confidence_tier,
        )
        apply_aggressive_profile_boost(profile, mode)
    return profile
