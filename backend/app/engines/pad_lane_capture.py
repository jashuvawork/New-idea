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
    return False


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
