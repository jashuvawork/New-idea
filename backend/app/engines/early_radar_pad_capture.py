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
    return max(0.0, _number(alert.get("offLowMovePct")))


def early_radar_pad_top_structure(alert: Mapping[str, Any]) -> bool:
    """True when radar shows FTV / V / ELITE / EXPLODING shape at the pad."""
    if bool(alert.get("earlyRadarPadCapture") or alert.get("ictEarlyRadarPadCapture")):
        return True

    tier = str(alert.get("tier") or "").upper()

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
