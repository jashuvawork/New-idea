"""Early radar pad capture — take FTV / V / ELITE / EXPLODING at the session trough.

When radar surfaces a top moment near the session low (e.g. ₹33 before a lift to ₹48),
authorize tradeable status, chart bypass, FTV policy, and max lots even while the 5m
chart is still bearish/bullish against the option side.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import get_settings
from app.engines.premium_filter import premium_in_band
from app.models.schemas import Side, SymbolSnapshot

EARLY_RADAR_PAD_READY = "early_radar_pad_ready"
BUILDING_COIL_PAD_READY = "building_coil_pad_ready"
BUILDING_COIL_PAD_ARMED = "building_coil_pad_armed"
BUILDING_COIL_PAD_UNCONFIRMED = "building_coil_pad_unconfirmed"


def _enrich_row_from_event(
    row: dict[str, Any],
    event: Any = None,
) -> dict[str, Any]:
    merged = dict(row)
    if event is None:
        return merged
    for key, attr in (
        ("premium", "premium"),
        ("strike", "strike"),
        ("side", "side"),
        ("tier", "tier"),
        ("velocity3s", "velocity_3s"),
        ("velocity9s", "velocity_9s"),
        ("peakMovePct", "peak_move_pct"),
        ("dailyMovePct", "daily_move_pct"),
    ):
        if merged.get(key) in (None, "", 0):
            value = getattr(event, attr, None)
            if hasattr(value, "value"):
                value = value.value
            if value not in (None, "", 0):
                merged[key] = value
    return merged


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def ict_base_armed_prelaunch_pad_lane(
    alert: Mapping[str, Any],
    settings: Any = None,
) -> bool:
    """ELITE/EXPLODING ict_base_armed at local pad before armed_base_launch stamps."""
    s = settings or get_settings()
    if bool(
        alert.get("ictArmedBaseLaunch")
        or alert.get("armedBaseLaunch")
        or alert.get("ictFirstLift")
        or alert.get("ictEliteBaseReady")
    ):
        return False
    tier = _alert_tier(alert)
    if tier not in ("ELITE", "EXPLODING"):
        return False
    if not bool(alert.get("ictBaseArmed") or alert.get("baseArmed")):
        return False
    armed_samples = int(alert.get("ictArmedBaseSamples") or 0)
    min_samples = int(getattr(s, "ict_armed_base_min_samples", 6) or 6)
    if armed_samples < min_samples:
        return False
    local_move = _alert_local_base_move(alert)
    pad_min = float(getattr(s, "ict_v_rip_pad_min_move_pct", 2.0) or 2.0)
    pad_max = float(getattr(s, "early_radar_pad_max_local_move_pct", 20.0) or 20.0)
    if not (pad_min <= local_move <= pad_max + 1e-6):
        return False
    min_score = float(
        getattr(s, "early_radar_pad_exploding_prelaunch_min_score", 25.0) or 25.0
    )
    return _alert_explosion_score(alert) >= min_score


def early_radar_pad_off_low_pct(alert: Mapping[str, Any]) -> float:
    if "offLowMovePct" in alert:
        return max(0.0, _number(alert.get("offLowMovePct")))
    # Aug28 SENSEX PUT 77500: session peakMovePct inflated off-low and disabled pad
    # capture at 5.4% local base while ict_base_armed samples were full.
    if ict_base_armed_prelaunch_pad_lane(alert):
        return max(0.0, _alert_local_base_move(alert))
    # Minimal/test alerts omit off-low — infer distance from session trough.
    return max(
        0.0,
        _number(alert.get("peakMovePct")),
        _number(alert.get("dailyMovePct")),
        _alert_local_base_move(alert),
    )


def _alert_tier(alert: Mapping[str, Any]) -> str:
    return str(alert.get("tier") or "").upper()


def _alert_explosion_score(alert: Mapping[str, Any]) -> float:
    return _number(alert.get("explosionScore") or alert.get("score"))


def _alert_local_base_move(alert: Mapping[str, Any]) -> float:
    return max(
        _number(alert.get("localBaseMovePct")),
        _number(alert.get("ictBaseRelativeMovePct")),
    )


def _cold_trough_coil_signal(alert: Mapping[str, Any]) -> bool:
    """Coil / armed-base proof at session trough — velocity may still be zero."""
    if bool(
        alert.get("ictBaseArmed")
        or alert.get("baseArmed")
        or alert.get("ictVRipReady")
        or alert.get("vRipReady")
    ):
        return True
    if bool(
        alert.get("volumeAwaken")
        or alert.get("ictVolumeAwakening")
        or alert.get("volumeAwakening")
    ):
        return True
    if bool(
        alert.get("buildingLiftHelping")
        or alert.get("buildingRipHelpersOk")
        or alert.get("buildingRipReady")
        or alert.get("ictBuildingRipReady")
    ):
        return True
    if bool(alert.get("ictFlatThenVertical") or alert.get("flatThenVertical")):
        return True
    rsi = _number(alert.get("rsi") or alert.get("optionRsi"))
    side = str(alert.get("side") or "").upper()
    if side == "CALL" and 0 < rsi <= 45.0:
        return True
    if side == "PUT" and rsi >= 55.0:
        return True
    macd_hist = _number(alert.get("macdHistogram"))
    if side == "CALL" and macd_hist > -0.05:
        return True
    if side == "PUT" and macd_hist < 0.05:
        return True
    return False


def _building_coil_pad_shape(alert: Mapping[str, Any], settings: Any = None) -> bool:
    """Quiet local-base coil window (10–25%) — tier-agnostic for promotion checks."""
    s = settings or get_settings()
    if not bool(getattr(s, "building_coil_pad_entry_enabled", True)):
        return False
    if bool(alert.get("ictMidRipCoil") or alert.get("midRipCoil")):
        return False

    min_local = float(
        getattr(s, "building_coil_pad_min_local_move_pct", 10.0) or 10.0
    )
    max_local = float(
        getattr(s, "building_coil_pad_max_local_move_pct", 25.0) or 25.0
    )
    local_move = _alert_local_base_move(alert)
    if local_move <= 0 or not (min_local <= local_move <= max_local + 1e-6):
        return False

    max_score = float(
        getattr(s, "building_coil_pad_max_explosion_score", 65.0) or 65.0
    )
    tier = _alert_tier(alert)
    if tier not in ("ELITE", "EXPLODING"):
        if _alert_explosion_score(alert) > max_score + 1e-6:
            return False

    if not _cold_trough_coil_signal(alert):
        return False
    return True


def building_coil_pad_lift_signal(alert: Mapping[str, Any], settings: Any = None) -> bool:
    """BUILDING armed coil at 10–25% local base — matches EOD hindsight entry window.

    Aug28 NIFTY PUT 24050 @ 11:12: BUILDING, baseRel 20.7%, v3=0, +₹78k hindsight sim.
    """
    return _alert_tier(alert) == "BUILDING" and _building_coil_pad_shape(alert, settings)


def building_coil_pad_lane_active(alert: Mapping[str, Any], settings: Any = None) -> bool:
    """Coil-pad lane — quiet BUILDING base, promoted coil with arm stamp, or fresh ELITE chase."""
    s = settings or get_settings()
    if bool(alert.get("ictArmedBaseLaunch")):
        return False
    if not _building_coil_pad_shape(alert, s):
        return False
    tier = _alert_tier(alert)
    if tier == "BUILDING":
        return True
    if tier in ("ELITE", "EXPLODING"):
        if bool(alert.get("buildingCoilPadArmed")):
            return True
        # first-lift / armed-base lanes own confirmed expansion off the pad.
        if bool(alert.get("ictFirstLift")):
            return False
        return True
    return bool(alert.get("buildingCoilPadArmed"))


def building_coil_pad_live_blocked(
    alert: Mapping[str, Any], settings: Any = None,
) -> tuple[bool, str]:
    """Block live entry when coil base is armed but expansion is not confirmed."""
    s = settings or get_settings()
    if not building_coil_pad_lane_active(alert, s):
        return False, ""
    if building_coil_pad_lift_confirmed(alert, s):
        return False, ""
    return True, BUILDING_COIL_PAD_UNCONFIRMED


def building_coil_pad_lift_confirmed(
    alert: Mapping[str, Any], settings: Any = None,
) -> bool:
    """Live entry requires lift confirmation — armed coil alone is watch-only."""
    s = settings or get_settings()
    if not bool(getattr(s, "building_coil_pad_confirm_entry_enabled", True)):
        return True
    if not building_coil_pad_lane_active(alert, s):
        return False

    v3 = _number(alert.get("velocity3s"))
    v9 = _number(alert.get("velocity9s"))
    min_v3 = float(
        getattr(s, "building_coil_pad_confirm_min_velocity_3s", 0.5) or 0.5
    )
    min_v9 = float(
        getattr(s, "building_coil_pad_confirm_min_velocity_9s", 0.25) or 0.25
    )
    if v3 >= min_v3 or v9 >= min_v9:
        return True

    flat_vert = bool(
        alert.get("ictFlatThenVertical") or alert.get("flatThenVertical")
    )
    breakout = bool(alert.get("ictBreakout") or alert.get("activeBreakout"))
    vol_awake = bool(
        alert.get("volumeAwaken")
        or alert.get("ictVolumeAwakening")
        or alert.get("volumeAwakening")
    )
    vol_surge = _number(alert.get("volumeSurge"))
    min_surge = float(
        getattr(s, "building_coil_pad_confirm_min_volume_surge", 1.2) or 1.2
    )
    if bool(getattr(s, "building_coil_pad_confirm_allow_flat_vertical", True)):
        if flat_vert and breakout and (vol_awake or vol_surge >= min_surge):
            return True
        # Flat coil with heat but breakout stamp lagging on quiet polls.
        if flat_vert and (vol_awake or vol_surge >= min_surge):
            local_move = _number(
                alert.get("ictBaseRelativeMovePct") or alert.get("localBaseMovePct")
            )
            pad_lo = float(
                getattr(s, "building_coil_pad_min_local_move_pct", 10.0) or 10.0
            )
            pad_hi = float(
                getattr(s, "building_coil_pad_max_local_move_pct", 25.0) or 25.0
            )
            if pad_lo <= local_move <= pad_hi + 1e-6:
                return True

    if bool(getattr(s, "building_coil_pad_confirm_armed_volume_ok", True)):
        if bool(alert.get("ictBaseArmed")) and not bool(alert.get("ictArmedBaseLaunch")):
            local_move = _number(
                alert.get("ictBaseRelativeMovePct") or alert.get("localBaseMovePct")
            )
            pad_lo = float(
                getattr(s, "building_coil_pad_min_local_move_pct", 10.0) or 10.0
            )
            pad_hi = float(
                getattr(s, "building_coil_pad_max_local_move_pct", 25.0) or 25.0
            )
            if (
                pad_lo <= local_move <= pad_hi + 1e-6
                and (vol_awake or vol_surge >= min_surge)
            ):
                return True

    if bool(
        alert.get("indexHelpersConfirm")
        or alert.get("indexTickSpike")
        or alert.get("indexTickAlign")
    ):
        if v3 > 0 or v9 > 0:
            return True

    return False


def building_coil_pad_structure(alert: Mapping[str, Any], settings: Any = None) -> bool:
    if bool(alert.get("buildingCoilPadReady")):
        return True
    return building_coil_pad_lane_active(alert, settings)


def stamp_building_coil_pad(alert: dict[str, Any], settings: Any = None) -> bool:
    if not isinstance(alert, dict):
        return False
    s = settings or get_settings()
    if not building_coil_pad_lane_active(alert, s):
        alert.pop("buildingCoilPad", None)
        alert.pop("buildingCoilPadArmed", None)
        alert.pop("buildingCoilPadReady", None)
        return False
    if building_coil_pad_lift_signal(alert, s) or bool(alert.get("buildingCoilPadArmed")):
        alert["buildingCoilPadArmed"] = True
    if not building_coil_pad_lift_confirmed(alert, s):
        alert.pop("buildingCoilPad", None)
        alert.pop("buildingCoilPadReady", None)
        if str(alert.get("ictBaseReadinessReason") or "") == BUILDING_COIL_PAD_READY:
            alert.pop("ictBaseReadinessReason", None)
        return False
    alert["buildingCoilPad"] = True
    alert["buildingCoilPadReady"] = True
    if str(alert.get("ictBaseReadinessReason") or "") != BUILDING_COIL_PAD_READY:
        alert.setdefault("ictBaseReadinessReason", BUILDING_COIL_PAD_READY)
    return True


def building_coil_pad_moneyness_ok(
    alert: Mapping[str, Any],
    snap: Optional[SymbolSnapshot],
    settings: Any = None,
) -> bool:
    """Expansion strikes may sit 2–3 steps OTM during BUILDING coil pad (Aug28 24050)."""
    s = settings or get_settings()
    side = str(alert.get("side") or "").upper()
    strike = _number(alert.get("strike"))
    if _atm_itm_ok(side=side, strike=strike, snap=snap):
        return True
    if early_radar_pad_shallow_otm_ok(alert, snap):
        return True
    if snap is None or side not in ("CALL", "PUT") or strike <= 0:
        return False
    spot = _number(getattr(snap, "spot", 0))
    atm = _number(getattr(snap, "atmStrike", 0)) or spot
    symbol = str(getattr(snap, "symbol", "") or alert.get("symbol") or "")
    if spot <= 0:
        return False
    from app.engines.moneyness import classify_moneyness, _depth_steps

    money = classify_moneyness(
        Side(side), strike, spot, symbol=symbol, atm=atm if atm > 0 else None,
    )
    if money != "OTM":
        return True
    max_steps = int(getattr(s, "building_coil_pad_max_otm_steps", 4) or 4)
    depth = _depth_steps(Side(side), strike, spot, symbol, atm)
    return depth <= max_steps


def building_coil_pad_entry_readiness(
    *,
    snap: Optional[SymbolSnapshot] = None,
    alert: Optional[dict[str, Any]] = None,
    settings: Any = None,
) -> tuple[bool, str]:
    row = alert if isinstance(alert, dict) else {}
    s = settings or get_settings()
    if not building_coil_pad_lane_active(row, s):
        return False, ""
    if isinstance(alert, dict):
        stamp_building_coil_pad(alert, s)
    if not building_coil_pad_lift_confirmed(row, s):
        return False, BUILDING_COIL_PAD_UNCONFIRMED
    if not building_coil_pad_moneyness_ok(row, snap, s):
        return False, "building_coil_pad_moneyness_blocked"
    premium = _number(row.get("premium"))
    peak_move = _number(row.get("peakMovePct"))
    if not premium_in_band(
        premium,
        mode="explosion",
        peak_move_pct=peak_move,
        snap=snap,
    ):
        return False, "building_coil_pad_premium_out_of_band"
    return True, BUILDING_COIL_PAD_READY


def alert_has_building_coil_pad(alert: Mapping[str, Any]) -> bool:
    """True only when coil pad is confirmed for live entry (not watch/armed)."""
    if not isinstance(alert, Mapping):
        return False
    return bool(alert.get("buildingCoilPadReady"))


def alert_has_building_coil_pad_armed(alert: Mapping[str, Any]) -> bool:
    return bool(alert.get("buildingCoilPadArmed"))


def cold_trough_pad_lift_signal(alert: Mapping[str, Any], settings: Any = None) -> bool:
    """WATCH/BUILDING at session trough — enter before v3 lifts (cold velocity OK)."""
    s = settings or get_settings()
    if not bool(getattr(s, "cold_trough_pad_entry_enabled", True)):
        return False
    tier = _alert_tier(alert)
    if tier not in ("WATCH", "BUILDING"):
        return False

    max_off = float(getattr(s, "cold_trough_pad_max_off_low_pct", 5.0) or 5.0)
    off_low = early_radar_pad_off_low_pct(alert)
    if off_low > max_off + 1e-6:
        return False

    max_local = float(getattr(s, "cold_trough_pad_max_local_move_pct", 8.0) or 8.0)
    local_move = _alert_local_base_move(alert)
    if local_move > max_local + 1e-6:
        return False

    max_score = float(getattr(s, "cold_trough_pad_max_explosion_score", 35.0) or 35.0)
    if _alert_explosion_score(alert) > max_score + 1e-6:
        return False

    if bool(alert.get("ictBaseArmed") or alert.get("baseArmed")):
        armed_samples = int(alert.get("ictArmedBaseSamples") or 0)
        min_samples = int(getattr(s, "ict_armed_base_min_samples", 6) or 6)
        if armed_samples >= min_samples and not bool(alert.get("ictArmedBaseLaunch")):
            min_trough = float(
                getattr(s, "cold_trough_armed_min_local_move_pct", 2.0) or 2.0
            )
            # Base coil armed-only (Aug17) — wait for launch; session trough lift OK.
            if local_move < min_trough - 1e-6:
                return False
            v3 = _number(alert.get("velocity3s"))
            v9 = _number(alert.get("velocity9s"))
            max_v3 = float(
                getattr(s, "cold_trough_pad_max_velocity_3s", 0.05) or 0.05
            )
            max_v9 = float(
                getattr(s, "cold_trough_pad_max_velocity_9s", 0.05) or 0.05
            )
            # Ramping premium off armed base — wait for armed_base_launch, not cold pad.
            if v3 > max_v3 + 1e-6 or v9 > max_v9 + 1e-6:
                return False

    if not _cold_trough_coil_signal(alert):
        return False
    return True


def watch_local_base_pad_lift_signal(alert: Mapping[str, Any], settings: Any = None) -> bool:
    """True when WATCH shows an early lift off session/local base without ELITE heat."""
    s = settings or get_settings()
    if not bool(getattr(s, "watch_local_base_pad_entry_enabled", True)):
        return False
    if _alert_tier(alert) != "WATCH":
        return False

    max_off = float(
        getattr(s, "watch_local_base_pad_max_off_low_pct", 18.0) or 18.0
    )
    if early_radar_pad_off_low_pct(alert) > max_off + 1e-6:
        return False

    max_score = float(
        getattr(s, "watch_local_base_pad_max_explosion_score", 35.0) or 35.0
    )
    if _alert_explosion_score(alert) > max_score + 1e-6:
        return False

    max_local = float(
        getattr(s, "watch_local_base_pad_max_local_move_pct", 15.0) or 15.0
    )
    local_move = _alert_local_base_move(alert)
    if local_move > max_local + 1e-6:
        return False

    min_v3 = float(
        getattr(s, "watch_local_base_pad_min_velocity_3s", 0.05) or 0.05
    )
    min_v9 = float(
        getattr(s, "watch_local_base_pad_min_velocity_9s", 0.03) or 0.03
    )
    v3 = _number(alert.get("velocity3s"))
    v9 = _number(alert.get("velocity9s"))

    if bool(alert.get("ictBaseArmed") or alert.get("baseArmed")):
        armed_samples = int(alert.get("ictArmedBaseSamples") or 0)
        min_samples = int(getattr(s, "ict_armed_base_min_samples", 6) or 6)
        if armed_samples >= min_samples and not bool(alert.get("ictArmedBaseLaunch")):
            return False
        return True
    if bool(
        alert.get("volumeAwaken")
        or alert.get("ictVolumeAwakening")
        or alert.get("volumeAwakening")
    ):
        return True
    if v3 >= min_v3 or v9 >= min_v9:
        return True
    if bool(
        alert.get("buildingLiftHelping")
        or alert.get("buildingRipHelpersOk")
        or alert.get("buildingRipReady")
        or alert.get("ictBuildingRipReady")
    ):
        return True
    if local_move > 0 and (v3 > 0 or v9 > 0):
        return True
    return False


def watch_local_base_pad_structure(alert: Mapping[str, Any], settings: Any = None) -> bool:
    """WATCH at session/local trough with early lift — trade before tier promotion."""
    if bool(alert.get("earlyRadarPadCapture") or alert.get("ictEarlyRadarPadCapture")):
        return True
    if cold_trough_pad_lift_signal(alert, settings):
        return True
    if alert_has_building_coil_pad(alert):
        return True
    return watch_local_base_pad_lift_signal(alert, settings)


def early_radar_pad_top_structure(alert: Mapping[str, Any]) -> bool:
    """True when radar shows FTV / V / ELITE / EXPLODING shape at the pad."""
    if bool(alert.get("earlyRadarPadCapture") or alert.get("ictEarlyRadarPadCapture")):
        return True

    tier = _alert_tier(alert)
    settings = get_settings()

    if watch_local_base_pad_structure(alert, settings):
        return True

    if tier == "WATCH" and bool(alert.get("ictFlatThenVertical")):
        if bool(
            alert.get("volumeAwaken")
            or alert.get("ictVolumeAwakening")
            or alert.get("ictBreakout")
        ):
            return True

    if tier in ("ELITE", "EXPLODING"):
        return True

    if alert_has_building_coil_pad(alert):
        return True

    if bool(alert.get("ictVRipReady")):
        return True
    if bool(alert.get("ictBuildingRipReady")):
        return True
    if bool(alert.get("ictFlatThenVertical") and alert.get("ictBreakout")):
        return True

    pad_flags = (
        "doubleDipVbaseReady",
        "slowGrindSuddenLiftReady",
        "fastBullishLocalBaseReady",
        "squeezeReleaseReady",
        "indexLedOptionLagReady",
        "stealthCvdCoilReady",
        "microPullbackRetestReady",
        "premiumFvgPadReady",
    )
    if any(bool(alert.get(flag)) for flag in pad_flags):
        return True

    vol_awake = bool(
        alert.get("volumeAwaken")
        or alert.get("ictVolumeAwakening")
    )
    return tier == "BUILDING" and vol_awake and bool(alert.get("ictBreakout"))


def _atm_itm_ok(
    *,
    side: str,
    strike: float,
    snap: Optional[SymbolSnapshot],
) -> bool:
    if snap is None or side not in ("CALL", "PUT") or strike <= 0:
        return True
    spot = _number(getattr(snap, "spot", 0))
    if spot <= 0:
        return True
    from app.engines.moneyness import classify_moneyness

    atm = _number(getattr(snap, "atmStrike", 0))
    money = classify_moneyness(
        Side(side),
        strike,
        spot,
        symbol=str(getattr(snap, "symbol", "") or ""),
        atm=atm if atm > 0 else None,
    )
    return money in ("ATM", "ITM")


def early_radar_pad_shallow_otm_ok(
    alert: Mapping[str, Any],
    snap: Optional[SymbolSnapshot],
) -> bool:
    """One-step shallow OTM may pad-capture when tier/score prove a base lift."""
    settings = get_settings()
    if snap is None:
        return False
    side = str(alert.get("side") or "").upper()
    strike = _number(alert.get("strike"))
    spot = _number(getattr(snap, "spot", 0))
    atm = _number(getattr(snap, "atmStrike", 0)) or spot
    symbol = str(getattr(snap, "symbol", "") or "")
    if side not in ("CALL", "PUT") or strike <= 0 or spot <= 0:
        return False
    from app.engines.moneyness import classify_moneyness, _depth_steps

    money = classify_moneyness(
        Side(side), strike, spot, symbol=symbol, atm=atm if atm > 0 else None,
    )
    if money != "OTM":
        return True
    max_steps = int(getattr(settings, "explosion_shallow_otm_history_steps", 1) or 1)
    depth = _depth_steps(Side(side), strike, spot, symbol, atm)
    return depth <= max_steps


def early_radar_pad_capture_active(
    alert: Mapping[str, Any],
    snap: Optional[SymbolSnapshot] = None,
) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "early_radar_pad_capture_enabled", True)):
        return False
    if bool(alert.get("ictMidRipCoil") or alert.get("midRipCoil")):
        return False

    # Session-trough pad only — elite/armed paths keep their own strict proofs.
    if bool(
        alert.get("ictArmedBaseLaunch")
        or alert.get("ictEliteBaseReady")
        or alert.get("ictFirstLift")
    ):
        return False

    armed_samples = int(alert.get("ictArmedBaseSamples") or 0)
    min_samples = int(getattr(settings, "ict_armed_base_min_samples", 6) or 6)
    if armed_samples >= min_samples and not bool(alert.get("ictArmedBaseLaunch")):
        # Aug27 SENSEX PUT 77300: EXPLODING at ~10% local base while ict_base_armed
        # samples were full but armed_base_launch had not stamped — pad capture was
        # disabled and first_lift_score<40 blocked the entry for a +40% runner.
        tier = _alert_tier(alert)
        local_move = _alert_local_base_move(alert)
        pad_max = float(
            getattr(settings, "early_radar_pad_max_local_move_pct", 20.0) or 20.0
        )
        min_score = float(
            getattr(
                settings,
                "early_radar_pad_exploding_prelaunch_min_score",
                25.0,
            )
            or 25.0
        )
        if not (
            tier in ("EXPLODING", "ELITE")
            and bool(alert.get("ictBaseArmed") or alert.get("baseArmed"))
            and local_move <= pad_max + 1e-6
            and _alert_explosion_score(alert) >= min_score
        ) and not cold_trough_pad_lift_signal(alert, settings):
            return False

    premium = _number(alert.get("premium"))
    peak_move = _number(alert.get("peakMovePct"))
    if not premium_in_band(
        premium,
        mode="explosion",
        peak_move_pct=peak_move,
        snap=snap,
    ):
        return False

    max_off = float(
        getattr(settings, "early_radar_pad_max_off_low_pct", 15.0) or 15.0
    )
    if early_radar_pad_off_low_pct(alert) > max_off + 1e-6:
        return False

    if not early_radar_pad_top_structure(alert):
        return False

    local_move = max(
        _number(alert.get("localBaseMovePct")),
        _number(alert.get("ictBaseRelativeMovePct")),
    )
    max_local = float(
        getattr(settings, "early_radar_pad_max_local_move_pct", 20.0) or 20.0
    )
    if local_move > max_local + 1e-6 and not bool(alert.get("ictVRipReady")):
        return False

    side = str(alert.get("side") or "").upper()
    strike = _number(alert.get("strike"))
    if not _atm_itm_ok(side=side, strike=strike, snap=snap) and not early_radar_pad_shallow_otm_ok(
        alert, snap,
    ):
        return False
    return True


def stamp_early_radar_pad_capture(
    alert: dict[str, Any],
    snap: Optional[SymbolSnapshot] = None,
) -> bool:
    """Stamp alert when early pad capture is active; return whether stamped."""
    if not isinstance(alert, dict):
        return False
    if early_radar_pad_capture_active(alert, snap):
        alert["earlyRadarPadCapture"] = True
        alert["ictEarlyRadarPadCapture"] = True
        if cold_trough_pad_lift_signal(alert):
            alert["coldTroughPad"] = True
        alert.setdefault("ictBaseReadinessReason", EARLY_RADAR_PAD_READY)
        return True
    alert.pop("earlyRadarPadCapture", None)
    alert.pop("ictEarlyRadarPadCapture", None)
    return False


def early_radar_pad_entry_readiness(
    *,
    snap: Optional[SymbolSnapshot],
    event: Any = None,
    ict: Any = None,
    alert: Optional[dict[str, Any]] = None,
    settings: Any = None,
) -> tuple[bool, str]:
    row = _enrich_row_from_event(alert if isinstance(alert, dict) else {}, event)
    if stamp_early_radar_pad_capture(row, snap):
        if isinstance(alert, dict):
            alert.update(
                {
                    key: row[key]
                    for key in ("earlyRadarPadCapture", "ictEarlyRadarPadCapture", "ictBaseReadinessReason")
                    if key in row
                }
            )
        return True, EARLY_RADAR_PAD_READY
    if early_radar_pad_capture_active(row, snap):
        if isinstance(alert, dict):
            alert["earlyRadarPadCapture"] = True
            alert["ictEarlyRadarPadCapture"] = True
        return True, EARLY_RADAR_PAD_READY
    return False, ""


def alert_has_early_radar_pad_capture(alert: Mapping[str, Any]) -> bool:
    return bool(
        alert.get("earlyRadarPadCapture")
        or alert.get("ictEarlyRadarPadCapture")
    )


def early_pad_score_floor(settings: Any = None) -> float:
    s = settings or get_settings()
    return float(getattr(s, "early_pad_min_explosion_score", 12.0) or 12.0)


def early_pad_quality_floor(settings: Any = None) -> float:
    s = settings or get_settings()
    return float(getattr(s, "early_pad_min_quality", 45.0) or 45.0)


def early_pad_context_active(
    row: Mapping[str, Any],
    *,
    local_base_move_pct: float | None = None,
    settings: Any = None,
) -> bool:
    """True when the contract is still at the session/local trough pad."""
    s = settings or get_settings()
    if bool(row.get("earlyRadarPadCapture") or row.get("ictEarlyRadarPadCapture")):
        return True
    lb = local_base_move_pct
    if lb is None:
        lb = max(
            _number(row.get("localBaseMovePct")),
            _number(row.get("ictBaseRelativeMovePct")),
        )
    off_low = early_radar_pad_off_low_pct(row)
    max_off = float(
        getattr(s, "watch_local_base_pad_max_off_low_pct", 18.0) or 18.0
    )
    max_lb = float(
        getattr(s, "early_radar_pad_max_local_move_pct", 20.0) or 20.0
    )
    tier = _alert_tier(row)
    if tier in ("WATCH", "BUILDING") and off_low <= max_off + 1e-6:
        return True
    if 2.0 <= lb <= max_lb + 1e-6:
        return True
    return watch_local_base_pad_lift_signal(row, s)
