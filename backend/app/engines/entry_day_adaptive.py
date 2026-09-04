"""Day-type-aware entry floors — coil-top, cold-base, probe sizing.

Sep 4 was CHOP+RALLY + ELITE confidence: BUILDING entered at the coil ceiling
because guards used one-size-fits-all thresholds. This module maps day_type
(WORST | CHOP | NORMAL | GOOD | ELITE) to entry policy so every session gets
appropriate base-entry vs breakout rules.
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
    probe_max_capital_pct: float
    cold_base_lot_cap: int
    block_building_watch_cold_base: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "dayType": self.day_type,
            "dayMode": self.day_mode,
            "confidenceTier": self.confidence_tier,
            "coilTopMaxPositionFrac": self.coil_top_max_position_frac,
            "coilTopMinRunPct": self.coil_top_min_run_pct,
            "coilTopMaxRunPct": self.coil_top_max_run_pct,
            "buildingColdBaseMinVelocity3s": self.building_cold_base_min_velocity_3s,
            "probeMaxCapitalPct": self.probe_max_capital_pct,
            "coldBaseLotCap": self.cold_base_lot_cap,
            "blockBuildingWatchColdBase": self.block_building_watch_cold_base,
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


def resolve_entry_day_policy(
    *,
    day_mode: str = "",
    confidence_tier: str = "",
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
    state: Optional[AutoTraderState] = None,
    settings: Any = None,
) -> EntryDayAdaptivePolicy:
    """Map session day type → coil-top / cold-base entry thresholds."""
    settings = settings or get_settings()
    dm = _resolve_day_mode(day_mode, state)
    tier = _resolve_confidence_tier(confidence_tier, state)
    snaps = snapshots or {}

    from app.engines.day_adaptive_engine import classify_day_type

    day_type = classify_day_type(dm, tier, snaps, state=state)
    rally = _chop_with_rally(dm)
    directional = any(x in dm for x in ("BULLISH", "BEARISH"))

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
            probe_max_capital_pct=float(
                getattr(settings, "probe_entry_max_capital_pct", 0.40) or 0.40
            ),
            cold_base_lot_cap=int(
                getattr(settings, "entry_timing_structured_cold_lot_cap", 3) or 3
            ),
            block_building_watch_cold_base=False,
        )

    default_probe = float(
        getattr(settings, "probe_entry_max_capital_pct", 0.40) or 0.40
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
        probe_pct = float(
            getattr(settings, "entry_day_worst_probe_max_capital_pct", 0.25) or 0.25
        )
        block_cold = bool(
            getattr(settings, "entry_day_worst_block_building_watch_cold_base", True)
        )
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
        else:
            max_pos = float(
                getattr(settings, "entry_day_chop_coil_top_max_position_frac", 0.40) or 0.40
            )
            building_v = float(
                getattr(settings, "entry_day_chop_building_cold_min_velocity_3s", 1.5) or 1.5
            )
        min_run = float(
            getattr(settings, "entry_day_chop_coil_top_min_run_pct", 0.06) or 0.06
        )
        max_run = float(
            getattr(settings, "entry_day_chop_coil_top_max_run_pct", 0.25) or 0.25
        )
        lot_cap = int(getattr(settings, "entry_day_chop_cold_base_lot_cap", 99) or 99)
        probe_pct = float(
            getattr(settings, "entry_day_chop_probe_max_capital_pct", default_probe)
            or default_probe
        )
        block_cold = bool(
            getattr(settings, "entry_day_chop_block_building_watch_cold_base", True)
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
        lot_cap = int(getattr(settings, "entry_day_good_cold_base_lot_cap", 99) or 99)
        probe_pct = float(
            getattr(settings, "entry_day_good_probe_max_capital_pct", default_probe)
            or default_probe
        )
        block_cold = False
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
        lot_cap = int(getattr(settings, "entry_day_normal_cold_base_lot_cap", 99) or 99)
        probe_pct = float(
            getattr(settings, "entry_day_normal_probe_max_capital_pct", default_probe)
            or default_probe
        )
        block_cold = False

    return EntryDayAdaptivePolicy(
        day_type=day_type,
        day_mode=dm,
        confidence_tier=tier,
        coil_top_max_position_frac=max_pos,
        coil_top_min_run_pct=min_run,
        coil_top_max_run_pct=max_run,
        building_cold_base_min_velocity_3s=building_v,
        probe_max_capital_pct=probe_pct,
        cold_base_lot_cap=lot_cap,
        block_building_watch_cold_base=block_cold,
    )
