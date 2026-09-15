"""Day-type-aware entry policy — single source for PR #552–#558 entry levers.

Maps session day_type (WORST | CHOP | NORMAL | GOOD | ELITE) to:
  - coil-top guard (position-in-range)
  - COLD_BASE / BUILDING cold velocity floors
  - probe capital % vs max-lot eligibility
  - consolidation-base pad ceiling + cold v3 at trough
  - top-score pre-entry risk bypass threshold
  - bullish-day floor relief activation

Consumers: explosion_entry_guards.coil_top_entry_blocked,
entry_timing.assess_entry_timing, ict_breakout_monitor consolidation,
auto_trader sizing + per_trade_risk bypass.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import AutoTraderState, SymbolSnapshot


@dataclass(frozen=True)
class EntryDayAdaptivePolicy:
    day_type: str
    day_mode: str
    confidence_tier: str
    coil_top_max_position_frac: float
    coil_top_min_run_pct: float
    coil_top_max_run_pct: float
    building_cold_base_min_velocity_3s: float
    cold_base_lot_cap: int
    block_building_watch_cold_base: bool
    probe_max_capital_pct: float
    consolidation_max_pad_pct: float
    consolidation_cold_v3_at_base: bool
    top_score_risk_bypass_min_score: float
    bullish_day_relief: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "dayType": self.day_type,
            "dayMode": self.day_mode,
            "confidenceTier": self.confidence_tier,
            "coilTopMaxPositionFrac": self.coil_top_max_position_frac,
            "coilTopMinRunPct": self.coil_top_min_run_pct,
            "coilTopMaxRunPct": self.coil_top_max_run_pct,
            "buildingColdBaseMinVelocity3s": self.building_cold_base_min_velocity_3s,
            "coldBaseLotCap": self.cold_base_lot_cap,
            "blockBuildingWatchColdBase": self.block_building_watch_cold_base,
            "probeMaxCapitalPct": self.probe_max_capital_pct,
            "consolidationMaxPadPct": self.consolidation_max_pad_pct,
            "consolidationColdV3AtBase": self.consolidation_cold_v3_at_base,
            "topScoreRiskBypassMinScore": self.top_score_risk_bypass_min_score,
            "bullishDayRelief": self.bullish_day_relief,
        }


def _resolve_day_mode(day_mode: str = "", state: Any = None) -> str:
    dm = (day_mode or "").upper()
    if dm:
        return dm
    if state is not None:
        ds = getattr(state, "dailyStrategy", None) or {}
        if isinstance(ds, dict):
            return str(ds.get("dayMode") or "").upper()
    try:
        from app.engines.daily_18pct_strategy import get_session_limits

        limits = get_session_limits()
        return str(getattr(limits, "dayMode", "") or "").upper() if limits else ""
    except Exception:
        return ""


def _resolve_confidence_tier(confidence_tier: str = "", state: Any = None) -> str:
    tier = (confidence_tier or "").upper()
    if tier:
        return tier
    if state is not None:
        ds = getattr(state, "dailyStrategy", None) or {}
        if isinstance(ds, dict):
            return str(ds.get("confidenceTier") or "").upper()
    try:
        from app.engines.daily_18pct_strategy import get_session_limits

        limits = get_session_limits()
        return str(getattr(limits, "confidenceTier", "") or "").upper() if limits else ""
    except Exception:
        return ""


def _chop_with_rally(day_mode: str) -> bool:
    dm = (day_mode or "").upper()
    return "RALLY" in dm or "MOMENTUM" in dm


def _bullish_day_relief_active(
    *,
    day_mode: str,
    confidence_tier: str,
    state: Optional[AutoTraderState],
    snapshots: dict[str, SymbolSnapshot],
    settings: Any,
) -> bool:
    if not bool(getattr(settings, "bullish_day_floor_relief_enabled", True)):
        return False
    from app.engines.bullish_day_floor_relief import bullish_day_context_active

    return bullish_day_context_active(
        day_mode=day_mode,
        confidence_tier=confidence_tier,
        state=state,
        snapshots=snapshots or None,
    )


def resolve_entry_day_policy(
    *,
    day_mode: str = "",
    confidence_tier: str = "",
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
    state: Optional[AutoTraderState] = None,
    settings: Any = None,
) -> EntryDayAdaptivePolicy:
    """Map session day type → unified entry policy for all PR #552–#558 levers."""
    settings = settings or get_settings()
    dm = _resolve_day_mode(day_mode, state)
    tier = _resolve_confidence_tier(confidence_tier, state)
    snaps = snapshots or {}

    from app.engines.day_adaptive_engine import classify_day_type

    day_type = classify_day_type(dm, tier, snaps, state=state)
    rally = _chop_with_rally(dm)
    directional = any(x in dm for x in ("BULLISH", "BEARISH"))
    default_probe = float(
        getattr(settings, "probe_entry_max_capital_pct", 0.40) or 0.40
    )
    default_consolidation = float(
        getattr(settings, "slow_grind_consolidation_base_max_peak_move_pct", 24.0) or 24.0
    )
    default_risk_bypass = float(
        getattr(settings, "top_score_per_trade_risk_bypass_min_score", 80.0) or 80.0
    )

    if not bool(getattr(settings, "entry_day_adaptive_enabled", True)):
        return EntryDayAdaptivePolicy(
            day_type=day_type or "NORMAL",
            day_mode=dm,
            confidence_tier=tier,
            coil_top_max_position_frac=float(
                getattr(settings, "explosion_coil_top_max_position_frac", 0.50) or 0.50
            ),
            coil_top_min_run_pct=float(
                getattr(settings, "explosion_coil_top_min_run_pct", 0.06) or 0.06
            ),
            coil_top_max_run_pct=float(
                getattr(settings, "explosion_coil_top_max_run_pct", 0.28) or 0.28
            ),
            building_cold_base_min_velocity_3s=float(
                getattr(
                    settings,
                    "entry_timing_structured_cold_building_min_velocity_3s",
                    1.5,
                )
                or 1.5
            ),
            cold_base_lot_cap=int(
                getattr(settings, "entry_timing_structured_cold_lot_cap", 3) or 3
            ),
            block_building_watch_cold_base=False,
            probe_max_capital_pct=default_probe,
            consolidation_max_pad_pct=default_consolidation,
            consolidation_cold_v3_at_base=True,
            top_score_risk_bypass_min_score=default_risk_bypass,
            bullish_day_relief=False,
        )

    if day_type == "WORST":
        max_pos = float(
            getattr(settings, "entry_day_worst_coil_top_max_position_frac", 0.35) or 0.35
        )
        min_run = float(
            getattr(settings, "entry_day_worst_coil_top_min_run_pct", 0.05) or 0.05
        )
        max_run = float(
            getattr(settings, "entry_day_worst_coil_top_max_run_pct", 0.22) or 0.22
        )
        building_v = float(
            getattr(settings, "entry_day_worst_building_cold_min_velocity_3s", 2.0) or 2.0
        )
        lot_cap = int(getattr(settings, "entry_day_worst_cold_base_lot_cap", 2) or 2)
        block_cold = bool(
            getattr(settings, "entry_day_worst_block_building_watch_cold_base", True)
        )
        probe_pct = float(
            getattr(settings, "entry_day_worst_probe_max_capital_pct", 0.25) or 0.25
        )
        consolidation_pad = float(
            getattr(settings, "entry_day_worst_consolidation_max_pad_pct", 22.0) or 22.0
        )
        risk_bypass = float(
            getattr(settings, "entry_day_worst_top_score_risk_bypass_min_score", 0.0) or 0.0
        )
        consolidation_cold_v3 = False
        bullish_relief = False
    elif day_type == "CHOP":
        if rally or (directional and tier in ("HIGH", "ELITE")):
            max_pos = float(
                getattr(settings, "entry_day_chop_rally_coil_top_max_position_frac", 0.40)
                or 0.40
            )
            building_v = float(
                getattr(
                    settings,
                    "entry_day_chop_rally_building_cold_min_velocity_3s",
                    1.5,
                )
                or 1.5
            )
            consolidation_pad = float(
                getattr(settings, "entry_day_chop_rally_consolidation_max_pad_pct", 30.0)
                or 30.0
            )
        else:
            max_pos = float(
                getattr(settings, "entry_day_chop_coil_top_max_position_frac", 0.40) or 0.40
            )
            building_v = float(
                getattr(settings, "entry_day_chop_building_cold_min_velocity_3s", 1.5) or 1.5
            )
            consolidation_pad = float(
                getattr(settings, "entry_day_chop_consolidation_max_pad_pct", 26.0) or 26.0
            )
        min_run = float(
            getattr(settings, "entry_day_chop_coil_top_min_run_pct", 0.06) or 0.06
        )
        max_run = float(
            getattr(settings, "entry_day_chop_coil_top_max_run_pct", 0.25) or 0.25
        )
        lot_cap = int(getattr(settings, "entry_day_chop_cold_base_lot_cap", 3) or 3)
        block_cold = bool(
            getattr(settings, "entry_day_chop_block_building_watch_cold_base", True)
        )
        probe_pct = float(
            getattr(settings, "entry_day_chop_probe_max_capital_pct", default_probe)
            or default_probe
        )
        risk_bypass = default_risk_bypass
        consolidation_cold_v3 = True
        bullish_relief = _bullish_day_relief_active(
            day_mode=dm,
            confidence_tier=tier,
            state=state,
            snapshots=snaps,
            settings=settings,
        )
    elif day_type in ("GOOD", "ELITE"):
        max_pos = float(
            getattr(settings, "entry_day_good_coil_top_max_position_frac", 0.50) or 0.50
        )
        min_run = float(
            getattr(settings, "entry_day_good_coil_top_min_run_pct", 0.06) or 0.06
        )
        max_run = float(
            getattr(settings, "entry_day_good_coil_top_max_run_pct", 0.30) or 0.30
        )
        building_v = float(
            getattr(settings, "entry_day_good_building_cold_min_velocity_3s", 1.0) or 1.0
        )
        lot_cap = int(getattr(settings, "entry_day_good_cold_base_lot_cap", 3) or 3)
        block_cold = False
        probe_pct = float(
            getattr(settings, "entry_day_good_probe_max_capital_pct", default_probe)
            or default_probe
        )
        consolidation_pad = float(
            getattr(settings, "entry_day_good_consolidation_max_pad_pct", 28.0) or 28.0
        )
        risk_bypass = default_risk_bypass
        consolidation_cold_v3 = True
        bullish_relief = _bullish_day_relief_active(
            day_mode=dm,
            confidence_tier=tier,
            state=state,
            snapshots=snaps,
            settings=settings,
        )
    else:
        max_pos = float(
            getattr(settings, "entry_day_normal_coil_top_max_position_frac", 0.50) or 0.50
        )
        min_run = float(
            getattr(settings, "entry_day_normal_coil_top_min_run_pct", 0.06) or 0.06
        )
        max_run = float(
            getattr(settings, "entry_day_normal_coil_top_max_run_pct", 0.28) or 0.28
        )
        building_v = float(
            getattr(settings, "entry_day_normal_building_cold_min_velocity_3s", 1.2) or 1.2
        )
        lot_cap = int(getattr(settings, "entry_day_normal_cold_base_lot_cap", 3) or 3)
        block_cold = False
        probe_pct = float(
            getattr(settings, "entry_day_normal_probe_max_capital_pct", default_probe)
            or default_probe
        )
        consolidation_pad = float(
            getattr(settings, "entry_day_normal_consolidation_max_pad_pct", default_consolidation)
            or default_consolidation
        )
        risk_bypass = default_risk_bypass
        consolidation_cold_v3 = True
        bullish_relief = _bullish_day_relief_active(
            day_mode=dm,
            confidence_tier=tier,
            state=state,
            snapshots=snaps,
            settings=settings,
        )

    return EntryDayAdaptivePolicy(
        day_type=day_type,
        day_mode=dm,
        confidence_tier=tier,
        coil_top_max_position_frac=max_pos,
        coil_top_min_run_pct=min_run,
        coil_top_max_run_pct=max_run,
        building_cold_base_min_velocity_3s=building_v,
        cold_base_lot_cap=lot_cap,
        block_building_watch_cold_base=block_cold,
        probe_max_capital_pct=probe_pct,
        consolidation_max_pad_pct=consolidation_pad,
        consolidation_cold_v3_at_base=consolidation_cold_v3,
        top_score_risk_bypass_min_score=risk_bypass,
        bullish_day_relief=bullish_relief,
    )


def probe_capital_pct_for_timing(
    policy: EntryDayAdaptivePolicy,
    timing: Optional[dict[str, Any]] = None,
) -> float:
    """Return capital % cap for probe / COLD / COLD_BASE entries on this day type."""
    if timing is None:
        return policy.probe_max_capital_pct
    assessment = str(timing.get("assessment") or "").upper()
    action = str(timing.get("action") or "").lower()
    if assessment in ("COLD_BASE", "COLD") or action == "lot_cap":
        return policy.probe_max_capital_pct
    return 1.0
