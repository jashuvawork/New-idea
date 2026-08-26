"""Pre-lift pad capture lanes — enter before the vertical spike.

Each lane mirrors slow_grind / fast_bullish: readiness proof → alert stamp →
FTV policy → max lots → 100% trail. All lanes share the ₹18–₹220 pad band.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot

# Readiness reason strings — keep in sync with building_ftv_gates.PAD_LANE_READY_REASONS.
SQUEEZE_RELEASE_READY = "squeeze_release_ready"
INDEX_LED_OPTION_LAG_READY = "index_led_option_lag_ready"
STEALTH_CVD_COIL_READY = "stealth_cvd_coil_ready"
MICRO_PULLBACK_RETEST_READY = "micro_pullback_retest_ready"
PREMIUM_FVG_PAD_READY = "premium_fvg_pad_ready"
DOUBLE_DIP_VBASE_READY = "double_dip_vbase_ready"

ALL_PAD_LANE_REASONS = frozenset(
    {
        "slow_grind_sudden_lift_ready",
        "slow_grind_armed_trough_ready",
        "slow_grind_consolidation_base_ready",
        "fast_bullish_local_base_ready",
        "v_rip_session_low_ready",
        "building_local_base_lift_ready",
        SQUEEZE_RELEASE_READY,
        INDEX_LED_OPTION_LAG_READY,
        STEALTH_CVD_COIL_READY,
        MICRO_PULLBACK_RETEST_READY,
        PREMIUM_FVG_PAD_READY,
        DOUBLE_DIP_VBASE_READY,
        "early_radar_pad_ready",
    }
)

PAD_LANE_FTV_MODES = frozenset(
    {
        "SLOW_GRIND_FTV",
        "FAST_BULLISH_FTV",
        "SQUEEZE_RELEASE_FTV",
        "INDEX_LED_OPTION_LAG_FTV",
        "STEALTH_CVD_COIL_FTV",
        "MICRO_PULLBACK_RETEST_FTV",
        "PREMIUM_FVG_PAD_FTV",
        "DOUBLE_DIP_VBASE_FTV",
        "EARLY_RADAR_PAD_FTV",
    }
)


def pad_lane_pre_lift(evidence: Mapping[str, Any]) -> bool:
    return bool(
        evidence.get("slowGrindSuddenLift")
        or evidence.get("fastBullishLocalBase")
        or evidence.get("squeezeRelease")
        or evidence.get("indexLedOptionLag")
        or evidence.get("stealthCvdCoil")
        or evidence.get("microPullbackRetest")
        or evidence.get("premiumFvgPad")
        or evidence.get("doubleDipVbase")
        or evidence.get("earlyRadarPadCapture")
    )


def pad_lane_cold_velocity_ok(
    evidence: Mapping[str, Any], v3: float, v9: float
) -> bool:
    """Pre-lift pad lanes that allow mildly negative / flat velocity snapshots."""
    if evidence.get("slowGrindSuddenLift") and -0.8 <= v3 <= 1.5:
        return True
    if evidence.get("stealthCvdCoil") and -0.5 <= v3 <= 1.0:
        return True
    if evidence.get("microPullbackRetest") and -1.2 <= v3 <= 0.5 and v9 >= -0.5:
        return True
    if evidence.get("squeezeRelease") and v3 <= 1.5:
        return True
    if evidence.get("indexLedOptionLag") and v3 <= 1.2:
        return True
    if evidence.get("premiumFvgPad") and v3 <= 2.0:
        return True
    if evidence.get("doubleDipVbase") and -0.8 <= v3 <= 1.5:
        return True
    if evidence.get("earlyRadarPadCapture") and -0.8 <= v3 <= 1.5:
        return True
    if evidence.get("vRipReady") and -1.2 <= v3 <= 1.5 and v9 >= -0.8:
        return True
    if evidence.get("firstLiftLocalBase") and -1.5 <= v3 <= 1.5 and v9 >= -1.0:
        return True
    tier = str(evidence.get("tier") or "").upper()
    local_move = float(evidence.get("localBaseMovePct") or 0)
    if (
        tier in ("ELITE", "EXPLODING")
        and bool(evidence.get("flatThenVertical") and evidence.get("activeBreakout"))
        and 2.0 <= local_move <= 40.0
        and -1.2 <= v3 <= 1.5
        and v9 >= -0.8
    ):
        return True
    return False


def pad_lane_ftv_waives_timing_block(evidence: Mapping[str, Any]) -> bool:
    """Pad-lane local-base FTV may waive cold-velocity / FAILED_LAUNCH timing blocks."""
    settings = get_settings()
    if not bool(getattr(settings, "pad_lane_ftv_waives_timing_block_enabled", True)):
        return False
    if evidence.get("faded") or evidence.get("exhaustedReentry"):
        return False
    timing = str(evidence.get("timingAssessment") or "").upper()
    if timing in ("FADED", "FADING", "EXHAUSTED", "NEGATIVE", "REJECT", "BLOCKED"):
        return False
    v3 = float(evidence.get("velocity3s") or 0)
    v9 = float(evidence.get("velocity9s") or 0)
    return pad_lane_cold_velocity_ok(evidence, v3, v9)


def pad_lane_grade_floor_applies(evidence: Mapping[str, Any]) -> bool:
    """True when rank/top-moment grading should floor to A for pad-lane FTV."""
    settings = get_settings()
    if not bool(getattr(settings, "pad_lane_grade_floor_enabled", True)):
        return False
    if evidence.get("faded") or evidence.get("exhaustedReentry") or evidence.get("midRipCoil"):
        return False
    tier = str(evidence.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False
    if evidence.get("vRipReady") or evidence.get("earlyRadarPadCapture"):
        if not pad_lane_ftv_waives_allocation_rank_one(evidence):
            return False
        v3 = float(evidence.get("velocity3s") or 0)
        v9 = float(evidence.get("velocity9s") or 0)
        return pad_lane_cold_velocity_ok(evidence, v3, v9)
    if not bool(evidence.get("flatThenVertical") and evidence.get("activeBreakout")):
        return False
    if not bool(evidence.get("volumeAwaken") or evidence.get("orderflowPositive")):
        return False
    score = float(evidence.get("explosionScore") or 0)
    if score < float(
        getattr(settings, "pad_lane_elite_ftv_chart_bypass_min_score", 45.0) or 45.0
    ):
        return False
    local_move = max(
        float(evidence.get("localBaseMovePct") or 0),
        float(evidence.get("offLowMovePct") or 0),
    )
    return 2.0 <= local_move <= 40.0


def _pad_premium_band_ok(
    premium: float,
    *,
    settings: Any,
    max_premium_setting: str,
    reason_prefix: str,
) -> tuple[bool, str]:
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


def _side_from_row(event: Any, row: dict[str, Any]) -> str:
    return str(
        getattr(getattr(event, "side", None), "value", getattr(event, "side", ""))
        or row.get("side")
        or ""
    ).upper()


def _base_move(ict: Any, row: dict[str, Any]) -> float:
    return float(
        getattr(ict, "base_relative_move_pct", 0)
        or row.get("ictBaseRelativeMovePct")
        or row.get("localBaseMovePct")
        or 0
    )


def _velocity_3s(event: Any, row: dict[str, Any], ict: Any) -> float:
    return float(
        getattr(event, "velocity_3s", 0)
        or row.get("velocity3s")
        or getattr(ict, "velocity_3s", 0)
        or 0
    )


def _velocity_9s(event: Any, row: dict[str, Any], ict: Any) -> float:
    return float(
        getattr(event, "velocity_9s", 0)
        or row.get("velocity9s")
        or getattr(ict, "velocity_9s", 0)
        or 0
    )


def _base_armed(ict: Any, row: dict[str, Any]) -> bool:
    return bool(
        getattr(ict, "base_armed", False)
        or row.get("ictBaseArmed")
        or getattr(ict, "local_swing_base", False)
    )


def _structured(ict: Any, row: dict[str, Any], settings: Any) -> bool:
    return bool(
        getattr(ict, "flat_then_vertical", False)
        or getattr(ict, "active", False)
        or row.get("ictFlatThenVertical")
        or row.get("ictBreakout")
        or float(getattr(ict, "flat_vertical_quality", 0) or 0)
        >= float(getattr(settings, "slow_grind_sudden_lift_min_flat_quality", 50.0) or 50.0)
    )


def _atm_itm_ok(
    *,
    side: str,
    strike: float,
    snap: SymbolSnapshot,
) -> tuple[bool, str]:
    if side not in ("CALL", "PUT"):
        return False, "side_invalid"
    if strike <= 0 or float(getattr(snap, "spot", 0) or 0) <= 0:
        return False, "moneyness_unavailable"
    from app.engines.moneyness import classify_moneyness

    spot = float(getattr(snap, "spot", 0) or 0)
    atm = float(getattr(snap, "atmStrike", 0) or 0)
    money = classify_moneyness(
        Side(side),
        strike,
        spot,
        symbol=str(getattr(snap, "symbol", "") or ""),
        atm=atm if atm > 0 else None,
    )
    if money not in ("ATM", "ITM"):
        return False, f"requires_atm_itm_{money.lower()}"
    return True, ""


def _stamp_pad_lane(alert: Optional[dict[str, Any]], reason: str, **flags: Any) -> None:
    if not isinstance(alert, dict):
        return
    alert["ictBaseReadinessReason"] = reason
    for key, value in flags.items():
        alert[key] = value


def _squeeze_state(
    snap: SymbolSnapshot,
    side: str,
    settings: Any,
) -> tuple[bool, bool, list[str]]:
    """Return (compressed, fresh_release, signal_names)."""
    signals: list[str] = []
    ca = getattr(snap, "chartAnalysis", None)
    sq = getattr(ca, "squeeze", None) if ca is not None else None
    if not isinstance(sq, dict) or not sq:
        return False, False, signals
    side_u = str(side or "").upper()
    bars_on = int(sq.get("bars_on") or 0)
    bsf = int(sq.get("bars_since_fired") or -1)
    direction = str(sq.get("direction") or "NEUTRAL").upper()
    target = "BEARISH" if side_u == "PUT" else "BULLISH"
    min_bars = int(getattr(settings, "squeeze_release_min_bars_on", 3) or 3)
    compressed = bars_on >= min_bars
    if compressed:
        signals.append("squeeze_compressed")
    window = int(getattr(settings, "squeeze_fresh_window_bars", 3) or 3)
    fresh = 0 <= bsf <= window and direction == target
    if fresh:
        signals.append("squeeze_fresh_release")
    return compressed, fresh, signals


def squeeze_release_readiness(
    *,
    snap: Optional[SymbolSnapshot],
    event: Any = None,
    ict: Any = None,
    alert: Optional[dict[str, Any]] = None,
    settings: Any = None,
) -> tuple[bool, str]:
    """Bollinger-in-Keltner compression → fresh release at the pad before vertical lift."""
    s = settings or get_settings()
    if not bool(getattr(s, "squeeze_release_capture_enabled", True)):
        return False, ""
    row = alert if isinstance(alert, dict) else {}
    if snap is None:
        return False, "squeeze_release_chart_missing"

    premium = float(getattr(event, "premium", 0) or row.get("premium") or 0)
    prem_ok, prem_reason = _pad_premium_band_ok(
        premium,
        settings=s,
        max_premium_setting="squeeze_release_max_premium_inr",
        reason_prefix="squeeze_release",
    )
    if not prem_ok:
        return False, prem_reason

    move = _base_move(ict, row)
    lo = float(getattr(s, "squeeze_release_min_move_pct", 2.0) or 2.0)
    hi = float(getattr(s, "squeeze_release_max_move_pct", 30.0) or 30.0)
    if not (lo <= move <= hi + 1e-6):
        return False, f"squeeze_release_pad_outside_{lo:g}_{hi:g}"

    v3 = _velocity_3s(event, row, ict)
    max_v3 = float(getattr(s, "squeeze_release_max_velocity_3s", 1.5) or 1.5)
    if v3 > max_v3:
        return False, f"squeeze_release_velocity3s>{max_v3:g}"

    if not _base_armed(ict, row):
        return False, "squeeze_release_base_not_armed"
    if not _structured(ict, row, s):
        return False, "squeeze_release_structure_missing"

    side = _side_from_row(event, row)
    compressed, fresh, _ = _squeeze_state(snap, side, s)
    if not (compressed or fresh):
        return False, "squeeze_release_not_compressed"

    mn_ok, mn_reason = _atm_itm_ok(
        side=side,
        strike=float(getattr(event, "strike", 0) or row.get("strike") or 0),
        snap=snap,
    )
    if not mn_ok:
        return False, f"squeeze_release_{mn_reason}"

    _stamp_pad_lane(
        alert,
        SQUEEZE_RELEASE_READY,
        squeezeReleaseReady=True,
        ictSqueezeRelease=True,
    )
    return True, SQUEEZE_RELEASE_READY


def index_led_option_lag_readiness(
    *,
    snap: Optional[SymbolSnapshot],
    event: Any = None,
    ict: Any = None,
    alert: Optional[dict[str, Any]] = None,
    settings: Any = None,
) -> tuple[bool, str]:
    """Index already thrusting while option premium is still flat in the pad band."""
    s = settings or get_settings()
    if not bool(getattr(s, "index_led_option_lag_capture_enabled", True)):
        return False, ""
    row = alert if isinstance(alert, dict) else {}
    if snap is None:
        return False, "index_lag_chart_missing"

    premium = float(getattr(event, "premium", 0) or row.get("premium") or 0)
    prem_ok, prem_reason = _pad_premium_band_ok(
        premium,
        settings=s,
        max_premium_setting="index_led_option_lag_max_premium_inr",
        reason_prefix="index_lag",
    )
    if not prem_ok:
        return False, prem_reason

    move = _base_move(ict, row)
    lo = float(getattr(s, "index_led_option_lag_min_move_pct", 2.0) or 2.0)
    hi = float(getattr(s, "index_led_option_lag_max_move_pct", 25.0) or 25.0)
    if not (lo <= move <= hi + 1e-6):
        return False, f"index_lag_pad_outside_{lo:g}_{hi:g}"

    v3 = _velocity_3s(event, row, ict)
    max_v3 = float(getattr(s, "index_led_option_lag_max_option_velocity_3s", 1.2) or 1.2)
    if v3 > max_v3:
        return False, f"index_lag_option_velocity3s>{max_v3:g}"

    if not _base_armed(ict, row):
        return False, "index_lag_base_not_armed"
    if not _structured(ict, row, s):
        return False, "index_lag_structure_missing"

    side = _side_from_row(event, row)
    index_confirm = bool(
        row.get("indexHelpersConfirm")
        or row.get("indexTickSpike")
        or row.get("indexDrift")
        or row.get("indexSpikeBurst")
    )
    if not index_confirm and snap is not None:
        try:
            from app.engines.index_tick_helpers import (
                evaluate_index_tick_helpers,
                stamp_index_tick_helpers,
            )

            idx = evaluate_index_tick_helpers(snap=snap, side=side, alert=row)
            stamp_index_tick_helpers(row, idx)
            index_confirm = bool(
                idx.confirming
                or idx.tick_spike
                or idx.tick_align
                or idx.drift_align
            )
        except Exception:
            index_confirm = False
    if not index_confirm:
        return False, "index_lag_helpers_missing"

    min_idx_v3 = float(
        getattr(s, "index_led_option_lag_min_index_velocity_3s", 0.02) or 0.02
    )
    idx_v3 = abs(
        float(
            row.get("indexSpotMove3s")
            or getattr(snap, "indexSpotMove3s", 0)
            or 0
        )
    )
    if idx_v3 < min_idx_v3:
        return False, f"index_lag_index_velocity3s<{min_idx_v3:g}"

    mn_ok, mn_reason = _atm_itm_ok(
        side=side,
        strike=float(getattr(event, "strike", 0) or row.get("strike") or 0),
        snap=snap,
    )
    if not mn_ok:
        return False, f"index_lag_{mn_reason}"

    _stamp_pad_lane(
        alert,
        INDEX_LED_OPTION_LAG_READY,
        indexLedOptionLagReady=True,
        ictIndexLedOptionLag=True,
    )
    return True, INDEX_LED_OPTION_LAG_READY


def stealth_cvd_coil_readiness(
    *,
    snap: Optional[SymbolSnapshot],
    event: Any = None,
    ict: Any = None,
    alert: Optional[dict[str, Any]] = None,
    settings: Any = None,
) -> tuple[bool, str]:
    """Flat premium coil with CVD buying/acceleration building before volume spikes."""
    s = settings or get_settings()
    if not bool(getattr(s, "stealth_cvd_coil_capture_enabled", True)):
        return False, ""
    row = alert if isinstance(alert, dict) else {}
    if snap is None:
        return False, "stealth_cvd_chart_missing"

    premium = float(getattr(event, "premium", 0) or row.get("premium") or 0)
    prem_ok, prem_reason = _pad_premium_band_ok(
        premium,
        settings=s,
        max_premium_setting="stealth_cvd_coil_max_premium_inr",
        reason_prefix="stealth_cvd",
    )
    if not prem_ok:
        return False, prem_reason

    move = _base_move(ict, row)
    lo = float(getattr(s, "stealth_cvd_coil_min_move_pct", 2.0) or 2.0)
    hi = float(getattr(s, "stealth_cvd_coil_max_move_pct", 25.0) or 25.0)
    if not (lo <= move <= hi + 1e-6):
        return False, f"stealth_cvd_pad_outside_{lo:g}_{hi:g}"

    v3 = _velocity_3s(event, row, ict)
    min_v3 = float(getattr(s, "stealth_cvd_coil_min_velocity_3s", -0.5) or -0.5)
    max_v3 = float(getattr(s, "stealth_cvd_coil_max_velocity_3s", 1.0) or 1.0)
    if v3 < min_v3:
        return False, f"stealth_cvd_velocity3s<{min_v3:g}"
    if v3 > max_v3:
        return False, f"stealth_cvd_velocity3s>{max_v3:g}"

    if not _base_armed(ict, row):
        return False, "stealth_cvd_base_not_armed"
    if not _structured(ict, row, s):
        return False, "stealth_cvd_structure_missing"

    volume_awake = bool(
        getattr(ict, "volume_awakening", False)
        or row.get("ictVolumeAwakening")
        or row.get("volumeAwaken")
    )
    max_surge = float(getattr(s, "stealth_cvd_coil_max_volume_surge", 1.8) or 1.8)
    surge = float(
        getattr(event, "volume_surge", 0)
        or row.get("volumeSurge")
        or getattr(ict, "volume_surge", 0)
        or 0
    )
    if volume_awake and surge >= max_surge:
        return False, "stealth_cvd_volume_already_awake"

    cvd_buying = bool(row.get("cvdBuying") or row.get("optionCvdBuying"))
    cvd_accel = bool(row.get("cvdAcceleration") or row.get("optionCvdAcceleration"))
    if snap is not None:
        try:
            from app.engines.advanced_indicators import (
                option_cvd_acceleration_confirms_buying,
                option_cvd_confirms_buying,
            )

            side = _side_from_row(event, row)
            if side in ("CALL", "PUT"):
                strike = float(getattr(event, "strike", 0) or row.get("strike") or 0)
                cvd_buying = cvd_buying or option_cvd_confirms_buying(
                    snap, strike, Side(side),
                )
                cvd_accel = cvd_accel or option_cvd_acceleration_confirms_buying(
                    snap, strike, Side(side),
                )
        except Exception:
            pass
    if not (cvd_buying and cvd_accel):
        return False, "stealth_cvd_orderflow_missing"

    side = _side_from_row(event, row)
    mn_ok, mn_reason = _atm_itm_ok(
        side=side,
        strike=float(getattr(event, "strike", 0) or row.get("strike") or 0),
        snap=snap,
    )
    if not mn_ok:
        return False, f"stealth_cvd_{mn_reason}"

    _stamp_pad_lane(
        alert,
        STEALTH_CVD_COIL_READY,
        stealthCvdCoilReady=True,
        ictStealthCvdCoil=True,
    )
    return True, STEALTH_CVD_COIL_READY


def micro_pullback_retest_readiness(
    *,
    snap: Optional[SymbolSnapshot],
    event: Any = None,
    ict: Any = None,
    alert: Optional[dict[str, Any]] = None,
    settings: Any = None,
) -> tuple[bool, str]:
    """Shallow retest dip on an armed base before the vertical lift resumes."""
    s = settings or get_settings()
    if not bool(getattr(s, "micro_pullback_retest_capture_enabled", True)):
        return False, ""
    row = alert if isinstance(alert, dict) else {}
    if snap is None:
        return False, "micro_pullback_chart_missing"

    premium = float(getattr(event, "premium", 0) or row.get("premium") or 0)
    prem_ok, prem_reason = _pad_premium_band_ok(
        premium,
        settings=s,
        max_premium_setting="micro_pullback_retest_max_premium_inr",
        reason_prefix="micro_pullback",
    )
    if not prem_ok:
        return False, prem_reason

    move = _base_move(ict, row)
    lo = float(getattr(s, "micro_pullback_retest_min_move_pct", 5.0) or 5.0)
    hi = float(getattr(s, "micro_pullback_retest_max_move_pct", 25.0) or 25.0)
    if not (lo <= move <= hi + 1e-6):
        return False, f"micro_pullback_pad_outside_{lo:g}_{hi:g}"

    v3 = _velocity_3s(event, row, ict)
    v9 = _velocity_9s(event, row, ict)
    min_v3 = float(getattr(s, "micro_pullback_retest_min_velocity_3s", -1.2) or -1.2)
    max_v3 = float(getattr(s, "micro_pullback_retest_max_velocity_3s", 0.5) or 0.5)
    min_v9 = float(getattr(s, "micro_pullback_retest_min_velocity_9s", -0.5) or -0.5)
    if v3 > max_v3 or v3 < min_v3:
        return False, f"micro_pullback_velocity3s_outside_{min_v3:g}_{max_v3:g}"
    if v9 < min_v9:
        return False, f"micro_pullback_velocity9s<{min_v9:g}"

    if not _base_armed(ict, row):
        return False, "micro_pullback_base_not_armed"
    if not _structured(ict, row, s):
        return False, "micro_pullback_structure_missing"

    heat = bool(
        getattr(ict, "volume_awakening", False)
        or row.get("ictVolumeAwakening")
        or row.get("volumeAwaken")
        or row.get("cvdBuying")
        or row.get("orderflowPositive")
    )
    if not heat:
        return False, "micro_pullback_heat_missing"

    trigger = bool(
        getattr(ict, "first_lift", False)
        or row.get("ictFirstLift")
        or getattr(ict, "armed_base_launch", False)
        or row.get("ictArmedBaseLaunch")
        or getattr(ict, "armed_base_sustained_lift", False)
        or row.get("ictArmedBaseSustainedLift")
    )
    if not trigger:
        return False, "micro_pullback_trigger_missing"

    side = _side_from_row(event, row)
    mn_ok, mn_reason = _atm_itm_ok(
        side=side,
        strike=float(getattr(event, "strike", 0) or row.get("strike") or 0),
        snap=snap,
    )
    if not mn_ok:
        return False, f"micro_pullback_{mn_reason}"

    _stamp_pad_lane(
        alert,
        MICRO_PULLBACK_RETEST_READY,
        microPullbackRetestReady=True,
        ictMicroPullbackRetest=True,
    )
    return True, MICRO_PULLBACK_RETEST_READY


def premium_fvg_pad_readiness(
    *,
    snap: Optional[SymbolSnapshot],
    event: Any = None,
    ict: Any = None,
    alert: Optional[dict[str, Any]] = None,
    settings: Any = None,
) -> tuple[bool, str]:
    """Option premium FVG at the local base before the vertical leg extends."""
    s = settings or get_settings()
    if not bool(getattr(s, "premium_fvg_pad_capture_enabled", True)):
        return False, ""
    row = alert if isinstance(alert, dict) else {}
    if snap is None:
        return False, "premium_fvg_pad_chart_missing"

    premium = float(getattr(event, "premium", 0) or row.get("premium") or 0)
    prem_ok, prem_reason = _pad_premium_band_ok(
        premium,
        settings=s,
        max_premium_setting="premium_fvg_pad_max_premium_inr",
        reason_prefix="premium_fvg_pad",
    )
    if not prem_ok:
        return False, prem_reason

    move = _base_move(ict, row)
    lo = float(getattr(s, "premium_fvg_pad_min_move_pct", 2.0) or 2.0)
    hi = float(getattr(s, "premium_fvg_pad_max_move_pct", 28.0) or 28.0)
    if not (lo <= move <= hi + 1e-6):
        return False, f"premium_fvg_pad_outside_{lo:g}_{hi:g}"

    v3 = _velocity_3s(event, row, ict)
    max_v3 = float(getattr(s, "premium_fvg_pad_max_velocity_3s", 2.0) or 2.0)
    if v3 > max_v3:
        return False, f"premium_fvg_pad_velocity3s>{max_v3:g}"

    if not _base_armed(ict, row):
        return False, "premium_fvg_pad_base_not_armed"
    if not _structured(ict, row, s):
        return False, "premium_fvg_pad_structure_missing"

    fvg = bool(
        getattr(ict, "premium_fvg", False)
        or row.get("ictPremiumFvg")
        or row.get("premiumFvg")
    )
    if not fvg:
        return False, "premium_fvg_pad_fvg_missing"

    side = _side_from_row(event, row)
    mn_ok, mn_reason = _atm_itm_ok(
        side=side,
        strike=float(getattr(event, "strike", 0) or row.get("strike") or 0),
        snap=snap,
    )
    if not mn_ok:
        return False, f"premium_fvg_pad_{mn_reason}"

    _stamp_pad_lane(
        alert,
        PREMIUM_FVG_PAD_READY,
        premiumFvgPadReady=True,
        ictPremiumFvgPad=True,
    )
    return True, PREMIUM_FVG_PAD_READY


def _double_dip_vbase_shape(
    *,
    symbol: str,
    strike: float,
    side: str,
    premium: float,
    ict: Any,
    row: dict[str, Any],
    settings: Any,
) -> tuple[bool, str, dict[str, float]]:
    """Session low → bounce → retest low (W at trough) before second lift."""
    from app.engines.explosion_detector import (
        get_session_low_premium,
        get_session_peak_premium,
        mid_rip_armed_coil,
        session_low_relative_move_pct,
    )

    if bool(row.get("ictMidRipCoil") or row.get("midRipCoil")):
        return False, "double_dip_mid_rip_coil", {}

    sess_low = get_session_low_premium(symbol, strike, side)
    sess_peak = get_session_peak_premium(symbol, strike, side)
    if sess_low <= 0 or sess_peak <= 0 or premium <= 0:
        return False, "double_dip_session_missing", {}

    min_bounce = float(
        getattr(settings, "double_dip_vbase_min_first_bounce_pct", 8.0) or 8.0
    )
    first_bounce_pct = (sess_peak - sess_low) / sess_low * 100.0
    if first_bounce_pct < min_bounce:
        return False, "double_dip_first_bounce_too_small", {}

    off_low = session_low_relative_move_pct(symbol, strike, side, premium)
    max_retest = float(
        getattr(settings, "double_dip_vbase_max_retest_off_low_pct", 12.0) or 12.0
    )
    if off_low > max_retest + 1e-6:
        return False, "double_dip_not_near_low", {}

    bounce = sess_peak - sess_low
    if bounce <= 0:
        return False, "double_dip_flat_bounce", {}
    retrace_ratio = (sess_peak - premium) / bounce
    min_retrace = float(
        getattr(settings, "double_dip_vbase_min_retrace_ratio", 0.55) or 0.55
    )
    if retrace_ratio < min_retrace:
        return False, "double_dip_shallow_retest", {}

    armed_base = float(
        getattr(ict, "base_premium", 0)
        or row.get("ictBasePremium")
        or premium
        or 0
    )
    if mid_rip_armed_coil(
        session_low=sess_low,
        armed_base=armed_base,
        premium=premium,
        session_peak=sess_peak,
        settings=settings,
    ):
        return False, "double_dip_mid_rip_armed", {}

    return True, "", {
        "offLowMovePct": off_low,
        "firstBouncePct": first_bounce_pct,
        "retraceRatio": retrace_ratio,
        "sessionLowPremium": sess_low,
        "sessionPeakPremium": sess_peak,
    }


def double_dip_vbase_readiness(
    *,
    snap: Optional[SymbolSnapshot],
    event: Any = None,
    ict: Any = None,
    alert: Optional[dict[str, Any]] = None,
    settings: Any = None,
) -> tuple[bool, str]:
    """Session-trough W: bounce off low, retest low, lift on second touch."""
    s = settings or get_settings()
    if not bool(getattr(s, "double_dip_vbase_capture_enabled", True)):
        return False, ""
    row = alert if isinstance(alert, dict) else {}
    if snap is None:
        return False, "double_dip_vbase_chart_missing"

    premium = float(getattr(event, "premium", 0) or row.get("premium") or 0)
    prem_ok, prem_reason = _pad_premium_band_ok(
        premium,
        settings=s,
        max_premium_setting="double_dip_vbase_max_premium_inr",
        reason_prefix="double_dip_vbase",
    )
    if not prem_ok:
        return False, prem_reason

    move = _base_move(ict, row)
    lo = float(getattr(s, "double_dip_vbase_min_move_pct", 2.0) or 2.0)
    hi = float(getattr(s, "double_dip_vbase_max_move_pct", 20.0) or 20.0)
    if not (lo <= move <= hi + 1e-6):
        return False, f"double_dip_vbase_pad_outside_{lo:g}_{hi:g}"

    v3 = _velocity_3s(event, row, ict)
    min_v3 = float(getattr(s, "double_dip_vbase_min_velocity_3s", -0.8) or -0.8)
    max_v3 = float(getattr(s, "double_dip_vbase_max_velocity_3s", 1.5) or 1.5)
    if v3 < min_v3:
        return False, f"double_dip_vbase_velocity3s<{min_v3:g}"
    if v3 > max_v3:
        return False, f"double_dip_vbase_velocity3s>{max_v3:g}"

    if not _base_armed(ict, row):
        return False, "double_dip_vbase_base_not_armed"
    if not _structured(ict, row, s):
        return False, "double_dip_vbase_structure_missing"

    side = _side_from_row(event, row)
    symbol = str(getattr(snap, "symbol", "") or row.get("symbol") or "")
    strike = float(getattr(event, "strike", 0) or row.get("strike") or 0)
    shape_ok, shape_reason, metrics = _double_dip_vbase_shape(
        symbol=symbol,
        strike=strike,
        side=side,
        premium=premium,
        ict=ict,
        row=row,
        settings=s,
    )
    if not shape_ok:
        return False, shape_reason

    mn_ok, mn_reason = _atm_itm_ok(side=side, strike=strike, snap=snap)
    if not mn_ok:
        return False, f"double_dip_vbase_{mn_reason}"

    if isinstance(alert, dict):
        alert["offLowMovePct"] = metrics.get("offLowMovePct")
        alert["doubleDipFirstBouncePct"] = metrics.get("firstBouncePct")
        alert["doubleDipRetraceRatio"] = metrics.get("retraceRatio")

    _stamp_pad_lane(
        alert,
        DOUBLE_DIP_VBASE_READY,
        doubleDipVbaseReady=True,
        ictDoubleDipVbase=True,
    )
    return True, DOUBLE_DIP_VBASE_READY


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def _pad_lane_chart_metrics(
    *,
    event: Any = None,
    alert: Optional[dict[str, Any]] = None,
) -> tuple[float, float, float, float, bool]:
    row = alert if isinstance(alert, dict) else {}
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
    base_move = float(
        row.get("ictBaseRelativeMovePct")
        or row.get("localBaseMovePct")
        or row.get("offLowMovePct")
        or getattr(event, "daily_move_pct", 0)
        or 0
    )
    peak_move = float(
        row.get("peakMovePct")
        or getattr(event, "peak_move_pct", 0)
        or 0
    )
    volume_awake = bool(
        row.get("volumeAwaken")
        or row.get("ictVolumeAwakening")
        or row.get("optionCvdBuying")
        or row.get("orderflowConfirmed")
    )
    if not volume_awake:
        vol_surge = float(
            getattr(event, "volume_surge", 0)
            or row.get("volumeSurge")
            or row.get("volume_surge")
            or 0
        )
        volume_awake = vol_surge >= 2.0
    return v3, v9, base_move, peak_move, volume_awake


def _pad_lane_turnaround_signal(
    alert: Optional[dict[str, Any]],
    readiness_reason: str = "",
) -> bool:
    from app.engines.building_ftv_gates import (
        BUILDING_READY_REASONS,
        PAD_LANE_READY_REASONS,
        pad_lane_ready_reason,
    )

    if pad_lane_ready_reason(alert=alert, readiness_reason=readiness_reason):
        return True
    if not isinstance(alert, dict):
        return False
    stamped = str(
        alert.get("ictBaseReadinessReason")
        or alert.get("readyReason")
        or readiness_reason
        or ""
    )
    if stamped in BUILDING_READY_REASONS:
        return True
    if stamped in PAD_LANE_READY_REASONS or stamped.startswith("v_rip_session_low"):
        return True
    if bool(alert.get("ictVRipReady") or alert.get("vRipReady")):
        return stamped.startswith("v_rip")
    return bool(
        alert.get("slowGrindSuddenLiftReady")
        or alert.get("ictSlowGrindSuddenLift")
        or alert.get("slowGrindArmedTroughReady")
        or alert.get("slowGrindConsolidationBaseReady")
        or alert.get("fastBullishLocalBaseReady")
        or alert.get("bullishLocalBaseActive")
        or alert.get("buildingLiftHelping")
        or alert.get("buildingRipReady")
        or alert.get("ictBuildingRipReady")
    )


def _pad_lane_elite_ftv_chart_signal(
    alert: Optional[dict[str, Any]],
    event: Any = None,
) -> bool:
    """ELITE/EXPLODING flat→vertical in the local-base entry window.

    Aug25 24200 CE: promoted ELITE while 5m chart stayed bearish and the v_rip stamp
    had cleared — chart_not_aligned + exec_premium_fading_at_execution until bypass.
    """
    settings = get_settings()
    if not bool(getattr(settings, "pad_lane_elite_ftv_chart_bypass_enabled", True)):
        return False
    row = alert if isinstance(alert, dict) else {}
    tier = str(row.get("tier") or getattr(event, "tier", "") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False
    score = float(
        row.get("explosionScore")
        or getattr(event, "explosion_score", 0)
        or 0
    )
    min_score = float(
        getattr(settings, "pad_lane_elite_ftv_chart_bypass_min_score", 45.0) or 45.0
    )
    if score < min_score:
        return False
    if not bool(row.get("ictFlatThenVertical") or row.get("ictBreakout")):
        return False
    base_rel = float(
        row.get("ictBaseRelativeMovePct")
        or row.get("localBaseMovePct")
        or row.get("offLowMovePct")
        or 0
    )
    if base_rel <= 0:
        return False
    from app.engines.local_base_chart_bypass import local_base_entry_window

    vol = float(
        row.get("volumeSurge")
        or getattr(event, "volume_surge", 0)
        or 0
    )
    entry_min, chase_max = local_base_entry_window(tier, vol)
    return entry_min <= base_rel <= chase_max


def _armed_base_launch_pad_chart_signal(
    alert: Optional[dict[str, Any]],
    event: Any = None,
) -> bool:
    """armed_base_launch + first lift + volume awaken in the 2–25% local pad window.

    Aug26 NIFTY PUT 24250/24300: EXPLODING armed_base_launch at ~22–24% lb was blocked
    chart_live_bullish_no_puts because v3 was still flat/negative pre-vertical.
    """
    settings = get_settings()
    if not bool(
        getattr(settings, "pad_lane_armed_base_launch_chart_bypass_enabled", True)
    ):
        return False
    row = alert if isinstance(alert, dict) else {}
    moment = str(row.get("momentType") or "").lower()
    armed = moment == "armed_base_launch" or bool(
        row.get("ictArmedBaseLaunch")
        or (event is not None and getattr(event, "armed_base_launch", False))
    )
    if not armed:
        return False
    tier = str(row.get("tier") or getattr(event, "tier", "") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False
    if not bool(row.get("ictFirstLift") or row.get("ictArmedBaseLaunch")):
        return False
    if not bool(row.get("ictFlatThenVertical") or row.get("ictBreakout")):
        return False
    if not bool(row.get("volumeAwaken") or row.get("ictVolumeAwakening")):
        return False
    base_rel = float(
        row.get("ictBaseRelativeMovePct")
        or row.get("localBaseMovePct")
        or row.get("offLowMovePct")
        or (getattr(event, "daily_move_pct", 0) if event is not None else 0)
        or 0
    )
    lo = float(getattr(settings, "ict_v_rip_pad_min_move_pct", 2.0) or 2.0)
    hi = float(getattr(settings, "ict_v_rip_max_move_pct", 25.0) or 25.0)
    return lo <= base_rel <= hi + 1e-6


def _first_lift_local_base_pad_chart_signal(
    alert: Optional[dict[str, Any]],
    event: Any = None,
) -> bool:
    """first_lift_local_base + volume awaken in the 2–25% local pad window.

    Aug26 SENSEX PUT 77800: ELITE first_lift at ~16% lb while session peak was ~53%
    — chart_live_bullish_no_puts survived because pad-lane peak cap used session peak.
    """
    settings = get_settings()
    if not bool(
        getattr(settings, "pad_lane_first_lift_local_base_chart_bypass_enabled", True)
    ):
        return False
    row = alert if isinstance(alert, dict) else {}
    moment = str(row.get("momentType") or "").lower()
    first_lift = moment == "first_lift_local_base" or bool(
        row.get("ictFirstLift")
        or (event is not None and getattr(event, "first_lift", False))
    )
    if not first_lift:
        return False
    tier = str(row.get("tier") or getattr(event, "tier", "") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False
    if not bool(row.get("ictFlatThenVertical") or row.get("ictBreakout")):
        return False
    if not bool(row.get("volumeAwaken") or row.get("ictVolumeAwakening")):
        return False
    base_rel = float(
        row.get("ictBaseRelativeMovePct")
        or row.get("localBaseMovePct")
        or row.get("offLowMovePct")
        or (getattr(event, "daily_move_pct", 0) if event is not None else 0)
        or 0
    )
    lo = float(getattr(settings, "ict_v_rip_pad_min_move_pct", 2.0) or 2.0)
    hi = float(getattr(settings, "ict_v_rip_max_move_pct", 25.0) or 25.0)
    return lo <= base_rel <= hi + 1e-6


def _pad_lane_peak_for_cap(
    base_move: float,
    peak_move: float,
    settings: Any,
) -> float:
    """When LTP is still at the local pad, session peak must not block chart bypass."""
    pad_lo = float(getattr(settings, "ict_v_rip_pad_min_move_pct", 2.0) or 2.0)
    pad_hi = float(getattr(settings, "ict_v_rip_max_move_pct", 25.0) or 25.0)
    if pad_lo <= base_move <= pad_hi + 1e-6:
        return min(float(peak_move or 0), float(base_move or 0))
    return float(peak_move or 0)


def pad_lane_turnaround_chart_bypass(
    side: Side | str,
    snap: Optional[SymbolSnapshot],
    *,
    event: Any = None,
    alert: Optional[dict[str, Any]] = None,
    readiness_reason: str = "",
) -> bool:
    """Bypass chart_live_bearish_no_calls for premium-led pad-lane turnarounds.

    The option can V-rip off session low before the 5m index chart flips. Uses a
    wider adverse index-momentum cap than local_base_structure_active while still
    rejecting extended chases and hard index dumps.
    """
    from app.engines.local_base_chart_bypass import session_chart_conflicts_side

    settings = get_settings()
    if not bool(getattr(settings, "pad_lane_chart_bypass_enabled", True)):
        return False
    if snap is None or not session_chart_conflicts_side(side, snap):
        return False
    elite_ftv = _pad_lane_elite_ftv_chart_signal(alert, event)
    armed_launch = _armed_base_launch_pad_chart_signal(alert, event)
    first_lift_pad = _first_lift_local_base_pad_chart_signal(alert, event)
    if (
        not _pad_lane_turnaround_signal(alert, readiness_reason)
        and not elite_ftv
        and not armed_launch
        and not first_lift_pad
    ):
        return False

    v3, v9, base_move, peak_move, volume_awake = _pad_lane_chart_metrics(
        event=event,
        alert=alert,
    )
    min_v3 = float(
        getattr(settings, "pad_lane_chart_bypass_min_velocity_3s", 0.5) or 0.5
    )
    awake_min_v3 = float(
        getattr(
            settings,
            "pad_lane_chart_bypass_volume_awaken_min_velocity_3s",
            0.2,
        )
        or 0.2
    )
    if elite_ftv or armed_launch or first_lift_pad:
        min_v3 = min(min_v3, awake_min_v3)
    min_v9 = float(
        getattr(settings, "pad_lane_chart_bypass_min_premium_velocity_9s", -0.3)
        or -0.3
    )
    ftv_direct = ftv_direct_trade_active(
        event=event,
        alert=alert,
        snap=snap,
        readiness_reason=readiness_reason,
        tier=str((alert or {}).get("tier") or getattr(event, "tier", "") or ""),
    )
    if armed_launch or first_lift_pad:
        row = alert if isinstance(alert, dict) else {}
        evidence = {
            "tier": row.get("tier") or getattr(event, "tier", ""),
            "localBaseMovePct": base_move,
            "flatThenVertical": bool(
                row.get("ictFlatThenVertical") or row.get("ictBreakout")
            ),
            "activeBreakout": bool(row.get("ictBreakout") or row.get("ictFirstLift")),
            "volumeAwaken": volume_awake,
            "firstLiftLocalBase": first_lift_pad,
        }
        velocity_ok = pad_lane_cold_velocity_ok(evidence, v3, v9)
    elif ftv_direct:
        evidence = _ftv_direct_evidence_from_alert(alert) if isinstance(alert, dict) else {}
        velocity_ok = pad_lane_cold_velocity_ok(evidence, v3, v9)
    else:
        velocity_ok = v3 >= min_v3 or (volume_awake and v3 >= awake_min_v3)
    if not velocity_ok or v9 < min_v9:
        return False

    max_off_low = float(
        getattr(settings, "pad_lane_chart_bypass_max_off_low_pct", 30.0) or 30.0
    )
    max_peak = float(
        getattr(settings, "pad_lane_chart_bypass_max_peak_move_pct", 38.0) or 38.0
    )
    if ftv_direct:
        max_off_low = max(
            max_off_low,
            float(
                getattr(settings, "ftv_direct_trade_max_off_low_pct", 35.0) or 35.0
            ),
        )
        max_peak = max(
            max_peak,
            float(
                getattr(settings, "ftv_direct_trade_max_peak_move_pct", 50.0) or 50.0
            ),
        )
    if elite_ftv or first_lift_pad:
        max_peak = max(
            max_peak,
            float(
                getattr(
                    settings,
                    "pad_lane_elite_ftv_chart_bypass_max_peak_move_pct",
                    45.0,
                )
                or 45.0
            ),
        )
    move = max(base_move, float((alert or {}).get("offLowMovePct") or 0))
    if move > max_off_low + 1e-6:
        return False
    peak_for_cap = _pad_lane_peak_for_cap(base_move, peak_move, settings)
    if peak_for_cap > max_peak + 1e-6:
        return False

    chart = getattr(snap, "spotChart", None)
    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0) if chart else 0.0
    max_adverse = float(
        getattr(
            settings,
            "pad_lane_chart_bypass_max_adverse_index_mom5_pct",
            0.25,
        )
        or 0.25
    )
    side_v = _side_val(side)
    if side_v == "CALL" and mom5 < -max_adverse:
        return False
    if side_v == "PUT" and mom5 > max_adverse:
        return False
    return True


def pad_lane_turnaround_chart_bypass_for_snap(
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    explosion_event: Any = None,
    alert: Optional[dict[str, Any]] = None,
    readiness_reason: str = "",
) -> bool:
    """Snap helper — also scans matching explosionAlerts when alert is absent."""
    if pad_lane_turnaround_chart_bypass(
        side,
        snap,
        event=explosion_event,
        alert=alert,
        readiness_reason=readiness_reason,
    ):
        return True
    side_v = _side_val(side)
    strike = float(getattr(explosion_event, "strike", 0) or 0) if explosion_event else 0.0
    for row in snap.explosionAlerts or []:
        if str(row.get("side") or "").upper() != side_v:
            continue
        if strike and abs(float(row.get("strike") or 0) - strike) > 0.1:
            continue
        rr = str(
            row.get("ictBaseReadinessReason")
            or row.get("readyReason")
            or readiness_reason
            or ""
        )
        if pad_lane_turnaround_chart_bypass(
            side,
            snap,
            event=explosion_event,
            alert=row,
            readiness_reason=rr,
        ):
            return True
    return False


_STRICT_PAD_CHART_BYPASS_REASONS = frozenset(
    {
        "armed_base_option_led_ready",
        "elite_base_ready_s_preauthorized",
        "building_rip_bullish_ready",
        "building_local_base_lift_ready",
        "v_rip_session_low_ready",
        "fast_bullish_local_base_ready",
        "slow_grind_sudden_lift_ready",
        "slow_grind_armed_trough_ready",
        "slow_grind_consolidation_base_ready",
        "squeeze_release_ready",
        "index_led_option_lag_ready",
        "stealth_cvd_coil_ready",
        "micro_pullback_retest_ready",
        "premium_fvg_pad_ready",
        "double_dip_vbase_ready",
        "early_radar_pad_ready",
    }
)


def resolve_strict_pad_lane_chart_bypass(
    candidate: Any,
    snap: SymbolSnapshot,
) -> tuple[bool, bool]:
    """Return (pad_lane_chart_bypass, strict_first_lift_bypass) for live chart gates.

    Aug26 SENSEX PUT 77600 v_rip_session_low: pad_lane bypass passed in isolation but
    auto_trader zeroed all counter-trend waivers and never passed strict_first_lift.
    """
    return resolve_strict_pad_lane_for_entry(
        candidate.side,
        snap,
        mode=str(getattr(candidate, "mode", "") or ""),
        explosion_event=getattr(candidate, "explosion_event", None),
        alert=(
            candidate.alert if isinstance(getattr(candidate, "alert", None), dict) else None
        ),
    )


def resolve_strict_pad_lane_for_entry(
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    mode: str = "",
    explosion_event: Any = None,
    alert: Optional[dict[str, Any]] = None,
) -> tuple[bool, bool]:
    """Strict pad-lane bypass from side/snap/alert — shared by auto_trader and live chart monitor."""
    row = alert if isinstance(alert, dict) else None
    side_obj = side if isinstance(side, Side) else Side(str(side).upper())
    pad_lane_chart_bypass = pad_lane_turnaround_chart_bypass_for_snap(
        side_obj,
        snap,
        explosion_event=explosion_event,
        alert=row,
    )
    armed_base_chart_bypass = False
    if (mode or "").lower() == "explosion" and explosion_event is not None:
        from app.engines.ict_breakout_monitor import first_lift_entry_readiness

        armed_ready, armed_reason = first_lift_entry_readiness(
            snap=snap,
            event=explosion_event,
            alert=row,
        )
        armed_base_chart_bypass = bool(
            armed_ready and armed_reason in _STRICT_PAD_CHART_BYPASS_REASONS
        )
    strict_bypass = armed_base_chart_bypass or pad_lane_chart_bypass
    return pad_lane_chart_bypass, strict_bypass



def pad_lane_expiry_worst_waive(evidence: Mapping[str, Any]) -> bool:
    """EXPIRY WORST quality/score floors may waive for stamped pad-lane local-base FTV."""
    settings = get_settings()
    if not bool(getattr(settings, "pad_lane_expiry_worst_waive_enabled", True)):
        return False
    return pad_lane_ftv_waives_allocation_rank_one(evidence)


def _ftv_direct_resolve(
    *,
    tier: Optional[str] = None,
    event: Any = None,
    candidate: Any = None,
    alert: Optional[dict] = None,
    snap: Any = None,
) -> tuple[Any, dict, Any, str, float, float]:
    """Return event, alert, snap, side, strike, premium."""
    resolved_event = event
    resolved_alert = alert if isinstance(alert, dict) else {}
    resolved_snap = snap
    side = ""
    strike = 0.0
    premium = 0.0

    if candidate is not None:
        if resolved_event is None:
            resolved_event = getattr(candidate, "explosion_event", None)
        if not resolved_alert:
            raw = getattr(candidate, "alert", None)
            resolved_alert = raw if isinstance(raw, dict) else {}
        if resolved_snap is None:
            resolved_snap = getattr(candidate, "snap", None)
        side = str(getattr(candidate, "side", "") or "").upper()
        try:
            strike = float(getattr(candidate, "strike", 0) or 0)
        except (TypeError, ValueError):
            strike = 0.0
        try:
            premium = float(getattr(candidate, "premium", 0) or 0)
        except (TypeError, ValueError):
            premium = 0.0

    if resolved_event is not None:
        if not side:
            side = str(
                getattr(getattr(resolved_event, "side", None), "value", resolved_event.side)
                or ""
            ).upper()
        if strike <= 0:
            try:
                strike = float(getattr(resolved_event, "strike", 0) or 0)
            except (TypeError, ValueError):
                strike = 0.0
        if premium <= 0:
            try:
                premium = float(getattr(resolved_event, "premium", 0) or 0)
            except (TypeError, ValueError):
                premium = 0.0

    if resolved_alert:
        if not side:
            side = str(resolved_alert.get("side") or "").upper()
        if strike <= 0:
            try:
                strike = float(resolved_alert.get("strike") or 0)
            except (TypeError, ValueError):
                strike = 0.0
        if premium <= 0:
            try:
                premium = float(resolved_alert.get("premium") or 0)
            except (TypeError, ValueError):
                premium = 0.0

    tier_u = str(
        tier
        or resolved_alert.get("tier")
        or getattr(resolved_event, "tier", "")
        or ""
    ).upper()
    return resolved_event, resolved_alert, resolved_snap, side, strike, premium, tier_u


def _ftv_direct_at_trough(readiness_reason: str) -> bool:
    """True when readiness is at the pad/trough — off-low % may still be near zero."""
    rr = str(readiness_reason or "")
    return rr in (
        "slow_grind_armed_trough_ready",
        "slow_grind_consolidation_base_ready",
        "building_local_base_lift_ready",
        "building_first_lift_ready",
        "building_first_lift_preauthorized",
    ) or rr.startswith("v_rip_session_low")


def _ftv_direct_evidence_from_alert(alert: dict[str, Any]) -> dict[str, Any]:
    return {
        "tier": str(alert.get("tier") or "").upper(),
        "vRipReady": bool(alert.get("vRipReady") or alert.get("ictVRipReady")),
        "earlyRadarPadCapture": bool(
            alert.get("earlyRadarPadCapture") or alert.get("ictEarlyRadarPadCapture")
        ),
        "slowGrindSuddenLift": bool(
            alert.get("slowGrindSuddenLift") or alert.get("ictSlowGrindSuddenLift")
        ),
        "stealthCvdCoil": bool(
            alert.get("stealthCvdCoil") or alert.get("ictStealthCvdCoil")
        ),
        "microPullbackRetest": bool(
            alert.get("microPullbackRetest") or alert.get("ictMicroPullbackRetest")
        ),
        "squeezeRelease": bool(
            alert.get("squeezeRelease") or alert.get("ictSqueezeRelease")
        ),
        "indexLedOptionLag": bool(
            alert.get("indexLedOptionLag") or alert.get("ictIndexLedOptionLag")
        ),
        "premiumFvgPad": bool(
            alert.get("premiumFvgPad") or alert.get("ictPremiumFvgPad")
        ),
        "doubleDipVbase": bool(
            alert.get("doubleDipVbase") or alert.get("ictDoubleDipVbase")
        ),
        "flatThenVertical": bool(
            alert.get("ictFlatThenVertical") or alert.get("ictBreakout")
        ),
        "activeBreakout": bool(alert.get("ictBreakout") or alert.get("activeBreakout")),
        "volumeAwaken": bool(
            alert.get("volumeAwaken") or alert.get("ictVolumeAwakening")
        ),
        "orderflowPositive": bool(
            alert.get("optionCvdBuying") or alert.get("orderflowConfirmed")
        ),
        "localBaseMovePct": float(
            alert.get("localBaseMovePct") or alert.get("ictBaseRelativeMovePct") or 0
        ),
        "offLowMovePct": float(alert.get("offLowMovePct") or 0),
        "velocity3s": float(alert.get("velocity3s") or alert.get("velocity_3s") or 0),
        "velocity9s": float(alert.get("velocity9s") or alert.get("velocity_9s") or 0),
        "midRipCoil": bool(alert.get("midRipCoil") or alert.get("ictMidRipCoil")),
    }


def ftv_direct_trade_active(
    *,
    tier: Optional[str] = None,
    event: Any = None,
    candidate: Any = None,
    alert: Optional[dict] = None,
    snap: Any = None,
    readiness_reason: str = "",
) -> bool:
    """True → stamped pad-lane / BUILDING FTV at base links directly to execution.

    Covers BUILDING/WATCH (and building-rip ELITE) when radar stamped pad readiness
    at the local base — bypass chart/timing/chase/worst-day via elite_never_block.
    Blocks extended chases (e.g. 77700 PE after ₹120→₹200 vertical).
    """
    settings = get_settings()
    if not bool(getattr(settings, "ftv_direct_trade_enabled", True)):
        return False

    resolved_event, resolved_alert, resolved_snap, side, strike, premium, tier_u = (
        _ftv_direct_resolve(
            tier=tier,
            event=event,
            candidate=candidate,
            alert=alert,
            snap=snap,
        )
    )
    if tier_u not in ("BUILDING", "WATCH", "ELITE", "EXPLODING"):
        return False

    if bool(resolved_alert.get("midRipCoil") or resolved_alert.get("ictMidRipCoil")):
        return False

    from app.engines.building_ftv_gates import (
        BUILDING_READY_REASONS,
        PAD_LANE_READY_REASONS,
        building_rip_ready_reason,
        pad_lane_ready_reason,
    )

    rr = pad_lane_ready_reason(
        alert=resolved_alert or None,
        readiness_reason=readiness_reason,
    )
    if not rr:
        rr = building_rip_ready_reason(
            alert=resolved_alert or None,
            readiness_reason=readiness_reason,
        )
    ftv_reasons = PAD_LANE_READY_REASONS | BUILDING_READY_REASONS
    has_signal = bool(rr and (rr in ftv_reasons or rr.startswith("v_rip_session_low")))
    if not has_signal:
        has_signal = _pad_lane_turnaround_signal(resolved_alert or None, readiness_reason)
    if not has_signal:
        return False

    off_low = max(
        float(resolved_alert.get("offLowMovePct") or 0),
        float(resolved_alert.get("localBaseMovePct") or 0),
        float(resolved_alert.get("ictBaseRelativeMovePct") or 0),
        float(getattr(resolved_event, "off_low_move_pct", 0) or 0),
        float(getattr(resolved_event, "ict_base_relative_move_pct", 0) or 0),
    )
    local_move = max(
        float(resolved_alert.get("localBaseMovePct") or 0),
        float(resolved_alert.get("ictBaseRelativeMovePct") or 0),
        float(getattr(resolved_event, "ict_base_relative_move_pct", 0) or 0),
    )
    peak_move = max(
        float(resolved_alert.get("peakMovePct") or 0),
        float(getattr(resolved_event, "peak_move_pct", 0) or 0),
    )

    max_off = float(
        getattr(settings, "ftv_direct_trade_max_off_low_pct", 35.0) or 35.0
    )
    max_local = float(
        getattr(settings, "ftv_direct_trade_max_local_move_pct", 45.0) or 45.0
    )
    max_peak = float(
        getattr(settings, "ftv_direct_trade_max_peak_move_pct", 50.0) or 50.0
    )
    min_off = float(
        getattr(settings, "ftv_direct_trade_min_off_low_pct", 2.0) or 2.0
    )
    if not _ftv_direct_at_trough(rr) and off_low < min_off - 1e-6:
        return False
    if off_low > max_off + 1e-6:
        return False
    if local_move > max_local + 1e-6:
        return False
    if peak_move > max_peak + 1e-6:
        return False

    min_prem = float(getattr(settings, "min_option_premium_inr", 18.0) or 18.0)
    if premium > 0 and premium < min_prem:
        return False

    if bool(getattr(settings, "ftv_direct_trade_require_atm_itm", True)):
        if strike > 0 and resolved_snap is not None:
            ok, _ = _atm_itm_ok(side=side, strike=strike, snap=resolved_snap)
            if not ok:
                return False

    return True


def stamp_ftv_direct_trade_on_alert(
    alert: dict[str, Any],
    *,
    snap: Any = None,
    readiness_reason: str = "",
) -> bool:
    """Stamp alert when FTV direct-trade path is active (selector / funnel telemetry)."""
    if not isinstance(alert, dict):
        return False
    active = ftv_direct_trade_active(
        alert=alert,
        snap=snap,
        readiness_reason=readiness_reason,
        tier=str(alert.get("tier") or ""),
    )
    if active:
        alert["ictFtvDirectTrade"] = True
        alert["ftvDirectTrade"] = True
    return active


def pad_lane_early_near_miss_waive(
    alert: Optional[Mapping[str, Any]],
    *,
    readiness_reason: str = "",
) -> bool:
    """Stamped pad-lane readiness waives ICT first-lift quality / tier-lag near-miss blockers.

    Aug25 24150 CE at 10:47: v_rip_session_low_ready was stamping while
    first_lift_entry_readiness still returned first_lift_quality<65 and tier was
    BUILDING — explosion_near_miss for 60–90s before ELITE/quality caught up.
    """
    settings = get_settings()
    if not bool(getattr(settings, "pad_lane_early_near_miss_waive_enabled", True)):
        return False
    from app.engines.building_ftv_gates import (
        PAD_LANE_READY_REASONS,
        pad_lane_ready_reason,
    )

    rr = pad_lane_ready_reason(
        alert=alert if isinstance(alert, dict) else None,
        readiness_reason=readiness_reason,
    )
    if rr in PAD_LANE_READY_REASONS or rr.startswith("v_rip_session_low"):
        return True
    return _pad_lane_turnaround_signal(
        alert if isinstance(alert, dict) else None,
        readiness_reason,
    )


def pad_lane_ftv_waives_allocation_rank_one(
    evidence: Mapping[str, Any],
) -> bool:
    """Pad-lane local-base captures may authorize on rank 2+ FTV sleeves.

    The V-rip / slow-grind moment is contract-specific — waiting for the global
    rank-1 slot means missing the lift while another leg holds the sleeve.
    """
    settings = get_settings()
    if not bool(getattr(settings, "pad_lane_ftv_waives_allocation_rank_one", True)):
        return False
    max_off = float(
        getattr(settings, "pad_lane_chart_bypass_max_off_low_pct", 30.0) or 30.0
    )
    off_low = max(
        float(evidence.get("offLowMovePct") or 0),
        float(evidence.get("localBaseMovePct") or 0),
        float(evidence.get("ictBaseRelativeMovePct") or 0),
    )
    if off_low > max_off + 1e-6:
        return False
    if pad_lane_pre_lift(evidence):
        return True
    if bool(evidence.get("vRipReady") or evidence.get("earlyRadarPadCapture")):
        return True
    if bool(
        evidence.get("ictVRipReady")
        or evidence.get("ictEarlyRadarPadCapture")
        or evidence.get("ictSlowGrindSuddenLift")
    ):
        return True
    if bool(evidence.get("firstLift") or evidence.get("buildingRipReady")):
        return off_low >= 2.0
    return False


def extended_pad_lane_readiness(
    *,
    snap: Optional[SymbolSnapshot],
    event: Any = None,
    ict: Any = None,
    alert: Optional[dict[str, Any]] = None,
    settings: Any = None,
) -> tuple[bool, str]:
    """Run extended pre-lift pad lanes (squeeze, index lag, CVD, pullback, FVG)."""
    s = settings or get_settings()
    row = alert if isinstance(alert, dict) else {}
    checks = (
        double_dip_vbase_readiness,
        squeeze_release_readiness,
        premium_fvg_pad_readiness,
        index_led_option_lag_readiness,
        stealth_cvd_coil_readiness,
        micro_pullback_retest_readiness,
    )
    for fn in checks:
        ok, reason = fn(
            snap=snap,
            event=event,
            ict=ict,
            alert=row,
            settings=s,
        )
        if ok:
            return True, reason
    return False, ""
