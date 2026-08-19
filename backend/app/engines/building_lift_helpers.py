"""BUILDING sudden-lift helpers — monitor what actually moves premium (Aug19 shape).

Aug19 SENSEX 76900 PE proved the rip helpers are:
  volume awaken + surge, live velocity spike, displacement,
  chart/breadth align, flat→vertical structure, and ICT confluence
  (judas reclaim / index-option displacement / pm kill zone).

This module scores those helpers on every BUILDING LTP print so we catch
the lift as soon as something is helping — not after ELITE prints.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot


# Minimum helpers that must fire together for a "sudden lift helping" stamp.
# Aug19 fired vol + velocity + displacement + breadth + chart + FTV together.
DEFAULT_MIN_HELPERS = 3


@dataclass
class BuildingLiftHelpers:
    """Causal helper board for one BUILDING name on one LTP print."""

    helpers: list[str] = field(default_factory=list)
    helper_count: int = 0
    helping: bool = False
    sudden_lift: bool = False
    ltp_lift_pct: float = 0.0
    volume_awaken: bool = False
    volume_surge: float = 0.0
    absolute_volume: float = 0.0
    velocity_3s: float = 0.0
    velocity_9s: float = 0.0
    peak_velocity_3s: float = 0.0
    displacement: bool = False
    chart_align: bool = False
    breadth_align: bool = False
    flat_then_vertical: bool = False
    flat_vertical_quality: float = 0.0
    cvd_buying: bool = False
    ict_confirms: list[str] = field(default_factory=list)
    # Index-level helpers (actual NIFTY/SENSEX spot move — not strike premium).
    index_velocity_3s: float = 0.0
    index_velocity_9s: float = 0.0
    index_tick_align: bool = False
    index_tick_spike: bool = False
    index_mom_align: bool = False
    index_squeeze: bool = False
    index_helpers: list[str] = field(default_factory=list)
    index_confirming: bool = False
    score_bonus: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _side_str(alert: dict[str, Any]) -> str:
    return str(alert.get("side") or "").upper()


def evaluate_building_lift_helpers(
    *,
    snap: SymbolSnapshot,
    alert: dict[str, Any],
    prev_ltp: Optional[float] = None,
    live_ltp: Optional[float] = None,
) -> BuildingLiftHelpers:
    """Detect what is helping a BUILDING name move right now."""
    settings = get_settings()
    row = alert if isinstance(alert, dict) else {}
    side = _side_str(row)
    out = BuildingLiftHelpers()

    out.volume_awaken = bool(
        row.get("volumeAwaken") or row.get("ictVolumeAwakening")
    )
    out.volume_surge = _number(row.get("volumeSurge") or row.get("volume_surge"))
    out.absolute_volume = _number(
        row.get("volume") or row.get("absoluteVolume")
    )
    out.velocity_3s = _number(
        row.get("velocity3s") or row.get("velocity_3s") or row.get("tickVelocity3s")
    )
    out.velocity_9s = _number(
        row.get("velocity9s") or row.get("velocity_9s") or row.get("tickVelocity9s")
    )
    # Peak v3 often lives in reason string as peakV3=… or dedicated field.
    out.peak_velocity_3s = max(
        _number(row.get("peakVelocity3s") or row.get("peak_velocity_3s")),
        out.velocity_3s,
    )
    reason = str(row.get("reason") or "")
    if "peakV3=" in reason:
        try:
            frag = reason.split("peakV3=", 1)[1]
            out.peak_velocity_3s = max(
                out.peak_velocity_3s,
                float("".join(ch for ch in frag.split("%", 1)[0] if ch in "0123456789.-")),
            )
        except (TypeError, ValueError, IndexError):
            pass

    out.displacement = bool(
        row.get("ictDisplacement") or row.get("displacement")
    )
    out.flat_then_vertical = bool(
        row.get("ictFlatThenVertical") or row.get("flatThenVertical")
    )
    out.flat_vertical_quality = _number(
        row.get("flatVerticalQuality") or row.get("ictFlatVerticalQuality")
    )
    out.cvd_buying = bool(
        row.get("cvdBuying")
        or row.get("optionCvdBuying")
        or row.get("orderflowConfirmed")
    )

    # Live CVD if not already stamped.
    if not out.cvd_buying and side in ("CALL", "PUT"):
        try:
            from app.engines.advanced_indicators import (
                option_cvd_acceleration_confirms_buying,
                option_cvd_confirms_buying,
            )

            strike = _number(row.get("strike"))
            if strike > 0:
                out.cvd_buying = bool(
                    option_cvd_confirms_buying(snap, strike, Side(side))
                    or option_cvd_acceleration_confirms_buying(
                        snap, strike, Side(side)
                    )
                )
        except Exception:
            pass

    # Chart / breadth alignment (the index turn that helped Aug19 PE).
    if side in ("CALL", "PUT"):
        try:
            from app.engines.spot_direction import side_aligned_with_chart

            if getattr(snap, "spotChart", None) is not None:
                out.chart_align = bool(
                    side_aligned_with_chart(Side(side), snap.spotChart)
                )
        except Exception:
            out.chart_align = False
        try:
            from app.engines.symbol_cooldown import side_aligned_with_breadth

            bias = str(getattr(getattr(snap, "breadth", None), "bias", "") or "")
            out.breadth_align = bool(side_aligned_with_breadth(side, bias))
        except Exception:
            out.breadth_align = False

    # Index tick / mom / squeeze — actual spot move that lifts strikes.
    if side in ("CALL", "PUT"):
        try:
            from app.engines.index_tick_helpers import evaluate_index_tick_helpers

            idx = evaluate_index_tick_helpers(snap=snap, side=side, alert=row)
            out.index_velocity_3s = float(idx.velocity_3s)
            out.index_velocity_9s = float(idx.velocity_9s)
            out.index_tick_align = bool(idx.tick_align)
            out.index_tick_spike = bool(idx.tick_spike)
            out.index_mom_align = bool(idx.mom_align)
            out.index_squeeze = bool(idx.squeeze_align)
            out.index_helpers = list(idx.helpers)
            out.index_confirming = bool(idx.confirming)
            # Breadth already counted above; index board may reaffirm it.
            if idx.breadth_align and not out.breadth_align:
                out.breadth_align = True
        except Exception:
            pass

    # ICT confluence from local-base prediction (judas / displacement / kill zone).
    pred = (
        row.get("bullishLocalBasePrediction")
        or row.get("localBaseReversalPrediction")
        or {}
    )
    confirms = []
    if isinstance(pred, dict):
        raw = pred.get("ictConfirms") or pred.get("reasons") or []
        if isinstance(raw, list):
            confirms = [str(c) for c in raw if c]
    # Also harvest ictReasons that match known helpers.
    for r in row.get("ictReasons") or []:
        s = str(r)
        if any(
            tag in s
            for tag in (
                "judas",
                "displacement",
                "kill_zone",
                "volume",
                "flat_then",
                "first_lift",
                "local_swing",
            )
        ):
            confirms.append(s)
    # Dedupe preserve order.
    seen: set[str] = set()
    out.ict_confirms = []
    for c in confirms:
        if c not in seen:
            seen.add(c)
            out.ict_confirms.append(c)

    # Sudden LTP lift vs prior watch fingerprint.
    ltp = _number(live_ltp if live_ltp is not None else row.get("premium"))
    prev = _number(prev_ltp) if prev_ltp is not None else 0.0
    if prev > 0 and ltp > prev:
        out.ltp_lift_pct = (ltp - prev) / prev * 100.0
        min_sudden = float(
            getattr(settings, "building_sudden_lift_min_pct", 0.4) or 0.4
        )
        out.sudden_lift = out.ltp_lift_pct >= min_sudden
    elif ltp > 0 and prev <= 0:
        out.ltp_lift_pct = 0.0

    helpers: list[str] = []
    min_surge = float(
        getattr(settings, "building_rip_min_volume_surge", 1.8) or 1.8
    )
    min_v3 = float(
        getattr(settings, "building_sudden_lift_min_velocity_3s", 1.2) or 1.2
    )
    min_peak_v3 = float(
        getattr(settings, "building_sudden_lift_min_peak_velocity_3s", 3.0) or 3.0
    )
    min_fvq = float(
        getattr(settings, "building_sudden_lift_min_ftv_quality", 55.0) or 55.0
    )
    min_abs_vol = float(
        getattr(settings, "building_sudden_lift_min_absolute_volume", 25_000)
        or 25_000
    )

    if out.volume_awaken:
        helpers.append("vol_awaken")
    if out.volume_surge >= min_surge:
        helpers.append("volume_surge")
    if out.absolute_volume >= min_abs_vol:
        helpers.append("abs_volume")
    if out.velocity_3s >= min_v3:
        helpers.append("velocity_spike")
    if out.velocity_9s >= 0.8:
        helpers.append("velocity_9s")
    if out.peak_velocity_3s >= min_peak_v3:
        helpers.append("peak_velocity")
    if out.displacement:
        helpers.append("displacement")
    if out.chart_align:
        helpers.append("chart_align")
    if out.breadth_align:
        helpers.append("breadth_align")
    if out.flat_then_vertical or out.flat_vertical_quality >= min_fvq:
        helpers.append("flat_vertical")
    if out.cvd_buying:
        helpers.append("cvd_buying")
    if out.sudden_lift:
        helpers.append("sudden_ltp_lift")
    # Index-level helpers (spot tape / mom / squeeze) — drive strike lifts.
    for ih in out.index_helpers:
        if ih not in helpers:
            helpers.append(ih)
    # Named ICT confluence helpers from Aug19.
    confirm_blob = " ".join(out.ict_confirms).lower()
    if "judas" in confirm_blob:
        helpers.append("judas_reclaim")
    if "index_option_displacement" in confirm_blob or (
        "displacement" in confirm_blob and "displacement" not in helpers
    ):
        if "index_displacement" not in helpers:
            helpers.append("index_displacement")
    if "kill_zone" in confirm_blob or "pm_kill" in confirm_blob:
        helpers.append("pm_kill_zone")
    if "premium_accelerating" in confirm_blob:
        helpers.append("premium_accelerating")
    if "volume_expanding" in confirm_blob and "vol_awaken" not in helpers:
        helpers.append("volume_expanding")

    out.helpers = helpers
    out.helper_count = len(helpers)
    min_needed = int(
        getattr(settings, "building_sudden_lift_min_helpers", DEFAULT_MIN_HELPERS)
        or DEFAULT_MIN_HELPERS
    )
    # Need heat + at least one alignment/structure helper — never vol alone.
    has_heat = bool(
        {
            "vol_awaken",
            "volume_surge",
            "velocity_spike",
            "displacement",
            "cvd_buying",
        }
        & set(helpers)
    )
    has_structure = bool(
        {
            "chart_align",
            "breadth_align",
            "flat_vertical",
            "judas_reclaim",
            "index_displacement",
            "sudden_ltp_lift",
            "index_tick_align",
            "index_tick_spike",
            "index_spike_burst",
            "index_mom_turn",
            "index_squeeze",
            "index_breadth",
        }
        & set(helpers)
    )
    out.helping = (
        out.helper_count >= min_needed and has_heat and has_structure
    )
    # Index confirming + option heat is enough even one helper short of min
    # (spot move is the causal driver of the strike lift).
    if out.index_confirming and has_heat and has_structure:
        out.helping = True

    # Score bonus for ranking: each helper + extra when the board is helping.
    bonus = float(out.helper_count) * float(
        getattr(settings, "building_lift_helper_point", 3.5) or 3.5
    )
    if out.helping:
        bonus += float(
            getattr(settings, "building_lift_helping_bonus", 18.0) or 18.0
        )
    if out.sudden_lift:
        bonus += float(
            getattr(settings, "building_sudden_ltp_lift_bonus", 8.0) or 8.0
        )
    if out.index_confirming:
        bonus += float(
            getattr(settings, "index_tick_confirm_bonus", 10.0) or 10.0
        )
    out.score_bonus = round(min(40.0, bonus), 2)
    return out


def stamp_building_lift_helpers(
    alert: dict[str, Any],
    helpers: BuildingLiftHelpers,
) -> dict[str, Any]:
    """Attach helper board onto the live alert for FTV / UI / readiness."""
    out = dict(alert)
    out["buildingRipHelpers"] = list(helpers.helpers)
    out["buildingRipHelpersOk"] = bool(helpers.helping or helpers.helper_count >= 2)
    out["buildingLiftHelping"] = bool(helpers.helping)
    out["buildingSuddenLift"] = bool(helpers.sudden_lift)
    out["buildingLtpLiftPct"] = round(helpers.ltp_lift_pct, 3)
    out["buildingHelperCount"] = int(helpers.helper_count)
    out["buildingHelperBonus"] = float(helpers.score_bonus)
    out["buildingIctConfirms"] = list(helpers.ict_confirms)
    # Index spot tape for archive replay / FTV evidence.
    out["indexSpotMove3s"] = round(helpers.index_velocity_3s, 4)
    out["indexSpotMove9s"] = round(helpers.index_velocity_9s, 4)
    out["indexTickAlign"] = bool(helpers.index_tick_align)
    out["indexTickSpike"] = bool(helpers.index_tick_spike)
    out["indexMomAlign"] = bool(helpers.index_mom_align)
    out["indexSqueezeAlign"] = bool(helpers.index_squeeze)
    out["indexHelpers"] = list(helpers.index_helpers)
    out["indexHelperCount"] = int(len(helpers.index_helpers))
    out["indexHelpersConfirm"] = bool(helpers.index_confirming)
    if helpers.helping:
        out["ictBuildingRipReady"] = True
    return out
