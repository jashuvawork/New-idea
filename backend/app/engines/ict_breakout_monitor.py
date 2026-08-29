"""ICT / FVG breakout monitor — flat-then-vertical premium rips like 8→393 PE moves."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import AutoTraderState, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class ICTBreakoutSignal:
    active: bool
    pattern: str
    score: float
    reasons: list[str]
    premium_fvg: bool = False
    flat_then_vertical: bool = False
    displacement: bool = False
    volume_awakening: bool = False
    mega_rip: bool = False
    session_move_pct: float = 0.0
    velocity_3s: float = 0.0
    volume_surge: float = 1.0
    base_premium: float = 0.0
    base_relative_move_pct: float = 0.0
    local_swing_base: bool = False
    flat_vertical_quality: float = 0.0   # 0-100 quality of the flat->vertical setup
    flat_vertical_grade: str = ""        # A+ | A | B | C
    first_lift: bool = False             # appeared in 15–40% pad off lowest local base
    base_armed: bool = False             # causal stable base exists before launch
    elite_base_ready: bool = False       # strict 2–5% preauthorized base acceleration
    v_rip_ready: bool = False            # continuous 2–25% off session/day V-trough
    building_rip_ready: bool = False     # BUILDING + live bullish rip (mid-rip OK)
    armed_base_launch: bool = False       # strict 5–12% early launch band
    armed_base_sustained_lift: bool = False  # slower causal lift when sparse ticks hide v3/v9
    armed_base_samples: int = 0
    armed_base_span_seconds: float = 0.0
    armed_base_range_pct: float = 0.0
    armed_at: str = ""
    armed_base_expires_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "pattern": self.pattern,
            "score": round(self.score, 1),
            "reasons": self.reasons,
            "premiumFvg": self.premium_fvg,
            "flatThenVertical": self.flat_then_vertical,
            "displacement": self.displacement,
            "volumeAwakening": self.volume_awakening,
            "megaRip": self.mega_rip,
            "sessionMovePct": round(self.session_move_pct, 1),
            "velocity3s": round(self.velocity_3s, 1),
            "volumeSurge": round(self.volume_surge, 2),
            "basePremium": round(self.base_premium, 2),
            "baseRelativeMovePct": round(self.base_relative_move_pct, 1),
            "localSwingBase": self.local_swing_base,
            "flatVerticalQuality": round(self.flat_vertical_quality, 1),
            "flatVerticalGrade": self.flat_vertical_grade,
            "firstLift": self.first_lift,
            "baseArmed": self.base_armed,
            "eliteBaseReady": self.elite_base_ready,
            "vRipReady": self.v_rip_ready,
            "buildingRipReady": self.building_rip_ready,
            "armedBaseLaunch": self.armed_base_launch,
            "armedBaseSustainedLift": self.armed_base_sustained_lift,
            "armedBaseSamples": self.armed_base_samples,
            "armedBaseSpanSeconds": round(self.armed_base_span_seconds, 1),
            "armedBaseRangePct": round(self.armed_base_range_pct, 2),
            "armedAt": self.armed_at,
            "armedBaseExpiresAt": self.armed_base_expires_at,
        }


def _helper_confirmed_lift(
    *,
    row: dict[str, Any],
    ict: Any,
    snap: Optional[SymbolSnapshot],
    event: Any,
    settings: Any,
) -> tuple[bool, int]:
    """Count INDEPENDENT confirmations helping a base lift go vertical.

    "BUILDING on radar + suddenly something is helping to go FTV." When enough distinct
    signals agree (volume, displacement, FVG, flat->vertical structure, chart-align,
    breadth-align) at a local base with positive live velocity, that is the confirmed FTV
    — the caller may then take on a lower quality/score bar. Cold (v3<=0) never confirms.
    """
    if not bool(getattr(settings, "first_lift_helper_confirm_enabled", True)):
        return False, 0
    v3 = float(
        getattr(event, "velocity_3s", 0)
        or getattr(ict, "velocity_3s", 0)
        or row.get("velocity3s")
        or row.get("velocity_3s")
        or 0
    )
    volume_surge = float(
        getattr(event, "volume_surge", 0)
        or getattr(ict, "volume_surge", 0)
        or row.get("volumeSurge")
        or 0
    )
    vol_awake = bool(
        getattr(ict, "volume_awakening", False)
        or row.get("ictVolumeAwakening")
        or row.get("volumeAwaken")
        or "volAwaken" in str(row.get("reason") or "")
    )
    disp_floor = float(getattr(settings, "ict_displacement_min_velocity_3s", 2.2) or 2.2)
    displacement = bool(
        getattr(ict, "displacement", False)
        or row.get("displacement")
        or v3 >= disp_floor
    )
    fvg = bool(getattr(ict, "premium_fvg", False) or row.get("ictPremiumFvg"))
    structured = bool(
        (getattr(ict, "active", False) and getattr(ict, "flat_then_vertical", False))
        or (row.get("ictBreakout") and row.get("ictFlatThenVertical"))
    )
    local_move = float(
        getattr(ict, "base_relative_move_pct", 0)
        or row.get("ictBaseRelativeMovePct")
        or row.get("localBaseMovePct")
        or 0
    )
    has_local_base = bool(
        getattr(ict, "local_swing_base", False)
        or getattr(ict, "base_armed", False)
        or row.get("ictLocalSwingBase")
        or row.get("ictBaseArmed")
        or local_move > 0
    )
    side = str(
        getattr(getattr(event, "side", None), "value", getattr(event, "side", ""))
        or row.get("side")
        or ""
    ).upper()
    strong_surge = float(getattr(settings, "first_lift_helper_strong_surge", 3.0) or 3.0)
    # A DYNAMIC helper (strong volume, displacement, or FVG) is the "suddenly something is
    # helping" spark — static structure/chart/breadth alignment alone is too common to count
    # as confirmation. Require at least one dynamic helper (or a real stamped helper count).
    has_dynamic = bool(volume_surge >= strong_surge or displacement or fvg)
    count = 0
    if volume_surge >= strong_surge or (vol_awake and volume_surge >= strong_surge * 0.6):
        count += 1
    if displacement:
        count += 1
    if fvg:
        count += 1
    if structured:
        count += 1
    if side in ("CALL", "PUT"):
        from app.models.schemas import Side as _S

        try:
            from app.engines.spot_direction import side_aligned_with_chart

            if getattr(snap, "spotChart", None) is not None and side_aligned_with_chart(
                _S(side), snap.spotChart
            ):
                count += 1
        except Exception:
            pass
        try:
            from app.engines.symbol_cooldown import side_aligned_with_breadth

            bbias = str(getattr(getattr(snap, "breadth", None), "bias", "") or "")
            if side_aligned_with_breadth(side, bbias):
                count += 1
        except Exception:
            pass
    stamp = 0
    try:
        stamp = int(row.get("buildingHelperCount") or 0)
    except (TypeError, ValueError):
        stamp = 0
    count = max(count, stamp)
    min_h = int(getattr(settings, "first_lift_helper_confirm_min_helpers", 3) or 3)
    ok = (
        (has_dynamic or stamp >= min_h)
        and count >= min_h
        and v3 > 0
        and has_local_base
    )
    return ok, count


def _option_led_first_lift_ok(
    *,
    row: dict[str, Any],
    ict: Any,
    event: Any,
    snap: Optional[SymbolSnapshot],
    settings: Any,
) -> bool:
    """A confirmed ATM/ITM option leading the slower 5m spot chart.

    This is a deliberately STRONG independent lane (high FTV quality + fast sustained
    v3/v9 + volume awakening AND surge) that may lead before the index chart turns and
    before the generic explosion-score floor is met — the option tape IS the signal.
    All downstream selector/premium/moneyness/session/risk guards still run.
    """
    if not bool(getattr(settings, "first_lift_option_led_enabled", True)):
        return False
    if snap is None:
        return False
    quality = float(
        getattr(ict, "flat_vertical_quality", 0)
        or row.get("flatVerticalQuality")
        or 0
    )
    v3 = float(
        getattr(event, "velocity_3s", 0)
        or getattr(ict, "velocity_3s", 0)
        or row.get("velocity3s")
        or row.get("velocity_3s")
        or 0
    )
    v9 = float(
        getattr(event, "velocity_9s", 0)
        or getattr(ict, "velocity_9s", 0)
        or row.get("velocity9s")
        or row.get("velocity_9s")
        or 0
    )
    volume_awake = bool(
        getattr(ict, "volume_awakening", False)
        or row.get("ictVolumeAwakening")
        or row.get("volumeAwaken")
    )
    volume_surge = float(
        getattr(event, "volume_surge", 0)
        or getattr(ict, "volume_surge", 0)
        or row.get("volumeSurge")
        or 0
    )
    min_volume = float(
        getattr(settings, "first_lift_trade_min_volume_surge", 2.0) or 2.0
    )
    base_v3 = float(getattr(settings, "first_lift_trade_min_velocity_3s", 1.5) or 1.5)
    base_v9 = float(getattr(settings, "first_lift_trade_min_velocity_9s", 1.0) or 1.0)
    option_led_quality = float(
        getattr(settings, "first_lift_option_led_min_quality", 65.0) or 65.0
    )
    option_led_v3 = float(
        getattr(settings, "first_lift_option_led_min_velocity_3s", 1.5) or 1.5
    )
    option_led_v9 = float(
        getattr(settings, "first_lift_option_led_min_velocity_9s", 1.5) or 1.5
    )
    if not (
        quality >= option_led_quality
        and v3 >= max(base_v3, option_led_v3)
        and v9 >= max(base_v9, option_led_v9)
        and volume_awake
        and volume_surge >= min_volume
    ):
        return False
    side = str(
        getattr(getattr(event, "side", None), "value", getattr(event, "side", ""))
        or row.get("side")
        or ""
    ).upper()
    if side not in ("CALL", "PUT"):
        return False
    strike = float(getattr(event, "strike", 0) or row.get("strike") or 0)
    spot = float(getattr(snap, "spot", 0) or 0)
    atm = float(getattr(snap, "atmStrike", 0) or 0)
    if strike <= 0 or spot <= 0:
        return False
    from app.engines.moneyness import classify_moneyness
    from app.models.schemas import Side as _Side

    money = classify_moneyness(
        _Side(side),
        strike,
        spot,
        symbol=str(getattr(snap, "symbol", "") or ""),
        atm=atm if atm > 0 else None,
    )
    return money in ("ATM", "ITM")


def building_rip_bullish_readiness(
    *,
    snap: Optional[SymbolSnapshot],
    event: Any = None,
    ict: Any = None,
    alert: Optional[dict[str, Any]] = None,
    state: Any = None,
) -> tuple[bool, str]:
    """Solid bullish confirmation for BUILDING radar while still ripping.

    Two paths:
    1. Local-base early lift — radar already sees the local base; a measured
       little lift off that base + positive live velocity authorizes the take.
    2. Mid-rip expanding — still ripping toward max (trough arm not required).

    Cold/negative-v3 BUILDING (Aug19 11:45) is rejected on both paths.
    """
    settings = get_settings()
    if not bool(getattr(settings, "building_rip_bullish_enabled", True)):
        return False, "building_rip_disabled"
    if snap is None:
        return False, "building_rip_snap_missing"

    row = alert if isinstance(alert, dict) else {}
    tier = str(
        getattr(event, "tier", "")
        or row.get("tier")
        or ""
    ).upper()
    if tier != "BUILDING" and not (
        tier == "EXPLODING"
        and (
            bool(row.get("ictBuildingRipReady"))
            or bool(getattr(ict, "building_rip_ready", False))
            or "buildingRip" in str(row.get("reason") or "")
        )
    ):
        return False, "building_rip_tier_not_building"

    if bool(row.get("ictMidRipCoil") or row.get("midRipCoil")):
        return False, "building_rip_mid_rip_coil_rejected"

    # Strongly helper-confirmed BUILDING FTV — the "suddenly something is helping" catch.
    # This overrides the worst-day / BREAKOUT_ONLY BUILDING block (those chop/expiry days
    # are exactly where these FTVs were missed). Un-helped BUILDING still hits the block.
    helper_confirmed, _helper_count = _helper_confirmed_lift(
        row=row, ict=ict, snap=snap, event=event, settings=settings,
    )
    override_worst_day = helper_confirmed and bool(
        getattr(settings, "building_rip_helper_override_worst_day", True)
    )

    # Same worst-day / DEFENSIVE block as elite BUILDING ICT.
    if bool(getattr(settings, "worst_day_block_building_ict", True)) and not override_worst_day:
        try:
            from app.engines.worst_day_itm_fade import worst_day_defensive_session_active
            from app.engines.worst_day_guard import session_entry_policy
            from app.engines.dual_mode_strategy import resolve_trading_session_mode
            from app.models.schemas import AutoTraderState as _ATS

            st = state if state is not None else _ATS()
            snaps = {str(getattr(snap, "symbol", "") or ""): snap}
            if worst_day_defensive_session_active(st, snaps):
                return False, "building_rip_worst_day_blocked"
            policy, _ = session_entry_policy(st, snaps)
            if policy in ("BREAKOUT_ONLY", "PAUSED"):
                return False, "building_rip_policy_blocked"
            mode, _ = resolve_trading_session_mode(st, snaps)
            if mode == "DEFENSIVE":
                return False, "building_rip_defensive_blocked"
        except Exception:
            return False, "building_rip_policy_unavailable"

    v3 = float(
        getattr(event, "velocity_3s", 0)
        or row.get("velocity3s")
        or row.get("velocity_3s")
        or getattr(ict, "velocity_3s", 0)
        or 0
    )
    v9 = float(
        getattr(event, "velocity_9s", 0)
        or row.get("velocity9s")
        or row.get("velocity_9s")
        or 0
    )
    volume_surge = float(
        getattr(event, "volume_surge", 0)
        or getattr(ict, "volume_surge", 0)
        or row.get("volumeSurge")
        or 0
    )
    vol_awake = bool(
        getattr(ict, "volume_awakening", False)
        or row.get("ictVolumeAwakening")
        or row.get("volumeAwaken")
        or "volAwaken" in str(row.get("reason") or "")
    )
    min_surge = float(
        getattr(settings, "building_rip_min_volume_surge", 1.8) or 1.8
    )
    score = float(
        getattr(event, "explosion_score", 0)
        or row.get("explosionScore")
        or row.get("score")
        or 0
    )
    local_move = float(
        getattr(ict, "base_relative_move_pct", 0)
        or row.get("ictBaseRelativeMovePct")
        or row.get("localBaseMovePct")
        or 0
    )
    off_low = float(row.get("offLowMovePct") or 0)
    session_move = float(
        getattr(ict, "session_move_pct", 0)
        or row.get("dailyMovePct")
        or row.get("openPremiumMove")
        or getattr(event, "daily_move_pct", 0)
        or 0
    )
    peak_move = float(
        row.get("peakMovePct")
        or getattr(event, "peak_move_pct", 0)
        or 0
    )
    has_local_base = bool(
        getattr(ict, "local_swing_base", False)
        or getattr(ict, "base_armed", False)
        or row.get("ictLocalSwingBase")
        or row.get("ictBaseArmed")
        or local_move > 0
    )
    # Proper local-base lift measure — prefer pad off the known local base,
    # not day-% alone (day-% can look quiet while the local pad is lifting).
    measured_local_lift = local_move if local_move > 0 else (
        off_low if has_local_base and off_low > 0 else 0.0
    )
    local_lift_lo = float(
        getattr(settings, "building_rip_local_base_min_move_pct", 2.0) or 2.0
    )
    local_lift_hi = float(
        getattr(settings, "building_rip_local_base_max_move_pct", 15.0) or 15.0
    )
    local_lift_v3 = float(
        getattr(settings, "building_rip_local_base_min_velocity_3s", 1.2) or 1.2
    )
    local_lift_score = float(
        getattr(settings, "building_rip_local_base_min_score", 12.0) or 12.0
    )
    local_base_lift = bool(
        getattr(settings, "building_rip_local_base_lift_enabled", True)
        and has_local_base
        and local_lift_lo <= measured_local_lift <= local_lift_hi + 1e-6
        and v3 >= local_lift_v3
        and (vol_awake or volume_surge >= min_surge)
        and (v9 >= 0.5 or vol_awake or v3 >= local_lift_v3 + 0.3)
        and score >= local_lift_score
    )

    min_v3 = float(getattr(settings, "building_rip_min_velocity_3s", 1.5) or 1.5)
    min_v9 = float(getattr(settings, "building_rip_min_velocity_9s", 0.8) or 0.8)
    min_score = float(getattr(settings, "building_rip_min_score", 48.0) or 48.0)
    rip_move = max(local_move, off_low, session_move)
    min_move = float(getattr(settings, "building_rip_min_move_pct", 2.0) or 2.0)
    max_move = float(getattr(settings, "building_rip_max_move_pct", 55.0) or 55.0)
    mid_rip = bool(
        not local_base_lift
        and v3 >= min_v3
        and (vol_awake or volume_surge >= min_surge)
        and (v9 >= min_v9 or vol_awake)
        and score >= min_score
        and min_move <= rip_move <= max_move
    )
    if not local_base_lift and not mid_rip:
        if has_local_base and measured_local_lift > 0 and v3 < local_lift_v3:
            return False, f"building_rip_local_lift_velocity3s<{local_lift_v3:g}"
        if v3 < min_v3:
            return False, f"building_rip_velocity3s<{min_v3:g}"
        if not vol_awake and volume_surge < min_surge:
            return False, f"building_rip_volume_surge<{min_surge:g}"
        if score < min_score and score < local_lift_score:
            return False, f"building_rip_score<{min_score:g}"
        return False, f"building_rip_move_outside_{min_move:g}_{max_move:g}"

    # Reject faded tops: peak already ran away and live heat is soft.
    fade_gap = float(
        getattr(settings, "building_rip_fade_peak_gap_pct", 12.0) or 12.0
    )
    compare_move = measured_local_lift if local_base_lift else rip_move
    fade_v3_floor = local_lift_v3 if local_base_lift else min_v3
    if peak_move > compare_move + fade_gap and v3 < fade_v3_floor + 0.5:
        return False, "building_rip_faded_from_peak"

    side = str(
        getattr(getattr(event, "side", None), "value", getattr(event, "side", ""))
        or row.get("side")
        or ""
    ).upper()
    if side not in ("CALL", "PUT"):
        return False, "building_rip_side_invalid"

    from app.engines.moneyness import classify_moneyness
    from app.models.schemas import Side as _Side

    strike = float(getattr(event, "strike", 0) or row.get("strike") or 0)
    spot = float(getattr(snap, "spot", 0) or 0)
    atm = float(getattr(snap, "atmStrike", 0) or 0)
    if strike <= 0 or spot <= 0:
        return False, "building_rip_moneyness_unavailable"
    money = classify_moneyness(
        _Side(side),
        strike,
        spot,
        symbol=str(getattr(snap, "symbol", "") or ""),
        atm=atm if atm > 0 else None,
    )
    if money not in ("ATM", "ITM"):
        return False, f"building_rip_requires_atm_itm_{money.lower()}"

    # Chart align OR option-led confirmation — prove something is helping the lift.
    from app.engines.spot_direction import side_aligned_with_chart
    from app.engines.symbol_cooldown import side_aligned_with_breadth

    chart_ok = False
    if getattr(snap, "spotChart", None) is not None:
        chart_ok = bool(side_aligned_with_chart(_Side(side), snap.spotChart))
    breadth_bias = str(
        getattr(getattr(snap, "breadth", None), "bias", "") or ""
    )
    breadth_ok = bool(side_aligned_with_breadth(side, breadth_bias))
    absolute_volume = float(
        getattr(event, "volume", 0)
        or row.get("volume")
        or row.get("absoluteVolume")
        or 0
    )
    live_cvd = False
    live_cvd_accel = False
    try:
        from app.engines.advanced_indicators import (
            option_cvd_acceleration_confirms_buying,
            option_cvd_confirms_buying,
        )

        live_cvd = bool(
            option_cvd_confirms_buying(snap, strike, _Side(side))
        )
        live_cvd_accel = bool(
            option_cvd_acceleration_confirms_buying(snap, strike, _Side(side))
        )
    except Exception:
        live_cvd = False
        live_cvd_accel = False
    displacement = bool(
        row.get("ictDisplacement")
        or row.get("displacement")
        or getattr(ict, "displacement", False)
    )
    option_led = bool(
        vol_awake
        and (
            absolute_volume >= 25_000
            or row.get("optionCvdBuying")
            or row.get("orderflowConfirmed")
            or row.get("cvdBuying")
            or live_cvd
            or live_cvd_accel
            or volume_surge >= min_surge + 0.4
        )
    )
    helpers: list[str] = []
    if vol_awake:
        helpers.append("vol_awaken")
    if chart_ok:
        helpers.append("chart_align")
    if breadth_ok:
        helpers.append("breadth_align")
    if live_cvd or row.get("cvdBuying") or row.get("optionCvdBuying"):
        helpers.append("cvd_buying")
    if live_cvd_accel:
        helpers.append("cvd_accel")
    if displacement:
        helpers.append("displacement")
    if volume_surge >= min_surge:
        helpers.append("volume_surge")
    # Aug19 sudden-lift board — FTV structure + ICT confluence + LTP lift.
    try:
        from app.engines.building_lift_helpers import evaluate_building_lift_helpers

        board = evaluate_building_lift_helpers(snap=snap, alert=row)
        for h in board.helpers:
            if h not in helpers:
                helpers.append(h)
        if board.helping:
            # Something is actively helping — treat as option-led confirmation.
            option_led = True
    except Exception:
        pass
    if not chart_ok and not option_led and not breadth_ok:
        return False, "building_rip_needs_chart_or_option_led"
    if not helpers:
        return False, "building_rip_needs_helper_confirmation"

    # Stamp helpers onto the live alert so FTV policy / UI can see what helped.
    if isinstance(alert, dict):
        alert["ictBuildingRipReady"] = True
        alert["buildingRipHelpers"] = list(helpers)
        alert["buildingRipHelpersOk"] = True
        alert["buildingLiftHelping"] = True
        alert["ictBaseReadinessReason"] = (
            "building_local_base_lift_ready"
            if local_base_lift
            else "building_rip_bullish_ready"
        )

    if local_base_lift:
        return True, "building_local_base_lift_ready"
    return True, "building_rip_bullish_ready"


def _local_base_pad_premium_band_ok(
    premium: float,
    *,
    settings: Any,
    max_premium_setting: str,
    reason_prefix: str,
) -> tuple[bool, str]:
    """Require LTP inside the slow-coil → fast-lift pad band (default ₹18–₹220)."""
    if premium <= 0:
        return False, f"{reason_prefix}_premium_missing"
    min_prem = float(
        getattr(settings, "local_base_pad_capture_min_premium_inr", 18.0) or 18.0
    )
    max_prem = float(
        getattr(settings, max_premium_setting, 220.0)
        or getattr(settings, "local_base_pad_capture_max_premium_inr", 220.0)
        or 220.0
    )
    if premium < min_prem:
        return False, f"{reason_prefix}_premium_below_{min_prem:g}"
    if premium > max_prem:
        return False, f"{reason_prefix}_premium_above_{max_prem:g}"
    return True, ""


def _fast_bullish_local_base_readiness(
    *,
    snap: Optional[SymbolSnapshot],
    event: Any = None,
    ict: Any = None,
    alert: Optional[dict[str, Any]] = None,
    settings: Any = None,
) -> tuple[bool, str]:
    """Authorize fast-moving local-base lifts inside the ₹18–₹220 pad band."""
    s = settings or get_settings()
    if not bool(getattr(s, "fast_bullish_local_base_capture_enabled", True)):
        return False, ""
    row = alert if isinstance(alert, dict) else {}
    if snap is None:
        return False, "fast_bullish_chart_missing"

    premium = float(
        getattr(event, "premium", 0) or row.get("premium") or 0
    )
    prem_ok, prem_reason = _local_base_pad_premium_band_ok(
        premium,
        settings=s,
        max_premium_setting="fast_bullish_local_base_max_premium_inr",
        reason_prefix="fast_bullish",
    )
    if not prem_ok:
        return False, prem_reason

    base_move = float(
        getattr(ict, "base_relative_move_pct", 0)
        or row.get("ictBaseRelativeMovePct")
        or row.get("localBaseMovePct")
        or 0
    )
    lo = float(getattr(s, "fast_bullish_local_base_min_move_pct", 5.0) or 5.0)
    hi = float(getattr(s, "fast_bullish_local_base_max_move_pct", 45.0) or 45.0)
    if not (lo <= base_move <= hi + 1e-6):
        return False, f"fast_bullish_pad_outside_{lo:g}_{hi:g}"

    structured = bool(
        getattr(ict, "flat_then_vertical", False)
        or getattr(ict, "active", False)
        or row.get("ictFlatThenVertical")
        or row.get("ictBreakout")
    )
    if not structured:
        return False, "fast_bullish_structure_missing"

    from app.engines.bullish_local_base import bullish_local_base_prediction

    pred = bullish_local_base_prediction(snap, event, ict, alert=row)
    predictor_active = bool(
        pred.get("active") or row.get("bullishLocalBaseActive")
    )
    if not predictor_active:
        volume_awake = bool(
            getattr(ict, "volume_awakening", False)
            or row.get("ictVolumeAwakening")
            or row.get("volumeAwaken")
        )
        if not volume_awake:
            return False, "fast_bullish_volume_not_awake"
        from app.engines.local_base_chart_bypass import local_base_momentum_turn
        from app.models.schemas import Side as _Side

        side_v = str(
            getattr(getattr(event, "side", None), "value", getattr(event, "side", ""))
            or row.get("side")
            or ""
        ).upper()
        if side_v not in ("CALL", "PUT"):
            return False, "fast_bullish_side_invalid"
        if not local_base_momentum_turn(
            _Side(side_v), snap, event=event, alert=row,
        ):
            return False, "fast_bullish_momentum_turn_missing"
        v3 = float(
            getattr(event, "velocity_3s", 0) or row.get("velocity3s") or 0
        )
        if v3 < 0:
            return False, "fast_bullish_velocity_negative"
        pad_floor = float(
            getattr(s, "ict_v_rip_pad_min_move_pct", 2.0) or 2.0
        )
        min_v3 = float(
            getattr(s, "fast_bullish_local_base_min_velocity_3s", 0.8) or 0.8
        )
        trough_eps = float(
            getattr(s, "bullish_local_base_trough_velocity_eps", 0.05) or 0.05
        )
        at_pad_with_volume = volume_awake and base_move + 1e-6 >= pad_floor
        trough_awakening = at_pad_with_volume and 0 <= v3 <= trough_eps
        if not trough_awakening and v3 < min_v3:
            return False, f"fast_bullish_velocity3s<{min_v3:g}"

    from app.engines.moneyness import classify_moneyness
    from app.models.schemas import Side

    side = str(
        getattr(getattr(event, "side", None), "value", getattr(event, "side", ""))
        or row.get("side")
        or ""
    ).upper()
    if side not in ("CALL", "PUT"):
        return False, "fast_bullish_side_invalid"
    strike = float(getattr(event, "strike", 0) or row.get("strike") or 0)
    spot = float(getattr(snap, "spot", 0) or 0)
    atm = float(getattr(snap, "atmStrike", 0) or 0)
    if strike <= 0 or spot <= 0:
        return False, "fast_bullish_moneyness_unavailable"
    money = classify_moneyness(
        Side(side),
        strike,
        spot,
        symbol=str(getattr(snap, "symbol", "") or ""),
        atm=atm if atm > 0 else None,
    )
    if money not in ("ATM", "ITM"):
        return False, f"fast_bullish_requires_atm_itm_{money.lower()}"
    if isinstance(alert, dict):
        alert["fastBullishLocalBaseReady"] = True
        alert["bullishLocalBaseActive"] = True
        alert["ictBaseReadinessReason"] = "fast_bullish_local_base_ready"
    return True, "fast_bullish_local_base_ready"


SLOW_GRIND_ARMED_TROUGH_READY = "slow_grind_armed_trough_ready"


SLOW_GRIND_CONSOLIDATION_BASE_READY = "slow_grind_consolidation_base_ready"


def _slow_grind_consolidation_base_readiness(
    *,
    snap: Optional[SymbolSnapshot],
    event: Any = None,
    ict: Any = None,
    alert: Optional[dict[str, Any]] = None,
    settings: Any = None,
) -> tuple[bool, str]:
    """Authorize slow-coil on a mid-day consolidation base before the afternoon breakout."""
    s = settings or get_settings()
    if not bool(getattr(s, "slow_grind_consolidation_base_enabled", True)):
        return False, ""
    row = alert if isinstance(alert, dict) else {}
    if snap is None:
        return False, "slow_grind_consolidation_chart_missing"
    if bool(row.get("ictMidRipCoil") or row.get("midRipCoil")):
        return False, "slow_grind_consolidation_mid_rip_coil"
    if bool(
        row.get("ictArmedBaseLaunch")
        or row.get("ictEliteBaseReady")
        or row.get("ictFirstLift")
    ):
        return False, "slow_grind_consolidation_strict_path_active"

    from app.engines.morning_premium_capture import in_afternoon_premium_capture_window

    if not in_afternoon_premium_capture_window():
        return False, "slow_grind_consolidation_outside_afternoon_window"

    tier = str(
        getattr(event, "tier", "")
        or row.get("tier")
        or ""
    ).upper()
    if tier not in ("WATCH", "BUILDING"):
        return False, f"slow_grind_consolidation_tier_{tier.lower() or 'missing'}"

    premium = float(
        getattr(event, "premium", 0) or row.get("premium") or 0
    )
    prem_ok, prem_reason = _local_base_pad_premium_band_ok(
        premium,
        settings=s,
        max_premium_setting="slow_grind_consolidation_base_max_premium_inr",
        reason_prefix="slow_grind_consolidation",
    )
    if not prem_ok:
        return False, prem_reason

    off_low = max(0.0, float(row.get("offLowMovePct") or 0))
    trough_max = float(
        getattr(s, "slow_grind_armed_trough_max_off_low_pct", 2.0) or 2.0
    )
    min_off = float(
        getattr(s, "slow_grind_consolidation_base_min_off_low_pct", 3.0) or 3.0
    )
    max_off = float(
        getattr(s, "slow_grind_consolidation_base_max_off_low_pct", 30.0) or 30.0
    )
    if off_low <= trough_max + 1e-6:
        return False, "slow_grind_consolidation_at_session_trough"
    if not (min_off <= off_low <= max_off + 1e-6):
        return False, f"slow_grind_consolidation_off_low_outside_{min_off:g}_{max_off:g}"

    peak_move = float(
        getattr(event, "peak_move_pct", 0)
        or row.get("peakMovePct")
        or 0
    )
    max_peak = float(
        getattr(s, "slow_grind_consolidation_base_max_peak_move_pct", 24.0) or 24.0
    )
    if peak_move > max_peak + 1e-6:
        return False, f"slow_grind_consolidation_peak>{max_peak:g}"

    base_armed = bool(
        getattr(ict, "base_armed", False)
        or row.get("ictBaseArmed")
        or getattr(ict, "local_swing_base", False)
    )
    if not base_armed:
        return False, "slow_grind_consolidation_base_not_armed"

    base_move = float(
        getattr(ict, "base_relative_move_pct", 0)
        or row.get("ictBaseRelativeMovePct")
        or row.get("localBaseMovePct")
        or 0
    )
    lo = float(
        getattr(s, "slow_grind_consolidation_base_min_move_pct", 2.0) or 2.0
    )
    hi = float(
        getattr(s, "slow_grind_consolidation_base_max_move_pct", 22.0) or 22.0
    )
    if not (lo <= base_move <= hi + 1e-6):
        return False, f"slow_grind_consolidation_pad_outside_{lo:g}_{hi:g}"

    v3 = float(
        getattr(event, "velocity_3s", 0) or row.get("velocity3s") or 0
    )
    min_v3 = float(
        getattr(s, "slow_grind_sudden_lift_min_velocity_3s", -0.8) or -0.8
    )
    max_v3 = float(
        getattr(s, "slow_grind_sudden_lift_max_velocity_3s", 1.5) or 1.5
    )
    if v3 < min_v3:
        return False, f"slow_grind_consolidation_velocity3s<{min_v3:g}"
    if v3 > max_v3:
        return False, f"slow_grind_consolidation_velocity3s>{max_v3:g}"

    quality = float(
        getattr(ict, "flat_vertical_quality", 0)
        or row.get("flatVerticalQuality")
        or 0
    )
    min_quality = float(
        getattr(s, "slow_grind_consolidation_base_min_flat_quality", 35.0) or 35.0
    )
    if quality < min_quality:
        return False, f"slow_grind_consolidation_quality<{min_quality:g}"

    samples = int(
        getattr(ict, "armed_base_samples", 0)
        or row.get("ictArmedBaseSamples")
        or 0
    )
    min_samples = int(
        getattr(s, "slow_grind_consolidation_base_min_coil_samples", 6) or 6
    )
    if samples < min_samples:
        return False, f"slow_grind_consolidation_samples<{min_samples}"

    side = str(
        getattr(getattr(event, "side", None), "value", getattr(event, "side", ""))
        or row.get("side")
        or ""
    ).upper()
    signal_ct, _signals = _slow_grind_impending_lift_signals(
        side=side,
        snap=snap,
        ict=ict,
        row=row,
        settings=s,
    )
    min_signals = int(
        getattr(s, "slow_grind_consolidation_base_min_impending_signals", 2) or 2
    )
    if signal_ct < min_signals:
        return False, f"slow_grind_consolidation_impending_signals<{min_signals}"

    structured = bool(
        getattr(ict, "flat_then_vertical", False)
        or getattr(ict, "active", False)
        or row.get("ictFlatThenVertical")
        or row.get("ictBreakout")
        or quality >= min_quality
    )
    if not structured:
        return False, "slow_grind_consolidation_structure_missing"

    from app.engines.moneyness import classify_moneyness
    from app.models.schemas import Side

    if side not in ("CALL", "PUT"):
        return False, "slow_grind_consolidation_side_invalid"
    strike = float(getattr(event, "strike", 0) or row.get("strike") or 0)
    spot = float(getattr(snap, "spot", 0) or 0)
    atm = float(getattr(snap, "atmStrike", 0) or 0)
    if strike <= 0 or spot <= 0:
        return False, "slow_grind_consolidation_moneyness_unavailable"
    money = classify_moneyness(
        Side(side),
        strike,
        spot,
        symbol=str(getattr(snap, "symbol", "") or ""),
        atm=atm if atm > 0 else None,
    )
    if money not in ("ATM", "ITM"):
        return False, f"slow_grind_consolidation_requires_atm_itm_{money.lower()}"
    if isinstance(alert, dict):
        alert["slowGrindSuddenLiftReady"] = True
        alert["ictSlowGrindSuddenLift"] = True
        alert["slowGrindConsolidationBase"] = True
        alert["ictSlowGrindConsolidationBase"] = True
        alert["ictBaseReadinessReason"] = SLOW_GRIND_CONSOLIDATION_BASE_READY
    return True, SLOW_GRIND_CONSOLIDATION_BASE_READY


def _slow_grind_armed_trough_readiness(
    *,
    snap: Optional[SymbolSnapshot],
    event: Any = None,
    ict: Any = None,
    alert: Optional[dict[str, Any]] = None,
    settings: Any = None,
) -> tuple[bool, str]:
    """Authorize slow-coil at the session trough when base is armed but coil is still immature."""
    s = settings or get_settings()
    if not bool(getattr(s, "slow_grind_armed_trough_enabled", True)):
        return False, ""
    row = alert if isinstance(alert, dict) else {}
    if snap is None:
        return False, "slow_grind_armed_trough_chart_missing"
    if bool(row.get("ictMidRipCoil") or row.get("midRipCoil")):
        return False, "slow_grind_armed_trough_mid_rip_coil"
    if bool(
        row.get("ictArmedBaseLaunch")
        or row.get("ictEliteBaseReady")
        or row.get("ictFirstLift")
    ):
        return False, "slow_grind_armed_trough_strict_path_active"

    premium = float(
        getattr(event, "premium", 0) or row.get("premium") or 0
    )
    prem_ok, prem_reason = _local_base_pad_premium_band_ok(
        premium,
        settings=s,
        max_premium_setting="slow_grind_sudden_lift_max_premium_inr",
        reason_prefix="slow_grind_armed_trough",
    )
    if not prem_ok:
        return False, prem_reason

    off_low = max(0.0, float(row.get("offLowMovePct") or 0))
    max_off = float(
        getattr(s, "slow_grind_armed_trough_max_off_low_pct", 15.0) or 15.0
    )
    base_armed = bool(
        getattr(ict, "base_armed", False)
        or row.get("ictBaseArmed")
        or getattr(ict, "local_swing_base", False)
    )
    v_rip_ready = bool(
        getattr(ict, "v_rip_ready", False)
        or row.get("ictVRipReady")
    )
    if not base_armed:
        return False, "slow_grind_armed_trough_base_not_armed"

    quality = float(
        getattr(ict, "flat_vertical_quality", 0)
        or row.get("flatVerticalQuality")
        or 0
    )
    min_quality = float(
        getattr(s, "slow_grind_sudden_lift_min_flat_quality", 50.0) or 50.0
    )
    if quality >= min_quality:
        return False, "slow_grind_armed_trough_quality_mature"
    if bool(row.get("ictFlatThenVertical") and row.get("ictBreakout")):
        return False, "slow_grind_armed_trough_ftv_confirmed"

    if not (v_rip_ready or off_low <= max_off + 1e-6):
        return False, "slow_grind_armed_trough_not_at_trough"

    base_move = float(
        getattr(ict, "base_relative_move_pct", 0)
        or row.get("ictBaseRelativeMovePct")
        or row.get("localBaseMovePct")
        or 0
    )
    lo = float(getattr(s, "slow_grind_armed_trough_min_move_pct", 0.0) or 0.0)
    hi = float(getattr(s, "slow_grind_armed_trough_max_move_pct", 20.0) or 20.0)
    if not (lo <= base_move <= hi + 1e-6):
        return False, f"slow_grind_armed_trough_pad_outside_{lo:g}_{hi:g}"

    v3 = float(
        getattr(event, "velocity_3s", 0) or row.get("velocity3s") or 0
    )
    min_v3 = float(
        getattr(s, "slow_grind_sudden_lift_min_velocity_3s", -0.8) or -0.8
    )
    max_v3 = float(
        getattr(s, "slow_grind_sudden_lift_max_velocity_3s", 1.5) or 1.5
    )
    if v3 < min_v3:
        return False, f"slow_grind_armed_trough_velocity3s<{min_v3:g}"
    if v3 > max_v3:
        return False, f"slow_grind_armed_trough_velocity3s>{max_v3:g}"

    side = str(
        getattr(getattr(event, "side", None), "value", getattr(event, "side", ""))
        or row.get("side")
        or ""
    ).upper()
    signal_ct, _signals = _slow_grind_impending_lift_signals(
        side=side,
        snap=snap,
        ict=ict,
        row=row,
        settings=s,
    )
    min_signals = int(
        getattr(s, "slow_grind_armed_trough_min_impending_signals", 1) or 1
    )
    if signal_ct < min_signals:
        return False, f"slow_grind_armed_trough_impending_signals<{min_signals}"

    from app.engines.moneyness import classify_moneyness
    from app.models.schemas import Side

    if side not in ("CALL", "PUT"):
        return False, "slow_grind_armed_trough_side_invalid"
    strike = float(getattr(event, "strike", 0) or row.get("strike") or 0)
    spot = float(getattr(snap, "spot", 0) or 0)
    atm = float(getattr(snap, "atmStrike", 0) or 0)
    if strike <= 0 or spot <= 0:
        return False, "slow_grind_armed_trough_moneyness_unavailable"
    money = classify_moneyness(
        Side(side),
        strike,
        spot,
        symbol=str(getattr(snap, "symbol", "") or ""),
        atm=atm if atm > 0 else None,
    )
    if money not in ("ATM", "ITM"):
        return False, f"slow_grind_armed_trough_requires_atm_itm_{money.lower()}"
    if isinstance(alert, dict):
        alert["slowGrindSuddenLiftReady"] = True
        alert["ictSlowGrindSuddenLift"] = True
        alert["slowGrindArmedTrough"] = True
        alert["ictSlowGrindArmedTrough"] = True
        alert["ictBaseReadinessReason"] = SLOW_GRIND_ARMED_TROUGH_READY
    return True, SLOW_GRIND_ARMED_TROUGH_READY


def _slow_grind_impending_lift_signals(
    *,
    side: str,
    snap: SymbolSnapshot,
    ict: Any,
    row: dict[str, Any],
    settings: Any,
) -> tuple[int, list[str]]:
    """Count pre-breakout lift hints during a slow pad-band coil (no volume spike yet)."""
    signals: list[str] = []
    chart = getattr(snap, "spotChart", None)
    if chart is None:
        return 0, signals

    side_u = str(side or "").upper()
    macd_bias = str(getattr(chart, "macdBias", "") or "NEUTRAL").upper()
    hist = float(getattr(chart, "macdHistogram", 0) or 0)
    macd_line = float(getattr(chart, "macd", 0) or 0)
    macd_sig = float(getattr(chart, "macdSignal", 0) or 0)
    rsi = float(getattr(chart, "rsi", 50) or 50)
    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0)
    mom15 = float(getattr(chart, "momentum15Pct", 0) or 0)

    if side_u == "PUT":
        if macd_bias == "BEARISH" or hist < 0:
            signals.append("macd_bearish_building")
        if macd_line <= macd_sig + 0.05 and hist >= -1.0:
            signals.append("macd_cross_imminent")
        if 28.0 <= rsi <= 58.0:
            signals.append("rsi_neutral_coil")
        if mom5 <= mom15:
            signals.append("momentum_soft_bearish")
    elif side_u == "CALL":
        if macd_bias == "BULLISH" or hist > 0:
            signals.append("macd_bullish_building")
        if macd_line >= macd_sig - 0.05 and hist <= 1.0:
            signals.append("macd_cross_imminent")
        if 42.0 <= rsi <= 72.0:
            signals.append("rsi_neutral_coil")
        if mom5 >= mom15:
            signals.append("momentum_soft_bullish")

    quality = float(
        getattr(ict, "flat_vertical_quality", 0)
        or row.get("flatVerticalQuality")
        or 0
    )
    min_quality = float(
        getattr(settings, "slow_grind_sudden_lift_min_flat_quality", 50.0) or 50.0
    )
    samples = int(
        getattr(ict, "armed_base_samples", 0)
        or row.get("ictArmedBaseSamples")
        or 0
    )
    min_samples = int(
        getattr(settings, "slow_grind_sudden_lift_min_coil_samples", 6) or 6
    )
    if quality >= min_quality and samples >= min_samples:
        signals.append("tight_armed_coil")

    ca = getattr(snap, "chartAnalysis", None)
    sq = getattr(ca, "squeeze", None) if ca is not None else None
    if isinstance(sq, dict) and sq:
        bars_on = int(sq.get("bars_on") or 0)
        bsf = int(sq.get("bars_since_fired") or -1)
        direction = str(sq.get("direction") or "NEUTRAL").upper()
        target = "BEARISH" if side_u == "PUT" else "BULLISH"
        if bars_on >= 3:
            signals.append("squeeze_compressed")
        window = int(getattr(settings, "squeeze_fresh_window_bars", 3) or 3)
        if 0 <= bsf <= window and direction == target:
            signals.append("squeeze_fresh_release")

    if bool(
        getattr(ict, "v_rip_ready", False)
        or row.get("ictVRipReady")
        or getattr(ict, "base_armed", False)
        or row.get("ictBaseArmed")
    ):
        signals.append("session_trough_armed")

    volume_awake = bool(
        getattr(ict, "volume_awakening", False)
        or row.get("ictVolumeAwakening")
        or row.get("volumeAwaken")
    )
    v3 = float(getattr(ict, "velocity_3s", 0) or row.get("velocity3s") or 0)
    max_v3 = float(
        getattr(settings, "slow_grind_sudden_lift_max_velocity_3s", 1.5) or 1.5
    )
    if volume_awake and v3 <= max_v3:
        signals.append("volume_awakening_pre_spike")

    from app.engines.spot_direction import side_aligned_with_chart

    if side_u in ("CALL", "PUT"):
        from app.models.schemas import Side as _Side

        if side_aligned_with_chart(_Side(side_u), chart):
            signals.append("chart_direction_aligned")

    return len(signals), signals


def _slow_grind_sudden_lift_readiness(
    *,
    snap: Optional[SymbolSnapshot],
    event: Any = None,
    ict: Any = None,
    alert: Optional[dict[str, Any]] = None,
    settings: Any = None,
) -> tuple[bool, str]:
    """Authorize slow pad-band coil when impending-lift signals stack before the spike."""
    s = settings or get_settings()
    if not bool(getattr(s, "slow_grind_sudden_lift_enabled", True)):
        return False, ""
    armed_trough_ok, armed_trough_reason = _slow_grind_armed_trough_readiness(
        snap=snap,
        event=event,
        ict=ict,
        alert=alert,
        settings=s,
    )
    if armed_trough_ok:
        return True, armed_trough_reason
    consolidation_ok, consolidation_reason = _slow_grind_consolidation_base_readiness(
        snap=snap,
        event=event,
        ict=ict,
        alert=alert,
        settings=s,
    )
    if consolidation_ok:
        return True, consolidation_reason
    row = alert if isinstance(alert, dict) else {}
    if snap is None:
        return False, "slow_grind_chart_missing"

    premium = float(
        getattr(event, "premium", 0) or row.get("premium") or 0
    )
    prem_ok, prem_reason = _local_base_pad_premium_band_ok(
        premium,
        settings=s,
        max_premium_setting="slow_grind_sudden_lift_max_premium_inr",
        reason_prefix="slow_grind",
    )
    if not prem_ok:
        return False, prem_reason

    base_move = float(
        getattr(ict, "base_relative_move_pct", 0)
        or row.get("ictBaseRelativeMovePct")
        or row.get("localBaseMovePct")
        or 0
    )
    lo = float(getattr(s, "slow_grind_sudden_lift_min_move_pct", 2.0) or 2.0)
    hi = float(getattr(s, "slow_grind_sudden_lift_max_move_pct", 30.0) or 30.0)
    signal_ct, signals = _slow_grind_impending_lift_signals(
        side=str(
            getattr(getattr(event, "side", None), "value", getattr(event, "side", ""))
            or row.get("side")
            or ""
        ).upper(),
        snap=snap,
        ict=ict,
        row=row,
        settings=s,
    )
    if "volume_awakening_pre_spike" in signals:
        bonus = float(
            getattr(s, "slow_grind_sudden_lift_handoff_move_bonus_pct", 8.0) or 8.0
        )
        hi = hi + bonus
    if not (lo <= base_move <= hi + 1e-6):
        return False, f"slow_grind_pad_outside_{lo:g}_{hi:g}"

    v3 = float(
        getattr(event, "velocity_3s", 0) or row.get("velocity3s") or 0
    )
    min_v3 = float(
        getattr(s, "slow_grind_sudden_lift_min_velocity_3s", -0.8) or -0.8
    )
    max_v3 = float(
        getattr(s, "slow_grind_sudden_lift_max_velocity_3s", 1.5) or 1.5
    )
    if v3 < min_v3:
        return False, f"slow_grind_velocity3s<{min_v3:g}"
    if v3 > max_v3:
        return False, f"slow_grind_velocity3s>{max_v3:g}"

    base_armed = bool(
        getattr(ict, "base_armed", False)
        or row.get("ictBaseArmed")
        or getattr(ict, "local_swing_base", False)
    )
    if not base_armed:
        return False, "slow_grind_base_not_armed"

    structured = bool(
        getattr(ict, "flat_then_vertical", False)
        or getattr(ict, "active", False)
        or row.get("ictFlatThenVertical")
        or row.get("ictBreakout")
        or float(getattr(ict, "flat_vertical_quality", 0) or 0) >= float(
            getattr(s, "slow_grind_sudden_lift_min_flat_quality", 50.0) or 50.0
        )
    )
    if not structured:
        return False, "slow_grind_structure_missing"

    side = str(
        getattr(getattr(event, "side", None), "value", getattr(event, "side", ""))
        or row.get("side")
        or ""
    ).upper()
    if side not in ("CALL", "PUT"):
        return False, "slow_grind_side_invalid"

    min_signals = int(
        getattr(s, "slow_grind_sudden_lift_min_impending_signals", 2) or 2
    )
    if signal_ct < min_signals:
        return False, f"slow_grind_impending_signals<{min_signals}"

    from app.engines.moneyness import classify_moneyness
    from app.models.schemas import Side

    strike = float(getattr(event, "strike", 0) or row.get("strike") or 0)
    spot = float(getattr(snap, "spot", 0) or 0)
    atm = float(getattr(snap, "atmStrike", 0) or 0)
    if strike <= 0 or spot <= 0:
        return False, "slow_grind_moneyness_unavailable"
    money = classify_moneyness(
        Side(side),
        strike,
        spot,
        symbol=str(getattr(snap, "symbol", "") or ""),
        atm=atm if atm > 0 else None,
    )
    if money not in ("ATM", "ITM"):
        return False, f"slow_grind_requires_atm_itm_{money.lower()}"
    if isinstance(alert, dict):
        alert["slowGrindSuddenLiftReady"] = True
        alert["ictSlowGrindSuddenLift"] = True
        alert["ictBaseReadinessReason"] = "slow_grind_sudden_lift_ready"
    return True, "slow_grind_sudden_lift_ready"


def _v_rip_lane_active(
    *,
    v_rip_ready: bool,
    base_move_pct: float,
    settings: Any,
) -> bool:
    """V-rip sleeve is active when move is inside the 2–25% session-trough pad."""
    if not v_rip_ready:
        return False
    lo = float(getattr(settings, "ict_v_rip_min_move_pct", 2.0) or 2.0)
    hi = float(getattr(settings, "ict_v_rip_max_move_pct", 25.0) or 25.0)
    return lo <= float(base_move_pct or 0) <= hi + 1e-6


def first_lift_entry_ready(
    *,
    snap: Optional[SymbolSnapshot],
    event: Any = None,
    ict: Any = None,
    alert: Optional[dict[str, Any]] = None,
    day_mode: str = "",
    state: Any = None,
) -> bool:
    """Return whether a radar first lift has strict order-entry confirmation."""
    return first_lift_entry_readiness(
        snap=snap,
        event=event,
        ict=ict,
        alert=alert,
        day_mode=day_mode,
        state=state,
    )[0]


def first_lift_entry_readiness(
    *,
    snap: Optional[SymbolSnapshot],
    event: Any = None,
    ict: Any = None,
    alert: Optional[dict[str, Any]] = None,
    day_mode: str = "",
    state: Any = None,
) -> tuple[bool, str]:
    """Strict early-entry proof for a local-base first lift.

    Radar intentionally exposes softer first lifts. An order may use that early
    signal only when the base quality, premium heat, volume and live index turn
    agree. This is symmetric: CALL requires an improving bullish turn and PUT an
    improving bearish turn.
    """
    settings = get_settings()
    from app.engines.explosion_detector import enrich_alert_armed_evidence

    row = enrich_alert_armed_evidence(alert if isinstance(alert, dict) else {})
    persisted = (
        dict(row.get("ictArmedEvidence") or {})
        if row.get("ictBaseArmed")
        and str((row.get("ictArmedEvidence") or {}).get("armedAt") or "")
        == str(row.get("ictBaseArmedAt") or "")
        else {}
    )
    if bool(row.get("ictMidRipCoil") or row.get("midRipCoil")):
        return False, "mid_rip_armed_coil_rejected"

    # BUILDING bullish-rip sleeve — mid-rip OK while still expanding to max.
    # Runs before first-lift chart gate so option-led BUILDING rips still authorize.
    building_ok, building_reason = building_rip_bullish_readiness(
        snap=snap,
        event=event,
        ict=ict,
        alert=alert,
        state=state,
    )
    if building_ok:
        return True, building_reason

    from app.engines.pad_lane_capture import extended_pad_lane_readiness

    ext_ok, ext_reason = extended_pad_lane_readiness(
        snap=snap,
        event=event,
        ict=ict,
        alert=row,
        settings=settings,
    )
    if ext_ok:
        return True, ext_reason

    slow_ok, slow_reason = _slow_grind_sudden_lift_readiness(
        snap=snap,
        event=event,
        ict=ict,
        alert=row,
        settings=settings,
    )
    if slow_ok:
        return True, slow_reason

    fast_ok, fast_reason = _fast_bullish_local_base_readiness(
        snap=snap,
        event=event,
        ict=ict,
        alert=row,
        settings=settings,
    )
    if fast_ok:
        return True, fast_reason

    from app.engines.early_radar_pad_capture import (
        building_armed_prelaunch_entry_readiness,
        building_coil_pad_entry_readiness,
        building_coil_pad_live_blocked,
        early_radar_pad_entry_readiness,
    )

    prelaunch_ok, prelaunch_reason = building_armed_prelaunch_entry_readiness(
        snap=snap,
        alert=alert if isinstance(alert, dict) else None,
        settings=settings,
    )
    if prelaunch_ok:
        return True, prelaunch_reason

    coil_blocked, coil_block_reason = building_coil_pad_live_blocked(row, settings)
    if coil_blocked:
        return False, coil_block_reason

    if isinstance(alert, dict):
        coil_ok, coil_reason = building_coil_pad_entry_readiness(
            snap=snap,
            alert=alert,
            settings=settings,
        )
        if coil_ok:
            return True, coil_reason
        pad_ok, pad_reason = early_radar_pad_entry_readiness(
            snap=snap,
            event=event,
            ict=ict,
            alert=alert,
            settings=settings,
        )
        if pad_ok:
            return True, pad_reason

    if not bool(getattr(settings, "first_lift_trade_enabled", True)):
        return False, "first_lift_trading_disabled"
    if snap is None or getattr(snap, "spotChart", None) is None:
        return False, "first_lift_chart_missing"

    first_lift = bool(
        getattr(ict, "first_lift", False)
        or row.get("ictFirstLift")
        or persisted.get("firstLift")
    )
    armed_launch = bool(
        getattr(ict, "armed_base_launch", False) is True
        or row.get("ictArmedBaseLaunch") is True
        or persisted.get("armedLaunch") is True
    )
    elite_base_ready = bool(
        getattr(ict, "elite_base_ready", False) is True
        or row.get("ictEliteBaseReady") is True
        or persisted.get("eliteBaseReady") is True
    )
    v_rip_ready = bool(
        getattr(ict, "v_rip_ready", False) is True
        or row.get("ictVRipReady") is True
    )
    sustained_lift = bool(
        getattr(ict, "armed_base_sustained_lift", False) is True
        or row.get("ictArmedBaseSustainedLift") is True
    )
    structured = bool(
        getattr(ict, "active", False)
        and getattr(ict, "flat_then_vertical", False)
    ) or bool(
        row.get("ictBreakout") and row.get("ictFlatThenVertical")
    ) or bool(
        persisted.get("activeBreakout") and persisted.get("flatThenVertical")
    )
    if not (first_lift or armed_launch or elite_base_ready or v_rip_ready) or (
        not structured and not elite_base_ready and not v_rip_ready
    ):
        return False, "first_lift_structure_not_confirmed"

    base_move = float(
        getattr(ict, "base_relative_move_pct", 0)
        or row.get("ictBaseRelativeMovePct")
        or 0
    )
    if not day_mode and state is None:
        try:
            from app.engines.daily_18pct_strategy import get_session_limits

            limits = get_session_limits()
            day_mode = str(getattr(limits, "dayMode", "") or "") if limits else ""
        except Exception:
            day_mode = day_mode or ""
    if not day_mode and state is not None:
        day_mode = str(
            (getattr(state, "dailyStrategy", None) or {}).get("dayMode")
            or ""
        )
    from app.engines.grade_a_ftv_capture import (
        alert_is_grade_a_ftv_first_lift,
        grade_a_ftv_first_lift_floors,
    )
    from app.engines.top_ftv_v_expiry_bypass import (
        alert_is_top_ftv_or_v,
        top_ftv_v_expiry_floors,
    )

    grade_a_alert = row if isinstance(row, dict) else (
        alert if isinstance(alert, dict) else {}
    )
    grade_a_lane = alert_is_grade_a_ftv_first_lift(grade_a_alert, snap)
    grade_a_floors = grade_a_ftv_first_lift_floors(settings) if grade_a_lane else {}
    top_ftv_v_lane = (
        alert_is_top_ftv_or_v(grade_a_alert, snap)
        and _expiry_worst_session(day_mode=day_mode, state=state)
    )
    top_ftv_v_floors = top_ftv_v_expiry_floors(settings) if top_ftv_v_lane else {}
    # V-rip pad relaxes quality/score/velocity floors but does not bypass armed/elite
    # orderflow, TQS, stability, or reason tagging when those stamps are present.
    v_rip_lane = _v_rip_lane_active(
        v_rip_ready=v_rip_ready,
        base_move_pct=base_move,
        settings=settings,
    )
    strict_armed_path = armed_launch or elite_base_ready

    # EXPIRY WORST: armed/first-lift must clear the same raised defensive bar.
    if not day_mode and state is None:
        try:
            from app.engines.daily_18pct_strategy import get_session_limits

            limits = get_session_limits()
            day_mode = str(getattr(limits, "dayMode", "") or "") if limits else ""
        except Exception:
            day_mode = day_mode or ""
    if _expiry_worst_session(day_mode=day_mode, state=state):
        tier = str(
            getattr(event, "tier", "")
            or row.get("tier")
            or ""
        ).upper()
        quality = float(
            getattr(ict, "flat_vertical_quality", 0)
            or row.get("flatVerticalQuality")
            or 0
        )
        score = float(
            getattr(event, "explosion_score", 0)
            or row.get("explosionScore")
            or row.get("score")
            or 0
        )
        v3 = float(
            getattr(event, "velocity_3s", 0)
            or row.get("velocity3s")
            or 0
        )
        ok, deny = _expiry_worst_defensive_rip_allowed(
            tier=tier,
            quality=quality,
            score=score,
            velocity_3s=v3,
            settings=settings,
            evidence={
                "mode": "explosion",
                "tier": tier,
                "explosionScore": score,
                "flatVerticalQuality": quality,
                "velocity3s": v3,
                "localBaseMovePct": base_move,
                "offLowMovePct": row.get("offLowMovePct"),
                "vRipReady": v_rip_ready,
                "firstLift": first_lift,
                "earlyRadarPadCapture": row.get("earlyRadarPadCapture"),
                "slowGrindSuddenLift": row.get("slowGrindSuddenLift"),
                "fastBullishLocalBase": row.get("fastBullishLocalBase"),
                "buildingRipReady": row.get("buildingRipReady"),
                "flatVerticalGrade": row.get("flatVerticalGrade"),
                "flatThenVertical": bool(
                    row.get("ictFlatThenVertical") or row.get("flatThenVertical")
                ),
                "symbol": row.get("symbol") or getattr(event, "symbol", ""),
            },
        )
        if not ok:
            return False, deny

    if v_rip_lane:
        min_move = float(
            getattr(settings, "ict_v_rip_min_move_pct", 2.0) or 2.0
        )
        max_move = float(
            getattr(settings, "ict_v_rip_max_move_pct", 25.0) or 25.0
        )
    elif grade_a_lane:
        min_move = float(grade_a_floors.get("minBaseMove", 8.0) or 8.0)
        max_move = float(grade_a_floors.get("maxBaseMove", 45.0) or 45.0)
    elif top_ftv_v_lane:
        min_move = float(top_ftv_v_floors.get("minBaseMove", 5.0) or 5.0)
        max_move = float(top_ftv_v_floors.get("maxBaseMove", 55.0) or 55.0)
    elif elite_base_ready:
        min_move = float(
            getattr(settings, "ict_elite_base_ready_min_move_pct", 2.0) or 2.0
        )
        max_move = float(
            getattr(settings, "ict_elite_base_ready_max_move_pct", 5.0) or 5.0
        )
    elif armed_launch:
        min_move = float(
            getattr(settings, "ict_armed_base_launch_min_move_pct", 5.0) or 5.0
        )
        max_move = float(
            getattr(settings, "ict_armed_base_launch_max_move_pct", 15.0) or 15.0
        )
        if first_lift:
            max_move = max(
                max_move,
                float(
                    getattr(settings, "first_lift_trade_max_move_pct", 40.0)
                    or 40.0
                ),
            )
        if sustained_lift:
            min_move = min(
                min_move,
                float(
                    getattr(settings, "ict_armed_sustained_lift_min_move_pct", 8.0)
                    or 8.0
                ),
            )
            max_move = max(
                max_move,
                float(
                    getattr(settings, "ict_armed_sustained_lift_max_move_pct", 25.0)
                    or 25.0
                ),
            )
    else:
        min_move = float(
            getattr(settings, "ict_structured_early_min_move_pct", 15.0) or 15.0
        )
        max_move = float(
            getattr(settings, "first_lift_trade_max_move_pct", 25.0) or 25.0
        )
    if not (min_move <= base_move <= max_move):
        return False, f"first_lift_base_move_outside_{min_move:g}_{max_move:g}"

    # Option-led lane: a strong ATM/ITM option can lead before the 5m index chart turns
    # and before the generic explosion-score floor is met. Evaluated here so it is not
    # subordinate to that score floor; its own high quality/velocity/volume bar gates it.
    # Only for a plain first lift — the armed/elite/v-rip paths keep their stricter
    # orderflow/stability gates below and must not be short-circuited here.
    if (
        first_lift
        and not strict_armed_path
        and not v_rip_lane
        and _option_led_first_lift_ok(
            row=row, ict=ict, event=event, snap=snap, settings=settings,
        )
    ):
        return True, "first_lift_option_led_ready"

    quality = float(
        getattr(ict, "flat_vertical_quality", 0)
        or row.get("flatVerticalQuality")
        or 0
    )
    quality = max(quality, float(persisted.get("flatVerticalQuality") or 0))
    if v_rip_lane:
        min_quality = float(
            getattr(settings, "ict_v_rip_min_quality", 50.0) or 50.0
        )
        min_score = float(
            getattr(settings, "ict_v_rip_min_score", 40.0) or 40.0
        )
    elif elite_base_ready and not armed_launch:
        min_quality = float(
            getattr(settings, "ict_elite_base_ready_min_quality", 55.0) or 55.0
        )
        min_score = float(
            getattr(settings, "ict_elite_base_ready_min_score", 45.0) or 45.0
        )
    elif grade_a_lane:
        min_quality = float(grade_a_floors.get("minQuality", 65.0) or 65.0)
        min_score = float(grade_a_floors.get("minScore", 28.0) or 28.0)
    elif top_ftv_v_lane:
        min_quality = 0.0
        min_score = float(top_ftv_v_floors.get("minScore", 12.0) or 12.0)
    elif armed_launch:
        min_quality = float(
            getattr(settings, "ict_armed_base_launch_min_quality", 65.0) or 65.0
        )
        min_score = float(
            getattr(settings, "ict_armed_base_launch_min_score", 65.0) or 65.0
        )
    else:
        min_quality = float(
            getattr(settings, "first_lift_trade_min_quality", 65.0) or 65.0
        )
        min_score = float(
            getattr(settings, "first_lift_trade_min_score", 62.0) or 62.0
        )
    from app.engines.early_radar_pad_capture import (
        early_pad_context_active,
        early_pad_quality_floor,
        early_pad_score_floor,
    )

    if early_pad_context_active(row, local_base_move_pct=base_move, settings=settings):
        min_score = min(min_score, early_pad_score_floor(settings))
        min_quality = min(min_quality, early_pad_quality_floor(settings))
    # Helper-confirmed lane: a base lift with enough independent confirmations may enter on
    # a lower quality/score/velocity bar (the confirmations ARE the proof it's a real FTV).
    helper_row = dict(row)
    helper_row["buildingHelperCount"] = max(
        int(helper_row.get("buildingHelperCount") or 0),
        int(float(persisted.get("helperCount") or 0)),
    )
    helper_confirmed, _helper_ct = _helper_confirmed_lift(
        row=helper_row, ict=ict, snap=snap, event=event, settings=settings,
    )
    if helper_confirmed:
        min_quality = min(
            min_quality,
            float(getattr(settings, "first_lift_helper_confirm_min_quality", 50.0) or 50.0),
        )
        min_score = min(
            min_score,
            float(getattr(settings, "first_lift_helper_confirm_min_score", 45.0) or 45.0),
        )
    if quality < min_quality:
        return False, f"first_lift_quality<{min_quality:g}"

    score = float(
        getattr(event, "explosion_score", 0)
        or row.get("explosionScore")
        or row.get("score")
        or 0
    )
    score = max(score, float(persisted.get("explosionScore") or 0))
    if score < min_score:
        return False, f"first_lift_score<{min_score:g}"

    v3 = float(
        getattr(event, "velocity_3s", 0)
        or row.get("velocity3s")
        or row.get("velocity_3s")
        or 0
    )
    v9 = float(
        getattr(event, "velocity_9s", 0)
        or row.get("velocity9s")
        or row.get("velocity_9s")
        or 0
    )
    volume_surge = float(
        getattr(event, "volume_surge", 0)
        or getattr(ict, "volume_surge", 0)
        or row.get("volumeSurge")
        or 0
    )
    volume_awake = bool(
        getattr(ict, "volume_awakening", False)
        or row.get("ictVolumeAwakening")
        or row.get("volumeAwaken")
    )
    live_v3 = v3
    v3 = max(v3, float(persisted.get("velocity3s") or 0))
    v9 = max(v9, float(persisted.get("velocity9s") or 0))
    if live_v3 < 0:
        return False, "first_lift_live_velocity_negative"
    if v_rip_lane:
        min_v3 = float(
            getattr(settings, "ict_v_rip_min_velocity_3s", 1.2) or 1.2
        )
        min_v9 = float(
            getattr(settings, "ict_v_rip_min_velocity_9s", 0.8) or 0.8
        )
        pad_lo = float(
            getattr(settings, "ict_v_rip_pad_min_move_pct", 2.0) or 2.0
        )
        if volume_awake and base_move + 1e-6 >= pad_lo:
            # Volume awakening at the session trough IS the lift trigger — do not
            # require v3 to spike first (Aug24 NIFTY PUT 24250/24300 at ~7% pad).
            min_v3 = 0.0
            min_v9 = 0.0
    else:
        min_v3 = float(
            getattr(
                settings,
                (
                    "ict_elite_base_ready_min_velocity_3s"
                    if elite_base_ready
                    else "ict_armed_base_launch_min_velocity_3s"
                    if armed_launch
                    else "first_lift_trade_min_velocity_3s"
                ),
                1.5 if elite_base_ready else (2.0 if armed_launch else 1.5),
            )
            or (1.5 if elite_base_ready else (2.0 if armed_launch else 1.5))
        )
        min_v9 = float(
            getattr(
                settings,
                (
                    "ict_elite_base_ready_min_velocity_9s"
                    if elite_base_ready
                    else "ict_armed_base_launch_min_velocity_9s"
                    if armed_launch
                    else "first_lift_trade_min_velocity_9s"
                ),
                1.5 if elite_base_ready else (1.5 if armed_launch else 1.0),
            )
            or (1.5 if elite_base_ready else (1.5 if armed_launch else 1.0))
        )
    if helper_confirmed:
        min_v3 = min(
            min_v3,
            float(getattr(settings, "first_lift_helper_confirm_min_velocity_3s", 1.2) or 1.2),
        )
        min_v9 = min(
            min_v9,
            float(getattr(settings, "first_lift_helper_confirm_min_velocity_9s", 0.6) or 0.6),
        )
    if grade_a_lane and volume_awake:
        min_v3 = 0.0
        min_v9 = 0.0
    if top_ftv_v_lane and volume_awake:
        min_v3 = 0.0
        min_v9 = 0.0
    if not sustained_lift and v3 < min_v3:
        return False, f"first_lift_velocity3s<{min_v3:g}"
    if not sustained_lift and v9 < min_v9:
        return False, f"first_lift_velocity9s<{min_v9:g}"

    min_volume = float(
        getattr(settings, "first_lift_trade_min_volume_surge", 2.0) or 2.0
    )
    absolute_volume = float(
        getattr(event, "volume", 0)
        or row.get("volume")
        or row.get("absoluteVolume")
        or 0
    )
    persisted_orderflow_allowed = not any(
        name in row and row.get(name) is False
        for name in (
            "orderflowConfirmed",
            "optionCvdBuying",
            "ictVolumeAwakening",
            "volumeAwaken",
        )
    )
    if persisted_orderflow_allowed:
        absolute_volume = max(
            absolute_volume,
            float(persisted.get("volume") or 0),
        )
    if strict_armed_path:
        min_absolute = float(
            getattr(settings, "ict_armed_base_launch_min_absolute_volume", 25000.0)
            or 25000.0
        )
        orderflow_proof = bool(
            absolute_volume >= min_absolute
            or row.get("optionCvdBuying")
            or row.get("orderflowConfirmed")
            or (
                persisted_orderflow_allowed
                and persisted.get("orderflowConfirmed")
            )
            or volume_awake
            or (
                persisted_orderflow_allowed
                and bool(persisted.get("volumeAwakening"))
            )
        )
        if not orderflow_proof:
            return False, f"armed_base_orderflow_below_{min_absolute:g}"
    elif not volume_awake and volume_surge < min_volume:
        return False, f"first_lift_volume_surge<{min_volume:g}"

    side = str(
        getattr(getattr(event, "side", None), "value", getattr(event, "side", ""))
        or row.get("side")
        or ""
    ).upper()
    if side not in ("CALL", "PUT"):
        return False, "first_lift_side_invalid"

    if v_rip_lane and not strict_armed_path:
        if not volume_awake and volume_surge < min_volume:
            return False, f"first_lift_volume_surge<{min_volume:g}"
        from app.engines.moneyness import classify_moneyness
        from app.models.schemas import Side

        strike = float(
            getattr(event, "strike", 0)
            or row.get("strike")
            or 0
        )
        spot = float(getattr(snap, "spot", 0) or 0)
        atm = float(getattr(snap, "atmStrike", 0) or 0)
        if strike <= 0 or spot <= 0:
            return False, "v_rip_moneyness_unavailable"
        money = classify_moneyness(
            Side(side),
            strike,
            spot,
            symbol=str(getattr(snap, "symbol", "") or ""),
            atm=atm if atm > 0 else None,
        )
        if money not in ("ATM", "ITM"):
            return False, f"v_rip_requires_atm_itm_{money.lower()}"
        return True, "v_rip_session_low_ready"

    if strict_armed_path:
        sample_count = int(
            getattr(ict, "armed_base_samples", 0)
            or row.get("ictArmedBaseSamples")
            or 0
        )
        sample_count = max(
            sample_count,
            int(float(persisted.get("sampleCount") or 0)),
        )
        span = float(
            getattr(ict, "armed_base_span_seconds", 0)
            or row.get("ictArmedBaseSpanSeconds")
            or 0
        )
        span = max(span, float(persisted.get("spanSeconds") or 0))
        min_samples = int(
            getattr(settings, "ict_armed_base_min_samples", 6) or 6
        )
        min_span = float(
            getattr(settings, "ict_armed_base_min_span_seconds", 15.0) or 15.0
        )
        if sample_count < min_samples or span < min_span:
            return False, "armed_base_stability_not_confirmed"
        min_tqs = float(
            getattr(settings, "ict_armed_base_launch_min_tqs", 50.0) or 50.0
        )
        if v_rip_lane:
            min_tqs = min(
                min_tqs,
                float(
                    getattr(settings, "ict_v_rip_armed_min_tqs", 45.0) or 45.0
                ),
            )
        aligned_tqs = max(
            float(getattr(snap, "tradeQualityScore", 0) or 0),
            float(persisted.get("tradeQualityScore") or 0),
        )
        if aligned_tqs < min_tqs:
            return False, f"armed_base_tqs<{min_tqs:g}"
        from app.engines.moneyness import classify_moneyness
        from app.models.schemas import Side

        strike = float(
            getattr(event, "strike", 0)
            or row.get("strike")
            or 0
        )
        spot = float(getattr(snap, "spot", 0) or 0)
        atm = float(getattr(snap, "atmStrike", 0) or 0)
        if strike <= 0 or spot <= 0:
            return False, "armed_base_moneyness_unavailable"
        money = classify_moneyness(
            Side(side),
            strike,
            spot,
            symbol=str(getattr(snap, "symbol", "") or ""),
            atm=atm if atm > 0 else None,
        )
        if money not in ("ATM", "ITM"):
            from app.engines.early_radar_pad_capture import (
                alert_has_building_coil_pad,
                building_coil_pad_lane_active,
                building_coil_pad_moneyness_ok,
            )

            coil_context = (
                alert_has_building_coil_pad(row)
                or building_coil_pad_lane_active(row, settings)
            )
            if not (
                coil_context
                and building_coil_pad_moneyness_ok(row, snap, settings)
            ):
                return False, f"armed_base_requires_atm_itm_{money.lower()}"
        armed_min_tqs = float(
            getattr(settings, "ict_armed_base_launch_min_tqs", 50.0) or 50.0
        )
        use_v_rip_reason = (
            v_rip_lane
            and armed_launch
            and not elite_base_ready
            and aligned_tqs < armed_min_tqs
        )
        return True, (
            "elite_base_ready_s_preauthorized"
            if elite_base_ready
            else (
                "v_rip_session_low_ready"
                if use_v_rip_reason
                else "armed_base_option_led_ready"
            )
        )

    # A confirmed ATM/ITM option can lead the slower 5m spot chart. This path is
    # deliberately stronger than normal first-lift readiness: it requires an A/B+
    # base, faster sustained v3/v9, and both absolute-volume awakening and surge.
    # It only replaces the lagging index-turn proof; all selector fade/chase,
    # premium, moneyness, session, preorder, and risk guards still run.
    strike = float(
        getattr(event, "strike", 0)
        or row.get("strike")
        or 0
    )
    spot = float(getattr(snap, "spot", 0) or 0)
    atm = float(getattr(snap, "atmStrike", 0) or 0)
    option_led_quality = float(
        getattr(settings, "first_lift_option_led_min_quality", 65.0) or 65.0
    )
    option_led_v3 = float(
        getattr(settings, "first_lift_option_led_min_velocity_3s", 1.5) or 1.5
    )
    option_led_v9 = float(
        getattr(settings, "first_lift_option_led_min_velocity_9s", 1.5) or 1.5
    )
    if (
        bool(getattr(settings, "first_lift_option_led_enabled", True))
        and strike > 0
        and spot > 0
        and quality >= option_led_quality
        and v3 >= max(min_v3, option_led_v3)
        and v9 >= max(min_v9, option_led_v9)
        and volume_awake
        and volume_surge >= min_volume
    ):
        from app.engines.moneyness import classify_moneyness
        from app.models.schemas import Side

        money = classify_moneyness(
            Side(side),
            strike,
            spot,
            symbol=str(getattr(snap, "symbol", "") or ""),
            atm=atm if atm > 0 else None,
        )
        if money in ("ATM", "ITM"):
            return True, (
                "armed_base_option_led_ready"
                if armed_launch
                else "first_lift_option_led_ready"
            )

    chart = snap.spotChart
    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0)
    mom10 = float(getattr(chart, "momentum10Pct", 0) or 0)
    mom15 = float(getattr(chart, "momentum15Pct", 0) or 0)
    shift = float(
        getattr(settings, "first_lift_trade_min_momentum_shift_pct", 0.03)
        or 0.03
    )
    if side == "CALL":
        if mom5 >= mom10 and mom5 >= mom15 + shift:
            return True, "first_lift_entry_ready"
    elif mom5 <= mom10 and mom5 <= mom15 - shift:
        return True, "first_lift_entry_ready"
    if grade_a_lane and bool(
        row.get("indexMomAlign") or row.get("indexHelpersConfirm")
    ):
        return True, "first_lift_grade_a_index_aligned"
    if top_ftv_v_lane and bool(
        row.get("indexMomAlign")
        or row.get("indexHelpersConfirm")
        or row.get("ictVRipReady")
        or row.get("vRipReady")
    ):
        return True, "first_lift_top_ftv_v_index_aligned"
    return False, "first_lift_index_turn_not_confirmed"


def premium_poll_history(symbol: str, strike: float, side: Side | str) -> list[tuple[datetime, float, float]]:
    """Read rolling premium poll history for ICT gap detection."""
    from app.engines.explosion_detector import (
        PREMIUM_POLL_WINDOW_SECONDS,
        _history,
        _strike_key,
    )

    side_val = side.value if isinstance(side, Side) else str(side).upper()
    key = _strike_key(strike, Side(side_val))
    hist = _history.get(symbol.upper(), {}).get(key)
    if not hist:
        return []
    rows = list(hist)
    cutoff = rows[-1][0] - timedelta(seconds=PREMIUM_POLL_WINDOW_SECONDS)
    return [row for row in rows if row[0] >= cutoff]


def _detect_premium_fvg(
    history: list[tuple[datetime, float, float]], settings
) -> tuple[bool, float]:
    """
    Option-premium FVG / imbalance — premium gaps UP between polls.

    Works for both CALL and PUT explosions: the option premium itself is what
    rips vertically. (Index-side bearish/bullish FVGs live in SMC analysis.)
    Uses 3-bar gap: newest premium above prior by min gap %.
    """
    if len(history) < 3:
        return False, 0.0
    premiums = [h[1] for h in history[-3:]]
    if premiums[0] <= 0:
        return False, 0.0
    gap_pct = ((premiums[-1] - premiums[0]) / premiums[0]) * 100
    min_gap = settings.ict_fvg_min_gap_pct
    # Classic FVG: middle bar displaced — newest above oldest by min gap.
    if premiums[-1] > premiums[-2] > premiums[0] and gap_pct >= min_gap:
        return True, gap_pct
    if len(history) >= 2:
        p0, p1 = history[-2][1], history[-1][1]
        if p0 > 0:
            jump = ((p1 - p0) / p0) * 100
            if jump >= min_gap * 1.5:
                return True, jump
    return False, gap_pct


def flat_vertical_quality(
    *,
    flat: bool,
    flat_dev: float,
    base_len: int,
    base_rel_move: float,
    local_swing_base: bool,
    displacement: bool,
    velocity_3s: float,
    fvg: bool,
    vol_awaken: bool,
    volume_surge: float,
    early_min: float,
    settings: Any,
) -> tuple[float, str]:
    """Score the flat->vertical setup 0-100 + a letter grade.

    A textbook flat->vertical is a TIGHT, LONG coil that releases with heat and volume in
    the near-base launch window. We score each of those explicitly instead of a boolean:
      - base tightness (tighter consolidation = more stored energy)
      - base duration (longer coil = bigger release)
      - launch window (fresh 15-40% off the base, not a late chase)
      - break heat (displacement + velocity + FVG + volume awakening)
      - volume expansion on the break (accumulation -> markup)
    """
    if not (flat or local_swing_base):
        return 0.0, ""
    max_range = float(getattr(settings, "ict_flat_base_max_range_pct", 8.0) or 8.0) or 8.0
    q = 0.0
    # 1) Base tightness (0-25). Ultra-tight flat coil scores highest; a V-base is decent.
    if flat and flat_dev >= 0:
        q += 25.0 * max(0.0, min(1.0, 1.0 - flat_dev / max_range))
    elif local_swing_base:
        q += 15.0
    # 2) Base duration (0-15): ~10+ base samples = a real coil.
    q += min(15.0, max(0, base_len) * 1.5)
    # 3) Launch window (0-25): reward a fresh lift in the near-base band, decay a late chase.
    lo = max(1.0, early_min * 0.5)
    hi = float(getattr(settings, "elite_local_base_max_move_pct", 40.0) or 40.0)
    if base_rel_move <= 0:
        pass
    elif base_rel_move < lo:
        q += 25.0 * 0.6 * (base_rel_move / lo)
    elif base_rel_move <= hi:
        q += 25.0
    else:
        q += max(0.0, 25.0 * (1.0 - (base_rel_move - hi) / max(hi, 1.0)))
    # 4) Break heat (0-25).
    heat = 0.0
    if displacement:
        heat += 8.0
    heat += min(8.0, max(0.0, velocity_3s) * 2.0)
    if fvg:
        heat += 4.0
    if vol_awaken:
        heat += 5.0
    q += min(25.0, heat)
    # 5) Volume expansion on the break (0-10): 3x+ surge = full.
    q += min(10.0, max(0.0, volume_surge - 1.0) * 4.0)

    q = max(0.0, min(100.0, q))
    if q >= 85:
        grade = "A+"
    elif q >= 70:
        grade = "A"
    elif q >= 55:
        grade = "B"
    else:
        grade = "C"
    return round(q, 1), grade


def _detect_flat_base(history: list[tuple[datetime, float, float]], settings) -> tuple[bool, float, float]:
    """Flat consolidation — low variance in premium before breakout.

    Excludes the last 3–4 polls (breakout candles) so the rip itself does not
    destroy the flat-base signal (e.g. 26–28 base then 32/38/45).

    Returns (is_flat, max_dev_pct, base_level). ``base_level`` is the **lowest**
    premium in the flat window (true local launch pad), not the average — so
    first-lift % is measured from the trough and appears at ~15% off that low,
    not after a chase measured from a higher mid-base.
    """
    if len(history) < 6:
        return False, 0.0, 0.0
    # Drop breakout tail; keep at least 4 base samples.
    trim = 4 if len(history) >= 10 else 3
    base = [float(h[1]) for h in list(history)[:-trim] if float(h[1] or 0) > 0]
    if len(base) < 4:
        return False, 0.0, 0.0
    avg = sum(base) / len(base)
    if avg <= 0:
        return False, 0.0, 0.0
    max_dev = max(abs(p - avg) / avg * 100 for p in base)
    use_lowest = bool(getattr(settings, "ict_flat_base_use_lowest", True))
    # Also accept a short rolling window of 5–6 bars with low range.
    if max_dev > settings.ict_flat_base_max_range_pct and len(base) >= 6:
        window = base[-6:]
        wavg = sum(window) / len(window)
        if wavg > 0:
            wdev = max(abs(p - wavg) / wavg * 100 for p in window)
            if wdev <= settings.ict_flat_base_max_range_pct:
                level = min(window) if use_lowest else wavg
                return True, wdev, float(level)
    if max_dev <= settings.ict_flat_base_max_range_pct:
        level = min(base) if use_lowest else avg
        return True, max_dev, float(level)
    return False, max_dev, 0.0


def _detect_local_swing_base(
    history: list[tuple[datetime, float, float]],
    premium: float,
    settings,
    *,
    symbol: str = "",
    strike: float = 0.0,
    side: Side | str | None = None,
) -> tuple[bool, float, float]:
    """Local swing low after a dump — Jul23 SENSEX 76400 PE 14:35 (110→42→45).

    Flat-base detection fails on violent V-bottoms. When recent polls show a
    meaningful dump into a low, measure the new leg from that local low instead
    of the day open / earlier peak.

    Also merges the medium-horizon local-base history (~30 min) — the short
    premium_poll_history (~2 min) alone misses completed V-bottoms (Aug12
    SENSEX 77800 PE).

    Returns (found, local_low, base_relative_move_pct).
    """
    if premium <= 0:
        return False, 0.0, 0.0
    lookback = int(getattr(settings, "ict_local_base_lookback_polls", 16) or 16)
    lookback = max(4, lookback)
    window = list(history)[-lookback:] if history else []
    samples = [
        (h[0], float(h[1]))
        for h in window
        if float(h[1] or 0) > 0
    ]

    # Merge ~30m local-base hist so ICT still sees the trough after the rip.
    try:
        from app.engines.explosion_detector import (
            LOCAL_BASE_WINDOW_SECONDS,
            _local_base_hist,
            _open_key,
            _is_meaningful_premium,
        )

        if symbol and side is not None and strike > 0:
            full_key = _open_key(symbol, strike, side)
            dq = _local_base_hist.get(full_key)
            if dq:
                now = dq[-1][0]
                lo_cut = now - timedelta(seconds=int(LOCAL_BASE_WINDOW_SECONDS))
                for ts, p in dq:
                    if ts >= lo_cut and _is_meaningful_premium(p):
                        samples.append((ts, float(p)))
    except Exception:
        pass

    try:
        samples.sort(key=lambda item: item[0].timestamp())
    except (AttributeError, TypeError, ValueError):
        return False, 0.0, 0.0
    premiums = [premium_value for _, premium_value in samples]
    if len(premiums) < 4:
        return False, 0.0, 0.0
    local_low = min(premiums)
    local_high = max(premiums)
    if local_low <= 0:
        return False, 0.0, 0.0
    dump_pct = (local_high - local_low) / local_low * 100.0
    min_dump = float(getattr(settings, "ict_local_base_min_dump_pct", 25.0) or 25.0)
    if dump_pct < min_dump:
        return False, 0.0, 0.0
    # Low should be recent (in the back half of the window) — not a stale morning print.
    # With merged long history, accept when premium is still in an early expansion
    # off that low (≤65% pad) even if the trough is early in the series.
    low_idx = min(i for i, p in enumerate(premiums) if p <= local_low * 1.001)
    base_rel = (premium - local_low) / local_low * 100.0
    if base_rel < 0:
        base_rel = 0.0
    early_max = float(getattr(settings, "ict_structured_early_max_move_pct", 65.0) or 65.0)
    if low_idx < max(0, len(premiums) // 3):
        near_low = premium <= local_low * 1.35
        in_early_pad = 0 < base_rel <= early_max
        if not near_low and not in_early_pad:
            return False, 0.0, 0.0
    return True, local_low, base_rel


def _detect_recent_window_base(
    *,
    symbol: str,
    strike: float,
    side: Side | str,
    premium: float,
    settings: Any,
) -> tuple[bool, float, float]:
    """Confirm a durable base from the medium-horizon premium tape.

    The fast ICT history is intentionally short for velocity, but a 5-minute
    chart base often forms over 10–30 minutes. Require repeated support prints
    around the low so one bad tick cannot become a first-lift launch pad.
    """
    if not symbol or side is None or strike <= 0 or premium <= 0:
        return False, 0.0, 0.0
    try:
        from app.engines.explosion_detector import (
            LOCAL_BASE_EXCLUDE_RECENT_SECONDS,
            LOCAL_BASE_WINDOW_SECONDS,
            _is_meaningful_premium,
            _local_base_hist,
            _open_key,
        )

        side_v = side if isinstance(side, Side) else Side(str(side).upper())
        rows = list(_local_base_hist.get(_open_key(symbol, strike, side_v)) or [])
    except Exception:
        return False, 0.0, 0.0
    if not rows:
        return False, 0.0, 0.0

    now = rows[-1][0]
    window_seconds = int(
        getattr(
            settings,
            "ict_recent_base_window_seconds",
            LOCAL_BASE_WINDOW_SECONDS,
        )
        or LOCAL_BASE_WINDOW_SECONDS
    )
    exclude_seconds = int(
        getattr(
            settings,
            "ict_recent_base_exclude_seconds",
            LOCAL_BASE_EXCLUDE_RECENT_SECONDS,
        )
        or LOCAL_BASE_EXCLUDE_RECENT_SECONDS
    )
    lo_cut = now - timedelta(seconds=max(60, window_seconds))
    hi_cut = now - timedelta(seconds=max(5, exclude_seconds))
    samples = [
        (ts, float(value))
        for ts, value in rows
        if lo_cut <= ts <= hi_cut and _is_meaningful_premium(value)
    ]
    min_samples = max(
        3,
        int(getattr(settings, "ict_recent_base_min_samples", 6) or 6),
    )
    if len(samples) < min_samples:
        return False, 0.0, 0.0

    base = min(value for _, value in samples)
    support_band_pct = max(
        1.0,
        float(getattr(settings, "ict_recent_base_support_band_pct", 8.0) or 8.0),
    )
    support = [
        (ts, value)
        for ts, value in samples
        if value <= base * (1.0 + support_band_pct / 100.0)
    ]
    min_support = max(
        2,
        int(getattr(settings, "ict_recent_base_min_support_samples", 3) or 3),
    )
    if len(support) < min_support:
        return False, 0.0, 0.0
    support_span = (support[-1][0] - support[0][0]).total_seconds()
    min_span = max(
        0.0,
        float(getattr(settings, "ict_recent_base_min_support_span_seconds", 30.0) or 30.0),
    )
    if support_span < min_span:
        return False, 0.0, 0.0
    max_age = max(
        60.0,
        float(getattr(settings, "ict_recent_base_max_age_seconds", 900.0) or 900.0),
    )
    if (hi_cut - support[-1][0]).total_seconds() > max_age:
        return False, 0.0, 0.0

    base_rel = max(0.0, (premium - base) / base * 100.0)
    early_max = float(
        getattr(settings, "ict_structured_early_max_move_pct", 65.0) or 65.0
    )
    if base_rel <= 0 or base_rel > early_max:
        return False, 0.0, 0.0
    return True, base, base_rel


def _sustained_armed_base_lift(
    history: list[tuple],
    *,
    base_premium: float,
    premium: float,
    base_move_pct: float,
    settings: Any,
) -> bool:
    """Confirm a causal lift when sparse-but-fresh samples cannot produce v3/v9."""
    if not history or base_premium <= 0 or premium <= 0:
        return False
    min_move = float(
        getattr(settings, "ict_armed_sustained_lift_min_move_pct", 8.0) or 8.0
    )
    max_move = float(
        getattr(settings, "ict_armed_sustained_lift_max_move_pct", 25.0) or 25.0
    )
    if not min_move <= base_move_pct <= max_move:
        return False
    now = history[-1][0]
    lookback = float(
        getattr(settings, "ict_armed_sustained_lift_lookback_seconds", 120.0) or 120.0
    )
    rows = [
        (ts, float(value))
        for ts, value, *_ in history
        if 0 <= (now - ts).total_seconds() <= lookback and float(value or 0) > 0
    ]
    min_samples = int(
        getattr(settings, "ict_armed_sustained_lift_min_samples", 3) or 3
    )
    if len(rows) < min_samples:
        return False
    span = (rows[-1][0] - rows[0][0]).total_seconds()
    min_span = float(
        getattr(settings, "ict_armed_sustained_lift_min_span_seconds", 15.0) or 15.0
    )
    if span < min_span:
        return False
    prior_low = min(value for _, value in rows[:-1])
    progress = (premium - prior_low) / prior_low * 100.0 if prior_low > 0 else 0.0
    min_progress = float(
        getattr(settings, "ict_armed_sustained_lift_min_progress_pct", 3.0) or 3.0
    )
    max_fade = float(
        getattr(settings, "ict_armed_sustained_lift_max_fade_pct", 2.5) or 2.5
    )
    recent_high = max(value for _, value in rows)
    fade = (recent_high - premium) / recent_high * 100.0 if recent_high > 0 else 100.0
    return progress >= min_progress and fade <= max_fade


def analyze_ict_breakout(
    *,
    symbol: str,
    side: Side | str,
    strike: float,
    premium: float,
    session_move_pct: float = 0.0,
    peak_move_pct: float = 0.0,
    velocity_3s: float = 0.0,
    velocity_9s: float = 0.0,
    volume_surge: float = 1.0,
    volume: float = 0.0,
    tier: str = "",
    reason: str = "",
    snap: Optional[SymbolSnapshot] = None,
) -> ICTBreakoutSignal:
    """Score flat-then-vertical / FVG / displacement patterns on option premium."""
    settings = get_settings()
    if not settings.ict_breakout_monitor_enabled:
        return ICTBreakoutSignal(False, "disabled", 0.0, [])

    move = max(session_move_pct, peak_move_pct)
    history = premium_poll_history(symbol, strike, side)
    reasons: list[str] = []
    score = 0.0

    fvg, gap_pct = _detect_premium_fvg(history, settings)
    flat, flat_dev, flat_base = _detect_flat_base(history, settings)
    swing_found, swing_low, swing_rel = _detect_local_swing_base(
        history, premium, settings, symbol=symbol, strike=strike, side=side,
    )
    from app.engines.explosion_detector import armed_base_anchor

    armed_meta = armed_base_anchor(
        symbol, strike, side, premium, settings=settings,
    )
    base_armed = bool(armed_meta.get("armed"))
    armed_samples = int(armed_meta.get("sampleCount") or 0)
    armed_span = float(armed_meta.get("spanSeconds") or 0)
    armed_range = float(armed_meta.get("rangePct") or 0)
    armed_at = str(armed_meta.get("armedAt") or "")
    armed_expires_at = str(armed_meta.get("expiresAt") or "")
    early_min = float(getattr(settings, "ict_early_vertical_min_session_move_pct", 28.0) or 28.0)
    # First-lift floor — appear at the structured local-base pad (~15%), not after chase.
    first_lift_lo = float(
        getattr(settings, "ict_structured_early_min_move_pct", 15.0) or 15.0
    )
    first_lift_hi = float(
        getattr(settings, "elite_local_base_max_move_pct", 40.0) or 40.0
    )
    # A newly established flat consolidation is the launch pad even when an older,
    # deeper session/V low exists. Otherwise the stale low turns a genuine 15% first
    # lift off the coil into a 40%+ "chase". V-bottoms remain the fallback when there
    # is no trustworthy flat.
    local_swing_base = False
    base_level = 0.0
    base_rel_move = 0.0
    trusted_flat = False
    if flat and flat_base > 0 and premium > 0:
        cand_rel = (premium - flat_base) / flat_base * 100.0
        # Flat-at-the-highs after a rip is NOT a launch pad (Jul30 77700: baseRel=0
        # while session printed +1626% / fake mega). Require real lift off the base.
        if cand_rel >= min(early_min, first_lift_lo) * 0.5:
            trusted_flat = True
            base_level = flat_base
            base_rel_move = cand_rel
    if not trusted_flat and swing_found and swing_low > 0:
        local_swing_base = True
        base_level = swing_low
        base_rel_move = swing_rel
    if not trusted_flat and not local_swing_base:
        recent_found, recent_base, recent_rel = _detect_recent_window_base(
            symbol=symbol,
            strike=strike,
            side=side,
            premium=premium,
            settings=settings,
        )
        if recent_found:
            local_swing_base = True
            base_level = recent_base
            base_rel_move = recent_rel
            reasons.append(f"recent_window_base_{recent_base:.1f}")

    # The causal armed anchor is the shared REST/WS denominator. It supersedes
    # observation-local flat/swing choices and is sticky upward for its horizon.
    mid_rip_coil = bool(armed_meta.get("midRipCoil"))
    if mid_rip_coil:
        reasons.append("mid_rip_coil_rejected")
    if base_armed:
        base_level = float(armed_meta.get("basePremium") or 0)
        base_rel_move = float(armed_meta.get("baseRelativeMovePct") or 0)
        local_swing_base = True
        reasons.append(f"armed_base_{base_level:.1f}")

    # Session-low fallback is only for V-shaped legs without a trusted flat coil.
    # Never replace a recent flat trough with an older session low.
    sess_low = 0.0
    sess_peak = 0.0
    if premium > 0 and not trusted_flat:
        try:
            from app.engines.explosion_detector import (
                get_session_low_premium,
                session_move_min_baseline,
                _session_peak,
                _open_key,
            )

            sess_low = get_session_low_premium(symbol, strike, side)
            try:
                sess_peak = float(
                    _session_peak.get(_open_key(symbol, strike, side)) or 0
                )
            except Exception:
                sess_peak = 0.0
            floor = session_move_min_baseline(settings)
            if sess_low >= floor and premium > sess_low:
                off_low = (premium - sess_low) / sess_low * 100.0
                if off_low >= min(early_min, first_lift_lo) * 0.5:
                    if base_level <= 0:
                        local_swing_base = True
                        base_level = sess_low
                        base_rel_move = off_low
                        reasons.append(f"session_low_base_{sess_low:.1f}")
        except Exception:
            pass

    # Mid-rip pause coil (armed or recent-window) above a real trough must not
    # mint a fake "2–5% early" pad. Remeasure from the session trough so chase
    # gates see the true expansion (Aug19 SENSEX 76900 PE).
    if (
        premium > 0
        and sess_low > 0
        and base_level > 0
        and not trusted_flat
    ):
        try:
            from app.engines.explosion_detector import mid_rip_armed_coil

            if mid_rip_armed_coil(
                session_low=sess_low,
                armed_base=base_level,
                premium=premium,
                session_peak=sess_peak,
                settings=settings,
            ):
                off_low = (premium - sess_low) / sess_low * 100.0
                reasons.append(
                    f"mid_rip_coil_rejected_{base_level:.1f}_use_session_low_{sess_low:.1f}"
                )
                base_level = sess_low
                base_rel_move = off_low
                local_swing_base = True
                mid_rip_coil = True
                # Contaminated armed state cannot authorize elite/armed early entry.
                base_armed = False
        except Exception:
            pass

    surge_awaken = volume_surge >= float(
        getattr(settings, "ict_volume_surge_awaken_min", 3.0) or 3.0
    )
    vol_awaken = (
        volume >= settings.explosion_volume_awaken_min
        or "volAwaken" in (reason or "")
        or surge_awaken
    )
    displacement = velocity_3s >= settings.ict_displacement_min_velocity_3s
    armed_launch_lo = float(
        getattr(settings, "ict_armed_base_launch_min_move_pct", 5.0) or 5.0
    )
    armed_launch_hi = float(
        getattr(settings, "ict_armed_base_launch_max_move_pct", 12.0) or 12.0
    )
    armed_launch_v3 = float(
        getattr(settings, "ict_armed_base_launch_min_velocity_3s", 1.5) or 1.5
    )
    armed_launch_v9 = float(
        getattr(settings, "ict_armed_base_launch_min_velocity_9s", 1.5) or 1.5
    )
    fast_armed_launch = bool(
        base_armed
        and not mid_rip_coil
        and armed_launch_lo <= base_rel_move <= armed_launch_hi
        and velocity_3s >= armed_launch_v3
        and velocity_9s >= armed_launch_v9
        and vol_awaken
    )
    sustained_armed_lift = bool(
        base_armed
        and not mid_rip_coil
        and _sustained_armed_base_lift(
            history,
            base_premium=base_level,
            premium=premium,
            base_move_pct=base_rel_move,
            settings=settings,
        )
    )
    armed_launch = fast_armed_launch or sustained_armed_lift
    elite_ready_lo = float(
        getattr(settings, "ict_elite_base_ready_min_move_pct", 2.0) or 2.0
    )
    elite_ready_hi = float(
        getattr(settings, "ict_elite_base_ready_max_move_pct", 5.0) or 5.0
    )
    elite_ready_v3 = float(
        getattr(settings, "ict_elite_base_ready_min_velocity_3s", 1.5) or 1.5
    )
    elite_ready_v9 = float(
        getattr(settings, "ict_elite_base_ready_min_velocity_9s", 1.5) or 1.5
    )
    elite_base_ready = bool(
        getattr(settings, "ict_elite_base_ready_enabled", True)
        and base_armed
        and not mid_rip_coil
        and tier in ("BUILDING", "EXPLODING", "ELITE")
        and elite_ready_lo <= base_rel_move < elite_ready_hi
        and velocity_3s >= elite_ready_v3
        and velocity_9s >= elite_ready_v9
        and vol_awaken
    )
    # Continuous V-rip off the session/day trough — sparse polls often skip the
    # narrow 2–5% elite window (125→140 in one sample). Keep auth open 2–25%.
    session_low_armed = bool(armed_meta.get("sessionLowArmed"))
    near_low_pct = float(
        getattr(settings, "ict_v_rip_base_near_session_low_pct", 2.0) or 2.0
    )
    base_is_v_trough = bool(
        sess_low > 0
        and base_level > 0
        and abs(base_level - sess_low) / sess_low * 100.0 <= near_low_pct
    )
    v_rip_lo = float(getattr(settings, "ict_v_rip_min_move_pct", 2.0) or 2.0)
    v_rip_hi = float(getattr(settings, "ict_v_rip_max_move_pct", 25.0) or 25.0)
    v_rip_v3 = float(getattr(settings, "ict_v_rip_min_velocity_3s", 1.2) or 1.2)
    v_rip_v9 = float(getattr(settings, "ict_v_rip_min_velocity_9s", 0.8) or 0.8)
    v_rip_ready = bool(
        getattr(settings, "ict_v_rip_ready_enabled", True)
        and not mid_rip_coil
        and (base_armed or local_swing_base)
        and (session_low_armed or base_is_v_trough)
        and tier in ("BUILDING", "EXPLODING", "ELITE")
        and v_rip_lo <= base_rel_move <= v_rip_hi + 1e-6
        and (
            vol_awaken
            or displacement
            or velocity_3s >= v_rip_v3
        )
        and (
            velocity_3s >= v_rip_v3
            or vol_awaken
        )
        and (
            velocity_9s >= v_rip_v9
            or vol_awaken
            or sustained_armed_lift
        )
    )
    # BUILDING mid-rip / local-base early-lift flag for radar.
    building_rip_v3 = float(
        getattr(settings, "building_rip_min_velocity_3s", 1.5) or 1.5
    )
    building_rip_v9 = float(
        getattr(settings, "building_rip_min_velocity_9s", 0.8) or 0.8
    )
    building_rip_lo = float(
        getattr(settings, "building_rip_min_move_pct", 2.0) or 2.0
    )
    building_rip_hi = float(
        getattr(settings, "building_rip_max_move_pct", 55.0) or 55.0
    )
    local_lift_lo = float(
        getattr(settings, "building_rip_local_base_min_move_pct", 2.0) or 2.0
    )
    local_lift_hi = float(
        getattr(settings, "building_rip_local_base_max_move_pct", 15.0) or 15.0
    )
    local_lift_v3 = float(
        getattr(settings, "building_rip_local_base_min_velocity_3s", 1.2) or 1.2
    )
    structure_for_rip = max(base_rel_move, float(move or 0))
    # After promote BUILDING→EXPLODING, keep the rip sleeve if reason stamped it.
    building_tier_ok = tier == "BUILDING" or (
        tier == "EXPLODING" and "buildingRip" in str(reason or "")
    )
    local_base_lift_ready = bool(
        getattr(settings, "building_rip_bullish_enabled", True)
        and getattr(settings, "building_rip_local_base_lift_enabled", True)
        and not mid_rip_coil
        and building_tier_ok
        and (local_swing_base or base_armed)
        and local_lift_lo <= base_rel_move <= local_lift_hi + 1e-6
        and velocity_3s >= local_lift_v3
        and (vol_awaken or volume_surge >= float(
            getattr(settings, "building_rip_min_volume_surge", 1.8) or 1.8
        ))
    )
    mid_rip_ready = bool(
        getattr(settings, "building_rip_bullish_enabled", True)
        and not mid_rip_coil
        and building_tier_ok
        and velocity_3s >= building_rip_v3
        and (velocity_9s >= building_rip_v9 or vol_awaken)
        and (vol_awaken or volume_surge >= float(
            getattr(settings, "building_rip_min_volume_surge", 1.8) or 1.8
        ))
        and building_rip_lo <= structure_for_rip <= building_rip_hi + 1e-6
    )
    building_rip_ready = mid_rip_ready or local_base_lift_ready
    if local_base_lift_ready:
        reasons.append(
            f"building_local_base_lift_{base_rel_move:.1f}%_v3_{velocity_3s:.1f}"
        )
    elif mid_rip_ready:
        reasons.append(
            f"building_rip_bullish_{structure_for_rip:.1f}%_v3_{velocity_3s:.1f}"
        )
    early_v3 = float(getattr(settings, "ict_early_vertical_min_velocity_3s", 2.0) or 2.0)
    # Structure / early-window heat: prefer local-base move when we have one.
    structure_move = base_rel_move if base_rel_move > 0 else move
    vertical = move >= settings.ict_vertical_min_session_move_pct
    # Early breakout: flat OR local V-base + heat + ≥ early_min from that base.
    early_break = (
        (flat or local_swing_base)
        and structure_move >= early_min
        and (
            displacement
            or vol_awaken
            or fvg
            or velocity_3s >= early_v3
        )
    )
    if armed_launch:
        early_break = True
        reasons.append(
            f"armed_base_launch_{base_level:.1f}_{base_rel_move:.1f}%"
        )
        if sustained_armed_lift:
            reasons.append("armed_base_sustained_lift")
    elif elite_base_ready:
        early_break = True
        reasons.append(
            f"elite_base_ready_{base_level:.1f}_{base_rel_move:.1f}%"
        )
    elif v_rip_ready:
        early_break = True
        reasons.append(
            f"v_rip_session_low_{base_level:.1f}_{base_rel_move:.1f}%"
        )
    elif building_rip_ready:
        early_break = True
    # First lift off the lowest local base — appear in the 15–40% pad with heat,
    # before day-% / chase tiers light up. Soft velocity OK when volume confirms.
    first_lift_v3 = float(
        getattr(settings, "ict_first_lift_min_velocity_3s", 1.2) or 1.2
    )
    first_lift_heat = (
        displacement
        or vol_awaken
        or fvg
        or velocity_3s >= first_lift_v3
        or (velocity_3s >= early_v3 * 0.6 and volume_surge >= 1.6)
    )
    first_lift = bool(
        getattr(settings, "ict_first_lift_appear_enabled", True)
        and (flat or local_swing_base)
        and base_level > 0
        and (base_rel_move + 1e-6) >= first_lift_lo
        and base_rel_move <= (first_lift_hi + 1e-6)
        and first_lift_heat
    )
    if first_lift:
        early_break = True
        reasons.append(
            f"first_lift_local_base_{base_level:.1f}_{base_rel_move:.0f}%"
        )
    flat_then_vertical = (
        (flat and vertical and base_rel_move >= early_min * 0.5)
        or early_break
    )
    # Rate the flat->vertical setup quality (0-100 + grade) from tightness, coil length,
    # launch window, break heat and volume expansion — a graded read, not just a boolean.
    trim = 4 if len(history) >= 10 else 3
    base_len = max(0, len(history) - trim)
    fv_quality, fv_grade = flat_vertical_quality(
        flat=flat,
        flat_dev=flat_dev,
        base_len=base_len,
        base_rel_move=base_rel_move,
        local_swing_base=local_swing_base,
        displacement=displacement,
        velocity_3s=velocity_3s,
        fvg=fvg,
        vol_awaken=vol_awaken,
        volume_surge=volume_surge,
        early_min=early_min,
        settings=settings,
    )
    if not flat_then_vertical:
        fv_quality, fv_grade = 0.0, ""
    elif sustained_armed_lift:
        # Sustained armed lift is early FTV — floor quality so WINNER (≥70) can
        # authorize inside the pad before grade lags to A (still score-gated).
        fv_quality = max(fv_quality, 70.0)
        fv_grade = "B" if fv_grade not in ("A+", "A") else fv_grade
    elif (
        early_break
        and tier in ("EXPLODING", "ELITE")
        and 5.0 <= base_rel_move <= 25.0
        and (vol_awaken or displacement)
    ):
        # Early FTV heat in catch window — quality often prints B mid-60s while
        # the rip is still near base; floor to WINNER bar without lowering score.
        fv_quality = max(fv_quality, 70.0)
        if fv_grade not in ("A+", "A"):
            fv_grade = "B"
    mega_floor = float(getattr(settings, "ict_mega_rip_min_session_move_pct", 200.0) or 200.0)
    try:
        max_credible = float(getattr(settings, "session_move_max_credible_pct", 500.0))
    except (TypeError, ValueError):
        max_credible = 500.0
    if max_credible <= 0:
        max_credible = 500.0
    mega = move >= mega_floor
    # Fake mega from micro-baseline: huge day-% with no real local/off-low structure.
    if mega and move > max_credible and base_rel_move < early_min:
        mega = False
        reasons.append(f"mega_rip_rejected_uncredible_{move:.0f}%")

    if fvg:
        score += settings.ict_fvg_score_bonus
        reasons.append(f"premium_fvg_{gap_pct:.0f}%")
    if local_swing_base:
        reasons.append(f"local_swing_base_{base_level:.1f}")
    if flat and vertical and base_rel_move >= early_min * 0.5:
        score += settings.ict_flat_vertical_score_bonus
        reasons.append(f"flat_then_vertical_{flat_dev:.1f}%base")
    elif early_break:
        score += float(getattr(settings, "ict_early_breakout_score_bonus", 16.0) or 16.0)
        src = "local" if local_swing_base and not flat else "flat"
        reasons.append(f"early_{src}_break_{structure_move:.0f}%")
    elif flat and displacement:
        score += settings.ict_flat_vertical_score_bonus * 0.7
        reasons.append("flat_base_breaking")
    if displacement:
        score += 8.0
        reasons.append(f"displacement_v3_{velocity_3s:.1f}")
    if vol_awaken:
        score += 10.0
        reasons.append("volume_awakening" if not surge_awaken else f"volume_surge_{volume_surge:.1f}x")
    if vertical or early_break:
        score += min(25, move * 0.08)
        reasons.append(f"session_rip_{move:.0f}%")
    if mega:
        score += settings.ict_mega_rip_score_bonus
        reasons.append(f"mega_rip_{move:.0f}%")
    if tier in ("EXPLODING", "ELITE"):
        score += 6.0
        reasons.append(f"tier_{tier.lower()}")
    elif tier == "BUILDING" and (early_break or flat_then_vertical):
        score += 4.0
        reasons.append("tier_building_breakout")

    if snap and snap.spotChart:
        from app.engines.chart_advanced_analysis import analyze_smc_ict

        chart = snap.spotChart
        ohlc = getattr(chart, "ohlc5m", None) or []
        if len(ohlc) >= 5:
            opens = [float(b.get("open", b.get("o", 0))) for b in ohlc[-20:]]
            highs = [float(b.get("high", b.get("h", 0))) for b in ohlc[-20:]]
            lows = [float(b.get("low", b.get("l", 0))) for b in ohlc[-20:]]
            closes = [float(b.get("close", b.get("c", 0))) for b in ohlc[-20:]]
            if all(closes):
                smc = analyze_smc_ict(opens, highs, lows, closes, float(snap.spot or closes[-1]))
                if smc.get("displacement"):
                    score += 6.0
                    reasons.append("index_displacement")
                if smc.get("inKillZone"):
                    score += 4.0
                    reasons.append(str(smc.get("killZone") or "kill_zone"))
                if smc.get("bos"):
                    score += 5.0
                    reasons.append(str(smc["bos"]))

    # Displacement alone must not activate ICT on tiny session moves (Jul20 +1% noise).
    early_floor = float(getattr(settings, "ict_early_vertical_min_session_move_pct", 28.0) or 28.0)
    immature_floor = float(
        getattr(settings, "explosion_immature_min_session_move_pct", 28.0) or 28.0
    )
    displacement_only_ok = displacement and move >= immature_floor and (flat or vol_awaken or fvg)
    active = (
        mega
        or early_break
        or (fvg and (vertical or early_break or move >= early_floor))
        or flat_then_vertical
        or (
            score >= settings.ict_breakout_min_score
            and (flat_then_vertical or fvg or mega or displacement_only_ok or move >= early_floor)
        )
    )
    pattern = "mega_rip" if mega else (
        "flat_then_vertical" if flat_then_vertical else (
            "premium_fvg" if fvg else (
                "displacement" if displacement else "watch"
            )
        )
    )

    return ICTBreakoutSignal(
        active=active,
        pattern=pattern,
        score=score,
        reasons=reasons,
        premium_fvg=fvg,
        flat_then_vertical=flat_then_vertical,
        displacement=displacement,
        volume_awakening=vol_awaken,
        mega_rip=mega,
        session_move_pct=move,
        velocity_3s=velocity_3s,
        volume_surge=volume_surge,
        base_premium=base_level,
        base_relative_move_pct=base_rel_move,
        local_swing_base=local_swing_base,
        flat_vertical_quality=fv_quality,
        flat_vertical_grade=fv_grade,
        first_lift=first_lift,
        base_armed=base_armed,
        elite_base_ready=elite_base_ready,
        v_rip_ready=v_rip_ready,
        building_rip_ready=building_rip_ready,
        armed_base_launch=armed_launch,
        armed_base_sustained_lift=sustained_armed_lift,
        armed_base_samples=armed_samples,
        armed_base_span_seconds=armed_span,
        armed_base_range_pct=armed_range,
        armed_at=armed_at,
        armed_base_expires_at=armed_expires_at,
    )


def merge_alert_ict_stamps(
    ict: ICTBreakoutSignal,
    alert: Optional[Mapping[str, Any]],
) -> ICTBreakoutSignal:
    """Carry radar ICT stamps when live re-analyze drops v_rip / volume flags."""
    if not alert:
        return ict
    moment = str(alert.get("momentType") or alert.get("reason") or "").lower()
    if bool(alert.get("ictVRipReady") or alert.get("vRipReady")) or "v_rip" in moment:
        ict.v_rip_ready = True
    if bool(alert.get("volumeAwaken") or alert.get("ictVolumeAwakening")):
        ict.volume_awakening = True
    for alert_key, ict_attr in (
        ("ictFlatThenVertical", "flat_then_vertical"),
        ("ictLocalSwingBase", "local_swing_base"),
        ("ictBaseArmed", "base_armed"),
        ("ictFirstLift", "first_lift"),
    ):
        if bool(alert.get(alert_key)):
            setattr(ict, ict_attr, True)
    try:
        pad = float(
            alert.get("ictBaseRelativeMovePct")
            or alert.get("localBaseMovePct")
            or 0
        )
    except (TypeError, ValueError):
        pad = 0.0
    if pad > 0 and float(getattr(ict, "base_relative_move_pct", 0) or 0) <= 0:
        ict.base_relative_move_pct = pad
    return ict


def analyze_explosion_event_ict(event: Any, snap: Optional[SymbolSnapshot] = None) -> ICTBreakoutSignal:
    volume = float(getattr(event, "volume", 0) or 0)
    # Event path used to drop absolute volume (always 0) → ICT never saw abs awaken.
    # Fall back to detector history carry-forward when the event field is empty.
    if volume <= 0:
        try:
            from app.engines.explosion_detector import _history, _last_known_volume, _strike_key

            sym = str(getattr(event, "symbol", "") or "")
            side = getattr(event, "side", Side.CALL)
            strike = float(getattr(event, "strike", 0) or 0)
            hist = (_history.get(sym) or {}).get(_strike_key(strike, side))
            if hist:
                volume = _last_known_volume(hist)
        except Exception:
            volume = 0.0
    return analyze_ict_breakout(
        symbol=str(getattr(event, "symbol", "") or ""),
        side=getattr(event, "side", Side.CALL),
        strike=float(getattr(event, "strike", 0) or 0),
        premium=float(getattr(event, "premium", 0) or 0),
        session_move_pct=float(getattr(event, "daily_move_pct", 0) or 0),
        peak_move_pct=float(getattr(event, "peak_move_pct", 0) or 0),
        velocity_3s=float(getattr(event, "velocity_3s", 0) or 0),
        velocity_9s=float(getattr(event, "velocity_9s", 0) or 0),
        volume=volume,
        volume_surge=float(getattr(event, "volume_surge", 0) or 0),
        tier=str(getattr(event, "tier", "") or ""),
        reason=str(getattr(event, "reason", "") or ""),
        snap=snap,
    )


def late_fade_chase_blocked(
    event: Any,
    ict: Optional[ICTBreakoutSignal] = None,
    *,
    snap: Any = None,
) -> tuple[bool, str]:
    """Block chasing rips that already peaked hard with cooling live velocity (PF killer)."""
    settings = get_settings()
    if not getattr(settings, "ict_late_chase_block_enabled", True):
        return False, ""
    # Late-fade still blocks must-take / ELITE — cooling velocity after a hard
    # peak is a real PF killer even when the strike started near the pad.
    peak = float(getattr(event, "peak_move_pct", 0) or 0)
    daily = float(getattr(event, "daily_move_pct", 0) or 0)
    move = max(peak, daily, float(ict.session_move_pct) if ict else 0.0)
    v3 = float(getattr(event, "velocity_3s", 0) or 0)
    min_peak = float(getattr(settings, "ict_late_chase_min_peak_pct", 75.0) or 75.0)
    max_v3 = float(getattr(settings, "ict_late_chase_max_live_velocity_3s", 1.0) or 1.0)
    early_max = float(getattr(settings, "explosion_early_window_max_move_pct", 65.0) or 65.0)
    local_max = float(
        getattr(settings, "explosion_local_base_chase_max_move_pct", 65.0) or 65.0
    )
    # Fresh local-base / off-low leg still inside the pad — day peak % must not
    # late-fade-block (76400 PE reclaim; Aug5 24500 ~9% off pad while day% ~67%).
    if getattr(settings, "explosion_chase_use_local_base", True):
        try:
            from app.engines.explosion_entry_guards import effective_local_base_move_pct

            base_rel = effective_local_base_move_pct(event, ict)
        except Exception:
            base_rel = float(getattr(ict, "base_relative_move_pct", 0) or 0) if ict else 0.0
        if 0 < base_rel <= local_max:
            return False, ""
    # Early flat→vertical still in the capture window may keep a live displacement pass.
    if (
        ict
        and ict.flat_then_vertical
        and move <= early_max
        and (ict.volume_awakening or ict.displacement)
        and v3 >= max_v3
    ):
        return False, ""
    if move >= min_peak and v3 <= max_v3:
        return True, f"ict_late_fade_chase_peak_{move:.0f}%_v3_{v3:.1f}"
    return False, ""


def _expiry_worst_session(
    *,
    day_mode: str = "",
    state: Any = None,
    meta: Optional[dict[str, Any]] = None,
) -> bool:
    """True for EXPIRY WORST / expiry+worst day labels (Aug18 loss cluster)."""
    blobs: list[str] = [str(day_mode or "")]
    if isinstance(meta, dict):
        for key in ("dayMode", "dayType", "mode", "message"):
            blobs.append(str(meta.get(key) or ""))
        day_adaptive = meta.get("dayAdaptive")
        if isinstance(day_adaptive, dict):
            blobs.append(str(day_adaptive.get("dayMode") or ""))
            blobs.append(str(day_adaptive.get("dayType") or ""))
    if state is not None:
        for attr in ("dayMode", "day_mode", "dailyStrategy", "dayAdaptive"):
            raw = getattr(state, attr, None)
            if isinstance(raw, dict):
                blobs.extend(
                    str(raw.get(k) or "")
                    for k in ("dayMode", "dayType", "message", "mode")
                )
                nested = raw.get("dayAdaptive")
                if isinstance(nested, dict):
                    blobs.append(str(nested.get("dayMode") or ""))
                    blobs.append(str(nested.get("dayType") or ""))
            else:
                blobs.append(str(raw or ""))
    joined = " ".join(blobs).upper()
    if "EXPIRY WORST" in joined:
        return True
    # "EXPIRY DAY" + WORST dayType still counts (post-midday label drift).
    if "EXPIRY" in joined and "WORST" in joined:
        return True
    return False


def _defensive_base_rip_top_allowed(
    *,
    tier: str,
    quality: float,
    score: float,
    velocity_3s: float,
    settings: Any,
    base_move_pct: float = 0.0,
    volume_awake: bool = False,
    v_rip_ready: bool = False,
    armed_base_launch: bool = False,
    first_lift: bool = False,
) -> tuple[bool, str]:
    """Always-on top floor for defensive/worst local-base rips (not every EXPLODING)."""
    if not bool(getattr(settings, "ict_defensive_base_rip_require_top_quality", True)):
        return True, "ok"
    tier_u = str(tier or "").upper()
    if tier_u not in {"ELITE", "EXPLODING"}:
        return False, f"defensive_rip_top_tier_{tier_u.lower() or 'unknown'}"
    min_quality = float(
        getattr(settings, "ict_defensive_base_rip_min_quality", 70.0) or 70.0
    )
    min_score = float(
        getattr(settings, "ict_defensive_base_rip_min_score", 80.0) or 80.0
    )
    min_v3 = float(
        getattr(settings, "ict_defensive_base_rip_min_velocity_3s", 2.5) or 2.5
    )
    pad_lo = float(
        getattr(settings, "top_ftv_a_pad_velocity_min_move_pct", 8.0) or 8.0
    )
    pad_hi = float(
        getattr(settings, "top_ftv_a_pad_velocity_max_move_pct", 25.0) or 25.0
    )
    move = float(base_move_pct or 0)
    v_pad_lo = float(getattr(settings, "ict_v_rip_pad_min_move_pct", 2.0) or 2.0)
    v_pad_hi = float(getattr(settings, "ict_v_rip_max_move_pct", 25.0) or 25.0)
    # Aug26 SENSEX PUT 77600/77700: v_rip_session_low at 7–10% lb had explosionScore
    # ~40–42 (passes ict_v_rip_min_score) but defensive_rip_top still demanded ≥75.
    if v_pad_lo <= move <= v_pad_hi and (v_rip_ready or volume_awake):
        min_score = min(
            min_score,
            float(getattr(settings, "ict_v_rip_min_score", 40.0) or 40.0),
        )
        min_quality = min(
            min_quality,
            float(getattr(settings, "ict_v_rip_min_quality", 50.0) or 50.0),
        )
    if float(quality or 0) < min_quality:
        return False, f"defensive_rip_top_quality<{min_quality:g}"
    if float(score or 0) < min_score:
        return False, f"defensive_rip_top_score<{min_score:g}"
    if pad_lo <= move <= pad_hi and (v_rip_ready or volume_awake):
        pad_floor = float(
            getattr(settings, "ict_v_rip_pad_min_move_pct", 2.0) or 2.0
        )
        if volume_awake and move + 1e-6 >= pad_floor:
            min_v3 = min(
                min_v3,
                float(
                    getattr(
                        settings,
                        "ict_v_rip_volume_awake_min_velocity_3s",
                        0.85,
                    )
                    or 0.85
                ),
            )
        elif v_rip_ready:
            min_v3 = min(
                min_v3,
                float(
                    getattr(settings, "ict_v_rip_min_velocity_3s", 1.2) or 1.2
                ),
            )
        # Aug26 NIFTY PUT 24250 armed_base_launch at ~24% lb: volumeAwaken + first
        # lift showed v3≈-0.3 while chart/defensive gates still demanded ≥0.85.
        if (
            armed_base_launch
            and first_lift
            and volume_awake
            and pad_floor <= move <= pad_hi
        ):
            min_v3 = min(
                min_v3,
                float(
                    getattr(
                        settings,
                        "ict_armed_base_launch_cold_velocity_3s",
                        -0.5,
                    )
                    or -0.5
                ),
            )
        # Aug26 SENSEX PUT 77800 first_lift_local_base at ~16% lb with session peak 53%.
        if (
            first_lift
            and not armed_base_launch
            and volume_awake
            and pad_floor <= move <= pad_hi
        ):
            min_v3 = min(
                min_v3,
                float(
                    getattr(
                        settings,
                        "ict_first_lift_local_base_cold_velocity_3s",
                        -1.5,
                    )
                    or -1.5
                ),
            )
        # Aug26 SENSEX PUT 77600 v_rip_session_low at ~9% lb: v3≈0 at lift off trough.
        if (
            v_rip_ready
            and volume_awake
            and not first_lift
            and not armed_base_launch
            and v_pad_lo <= move <= v_pad_hi
        ):
            min_v3 = min(
                min_v3,
                float(
                    getattr(settings, "ict_v_rip_cold_velocity_3s", -1.5) or -1.5
                ),
            )
    if float(velocity_3s or 0) < min_v3:
        return False, f"defensive_rip_top_v3<{min_v3:g}"
    return True, "ok"


def _expiry_worst_defensive_rip_allowed(
    *,
    tier: str,
    quality: float,
    score: float,
    velocity_3s: float,
    settings: Any,
    evidence: Optional[Mapping[str, Any]] = None,
) -> tuple[bool, str]:
    """Raised bar for defensive/armed base rips on EXPIRY WORST days."""
    if evidence is not None:
        from app.engines.pad_lane_capture import pad_lane_expiry_worst_waive

        if pad_lane_expiry_worst_waive(evidence):
            return True, "pad_lane_expiry_worst_waive"
        from app.engines.grade_a_ftv_capture import grade_a_ftv_expiry_worst_waive

        if grade_a_ftv_expiry_worst_waive(evidence):
            return True, "grade_a_ftv_expiry_worst_waive"
        from app.engines.top_ftv_v_expiry_bypass import top_ftv_v_expiry_worst_waive

        if top_ftv_v_expiry_worst_waive(evidence):
            return True, "top_ftv_v_expiry_worst_waive"
        if bool(evidence.get("shallowOtmLocalBaseTradeable")):
            base_move = max(
                float(evidence.get("localBaseMovePct") or 0),
                float(evidence.get("ictBaseRelativeMovePct") or 0),
            )
            min_lb = float(
                getattr(settings, "shallow_otm_local_base_min_move_pct", 2.0) or 2.0
            )
            max_lb = float(
                getattr(settings, "shallow_otm_local_base_max_move_pct", 25.0) or 25.0
            )
            tier_u = str(evidence.get("tier") or tier or "").upper()
            if (
                tier_u in ("ELITE", "EXPLODING")
                and min_lb <= base_move <= max_lb + 1e-6
                and bool(
                    evidence.get("armedBaseLaunch")
                    or evidence.get("ictArmedBaseLaunch")
                )
            ):
                return True, "shallow_otm_local_base_expiry_worst_waive"
    if not bool(getattr(settings, "ict_defensive_base_rip_block_expiry_worst", True)):
        return True, "ok"
    min_tier = str(
        getattr(settings, "ict_defensive_base_rip_expiry_worst_min_tier", "ELITE")
        or "ELITE"
    ).upper()
    tier_rank = {"WATCH": 1, "BUILDING": 2, "EXPLODING": 3, "ELITE": 4}
    if tier_rank.get(str(tier or "").upper(), 0) < tier_rank.get(min_tier, 4):
        return False, f"expiry_worst_defensive_rip_tier_{str(tier or 'unknown').lower()}"
    min_quality = float(
        getattr(settings, "ict_defensive_base_rip_expiry_worst_min_quality", 85.0)
        or 85.0
    )
    if float(quality or 0) < min_quality:
        return False, f"expiry_worst_defensive_rip_quality<{min_quality:g}"
    min_score = float(
        getattr(settings, "ict_defensive_base_rip_expiry_worst_min_score", 90.0)
        or 90.0
    )
    if float(score or 0) < min_score:
        return False, f"expiry_worst_defensive_rip_score<{min_score:g}"
    min_v3 = float(
        getattr(settings, "ict_defensive_base_rip_expiry_worst_min_velocity_3s", 3.0)
        or 3.0
    )
    if float(velocity_3s or 0) < min_v3:
        return False, f"expiry_worst_defensive_rip_v3<{min_v3:g}"
    return True, "ok"


def good_day_ict_capture_active(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
    *,
    event: Any = None,
    ict: Optional[ICTBreakoutSignal] = None,
    day_mode: str = "",
    confidence_tier: str = "",
) -> tuple[bool, dict[str, Any]]:
    """ICT capture — AGGRESSIVE max-lots path + all-day early flat→vertical on NORMAL days."""
    settings = get_settings()
    meta: dict[str, Any] = {}

    from app.engines.dual_mode_strategy import resolve_trading_session_mode

    mode, mode_meta = resolve_trading_session_mode(
        state, snapshots, day_mode=day_mode, confidence_tier=confidence_tier,
    )
    meta["tradingMode"] = mode
    meta.update(mode_meta or {})

    if ict is None and event is not None:
        sym = str(getattr(event, "symbol", "") or "").upper()
        snap = snapshots.get(sym)
        ict = analyze_explosion_event_ict(event, snap)

    if ict is None:
        return False, meta

    meta["ict"] = ict.to_dict()

    # Max-profit / flat→vertical capture only when chart aligns with the option side.
    if bool(getattr(settings, "explosion_require_chart_align_enabled", True)) and event is not None:
        sym = str(getattr(event, "symbol", "") or "").upper()
        snap = snapshots.get(sym)
        chart = getattr(snap, "spotChart", None) if snap is not None else None
        if chart is not None:
            from app.engines.spot_direction import side_aligned_with_chart

            side = getattr(event, "side", None)
            if not side_aligned_with_chart(side, chart):
                meta["chartAligned"] = False
                meta["deniedReason"] = "ict_capture_requires_chart_align"
                return False, meta
            meta["chartAligned"] = True

    # Aggressive good-day path (unchanged intent).
    if settings.ict_good_day_capture_enabled and mode == "AGGRESSIVE":
        if ict.mega_rip or (ict.active and ict.score >= settings.ict_good_day_min_score):
            meta["maxProfitCapture"] = True
            meta["capturePath"] = "good_day_aggressive"
            return True, meta
        if ict.flat_then_vertical and ict.session_move_pct >= float(
            getattr(settings, "ict_early_vertical_min_session_move_pct", 28.0) or 28.0
        ):
            meta["maxProfitCapture"] = True
            meta["capturePath"] = "good_day_flat_vertical"
            return True, meta

    early_ok = (
        ict.active
        and ict.flat_then_vertical
        and (
            ict.volume_awakening
            or ict.displacement
            or ict.premium_fvg
            or ict.score >= float(getattr(settings, "ict_all_day_capture_min_score", 30.0) or 30.0)
        )
    )

    # All-day path — NORMAL / AGGRESSIVE: catch 26→70 CE and 12→392 PE style early.
    if getattr(settings, "ict_all_day_capture_enabled", True) and mode != "DEFENSIVE":
        if early_ok or ict.mega_rip:
            # Always mark max-profit so trail skips tiny hard TPs (not only on AGGRESSIVE).
            meta["maxProfitCapture"] = True
            meta["allDayIctCapture"] = True
            meta["capturePath"] = "all_day_flat_vertical"
            meta["lotMultiplier"] = (
                1.0 if mode == "AGGRESSIVE"
                else float(getattr(settings, "ict_all_day_lot_multiplier", 0.85) or 0.85)
            )
            return True, meta

    # DEFENSIVE / worst days — ELITE/EXPLODING clean base→vertical only (not BUILDING).
    if (
        mode == "DEFENSIVE"
        and getattr(settings, "ict_defensive_base_rip_enabled", True)
        and early_ok
        and not ict.mega_rip
    ):
        tier_u = ""
        if event is not None:
            tier_u = str(getattr(event, "tier", "") or "").upper()
        rip_raw = str(
            getattr(settings, "ict_defensive_base_rip_tiers_csv", "ELITE,EXPLODING")
            or "ELITE,EXPLODING"
        )
        rip_tiers = {t.strip().upper() for t in rip_raw.split(",") if t.strip()}
        # Require a known rip tier — empty/unknown must not open the Aug10 hole.
        if tier_u not in rip_tiers:
            meta["deniedReason"] = (
                "defensive_base_rip_tier_unknown"
                if not tier_u
                else f"defensive_base_rip_tier_{tier_u.lower()}"
            )
            return False, meta
        score = float(getattr(event, "explosion_score", 0) or 0) if event else 0.0
        v3 = float(getattr(event, "velocity_3s", 0) or 0) if event else float(ict.velocity_3s or 0)
        quality = float(getattr(ict, "flat_vertical_quality", 0) or 0)
        # EXPIRY WORST: ELITE + high floors. Other defensive days: top ELITE/EXPLODING only.
        if _expiry_worst_session(day_mode=day_mode, state=state, meta=meta):
            ok, deny = _expiry_worst_defensive_rip_allowed(
                tier=tier_u,
                quality=quality,
                score=score,
                velocity_3s=v3,
                settings=settings,
                evidence={
                    "mode": "explosion",
                    "tier": tier_u,
                    "explosionScore": score,
                    "flatVerticalQuality": quality,
                    "velocity3s": v3,
                    "localBaseMovePct": getattr(ict, "base_relative_move_pct", 0),
                    "vRipReady": getattr(ict, "v_rip_ready", False),
                    "firstLift": getattr(ict, "first_lift", False),
                },
            )
            if not ok:
                meta["deniedReason"] = deny
                meta["expiryWorstDefensiveRipBlocked"] = True
                return False, meta
        else:
            ok_top, deny_top = _defensive_base_rip_top_allowed(
                tier=tier_u,
                quality=quality,
                score=score,
                velocity_3s=v3,
                settings=settings,
                base_move_pct=float(getattr(ict, "base_relative_move_pct", 0) or 0),
                volume_awake=bool(getattr(ict, "volume_awakening", False)),
                v_rip_ready=bool(getattr(ict, "v_rip_ready", False)),
                armed_base_launch=bool(getattr(ict, "armed_base_launch", False)),
                first_lift=bool(getattr(ict, "first_lift", False)),
            )
            if not ok_top:
                meta["deniedReason"] = deny_top
                meta["defensiveRipTopBlocked"] = True
                return False, meta
        max_move = float(getattr(settings, "ict_defensive_base_rip_max_move_pct", 55.0) or 55.0)
        # ELITE local-base gate uses pad % (not session/day %) — day% can be 50+
        # while LTP is still ~28% off the pad; those must still take.
        if tier_u in ("ELITE", "EXPLODING"):
            elite_hi = float(
                getattr(settings, "elite_local_base_max_move_pct", 40.0) or 40.0
            )
            from app.engines.elite_never_block import top_explosion_must_take_active

            snap_for_mt = None
            if event is not None:
                snap_for_mt = snapshots.get(str(getattr(event, "symbol", "") or "").upper())
            if not top_explosion_must_take_active(event=event, snap=snap_for_mt):
                pad = float(getattr(ict, "base_relative_move_pct", 0) or 0)
                if pad <= 0 and event is not None:
                    try:
                        from app.engines.explosion_entry_guards import (
                            effective_local_base_move_pct,
                        )

                        pad = float(effective_local_base_move_pct(event, ict) or 0)
                    except Exception:
                        pad = 0.0
                timing_move = pad if pad > 0 else float(ict.session_move_pct or 0)
                if timing_move > elite_hi:
                    meta["deniedReason"] = (
                        f"elite_local_base_high_{timing_move:.0f}%"
                    )
                    return False, meta
        if ict.session_move_pct <= max_move and (ict.volume_awakening or ict.displacement):
            meta["maxProfitCapture"] = True
            meta["allDayIctCapture"] = True
            meta["defensiveBaseRip"] = True
            meta["capturePath"] = "defensive_base_flat_vertical"
            full_lots_raw = str(
                getattr(
                    settings,
                    "ict_defensive_base_rip_full_lots_tiers_csv",
                    "ELITE,EXPLODING",
                )
                or "ELITE,EXPLODING"
            )
            full_lots_tiers = {
                t.strip().upper() for t in full_lots_raw.split(",") if t.strip()
            }
            allow_full = (
                getattr(settings, "ict_defensive_base_rip_full_lots", True)
                and tier_u in full_lots_tiers
            )
            if allow_full:
                meta["lotMultiplier"] = 1.0
                meta["baseWindowFullLots"] = True
            else:
                # Cap below 0.99 so auto_trader force-max path cannot fire.
                mult = float(
                    getattr(settings, "ict_defensive_base_rip_lot_multiplier", 0.55)
                    or 0.55
                )
                if mult >= 0.99:
                    mult = 0.55
                meta["lotMultiplier"] = mult
            return True, meta

    return False, meta


def ict_explosion_rank_bonus(ict: ICTBreakoutSignal, trading_mode: str = "NORMAL") -> float:
    if not ict.active:
        return 0.0
    settings = get_settings()
    bonus = min(settings.ict_max_rank_bonus, ict.score * 0.35)
    if trading_mode == "AGGRESSIVE":
        bonus += settings.ict_good_day_rank_bonus
    if ict.mega_rip:
        bonus += settings.ict_mega_rip_rank_bonus
    return bonus


def _ict_max_profit_trade(trade: Any) -> bool:
    ctx = getattr(trade, "entryContext", None) or {}
    return bool(
        ctx.get("maxProfitCapture")
        or ctx.get("firstLiftCapture")
        or ctx.get("ictFirstLift")
        or ctx.get("goodDayIctCapture")
        or ctx.get("allDayIctCapture")
        or ctx.get("ictMegaRip")
        or ctx.get("ictFlatThenVertical")
        or ctx.get("defensiveBaseRip")
    )


def ict_no_progress_seconds(trade: Any, settings=None) -> int:
    """Extended hold for ICT mega rips — ride 8→393 style moves."""
    settings = settings or get_settings()
    ctx = getattr(trade, "entryContext", None) or {}
    if _ict_max_profit_trade(trade) or ctx.get("ictMegaRip") or ctx.get("goodDayIctCapture"):
        return settings.ict_mega_rip_no_progress_seconds
    if ctx.get("ictBreakout"):
        return settings.ict_breakout_no_progress_seconds
    return settings.explosion_no_progress_seconds


def ict_trail_arm_multiplier(trade: Any) -> float:
    ctx = getattr(trade, "entryContext", None) or {}
    settings = get_settings()
    if _ict_max_profit_trade(trade) or ctx.get("ictMegaRip") or ctx.get("goodDayIctCapture"):
        return settings.ict_mega_rip_trail_arm_multiplier
    if ctx.get("ictBreakout"):
        return settings.ict_breakout_trail_arm_multiplier
    return 1.0


def ict_monitor_summary(snapshots: dict[str, SymbolSnapshot]) -> dict[str, Any]:
    """Top ICT/FVG breakout signals across symbols — for live dashboard."""
    settings = get_settings()
    if not settings.ict_breakout_monitor_enabled:
        return {"enabled": False, "signals": []}

    from app.engines.explosion_detector import ExplosionEvent

    signals: list[dict[str, Any]] = []
    for symbol, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        for alert in snap.explosionAlerts or []:
            ict_active = bool(alert.get("ictBreakout"))
            ict_score = float(alert.get("ictScore") or 0)
            if not ict_active and ict_score < settings.ict_breakout_min_score * 0.5:
                continue
            event = ExplosionEvent(
                symbol=symbol,
                side=Side(alert["side"]),
                strike=float(alert.get("strike") or 0),
                premium=float(alert.get("premium") or 0),
                velocity_3s=float(alert.get("velocity3s") or 0),
                velocity_9s=float(alert.get("velocity9s") or 0),
                velocity_15s=float(alert.get("velocity15s") or 0),
                volume_surge=float(alert.get("volumeSurge") or 1),
                explosion_score=float(alert.get("explosionScore") or 0),
                tier=str(alert.get("tier") or "WATCH"),
                reason=str(alert.get("reason") or ""),
                daily_move_pct=float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0),
                peak_move_pct=float(alert.get("peakMovePct") or 0),
            )
            ict = analyze_explosion_event_ict(event, snap)
            if not ict.active and ict.score < settings.ict_breakout_min_score * 0.5:
                continue
            signals.append({
                "symbol": symbol,
                "side": alert.get("side"),
                "strike": alert.get("strike"),
                "premium": alert.get("premium"),
                **ict.to_dict(),
            })

    signals.sort(key=lambda s: (s.get("megaRip", False), s.get("score", 0)), reverse=True)
    return {
        "enabled": True,
        "signalCount": len(signals),
        "activeCount": sum(1 for s in signals if s.get("active")),
        "megaRipCount": sum(1 for s in signals if s.get("megaRip")),
        "topSignal": signals[0] if signals else None,
        "signals": signals[:8],
    }
