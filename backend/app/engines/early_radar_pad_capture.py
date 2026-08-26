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


def early_radar_pad_off_low_pct(alert: Mapping[str, Any]) -> float:
    if "offLowMovePct" in alert:
        return max(0.0, _number(alert.get("offLowMovePct")))
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
    if not _atm_itm_ok(side=side, strike=strike, snap=snap):
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
