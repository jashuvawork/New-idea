"""Expiry fast vertical burst — detect live mid-rip before post-peak radar.

Sep15 NIFTY 23350 PE: ₹20→₹53 vertical ~09:55–10:15 missed because trough-first-tick
caps off-low at 18% and cold-trough pad at 5%; radar first saw the contract at 10:30 @ ₹57.

Uses recent premium run (local window) so detection fires while premium is still climbing
off the launch pad, not after chain day-high is printed. CE/PE symmetric (PUT off window
low, CALL off window high).
"""

from __future__ import annotations

from collections import deque
from typing import Any, Mapping, Optional

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot


def projected_premium_run(
    run: Mapping[str, float],
    premium: float,
) -> dict[str, float]:
    """Merge the incoming tick into a recent run window (pre-_record probe)."""
    prem = float(premium or 0)
    low = float(run.get("low") or 0)
    high = float(run.get("high") or 0)
    if prem <= 0:
        return dict(run)
    if low <= 0:
        low = prem
    high = max(high, prem)
    if high <= low:
        low = min(low, prem) if low > 0 else prem
        high = max(high, prem)
    off = (prem - low) / low if low > 0 and prem > low else 0.0
    run_pct = (high - low) / low if low > 0 and high > low else 0.0
    return {
        "run": run_pct,
        "low": low,
        "high": high,
        "current": prem,
        "off_low": off,
    }


def expiry_fast_vertical_burst_from_run(
    run: Mapping[str, float],
    *,
    hist: Optional[deque] = None,
    effective_volume: float = 0.0,
    settings: Any | None = None,
) -> tuple[bool, float, float]:
    """True when a short-window premium run is vertical and still early in the rip."""
    s = settings or get_settings()
    if not bool(getattr(s, "expiry_fast_vertical_burst_enabled", True)):
        return False, 0.0, 0.0

    low = float(run.get("low") or 0)
    high = float(run.get("high") or 0)
    if low <= 0 or high <= low:
        return False, 0.0, 0.0

    run_pct = float(run.get("run") or 0) * 100.0
    off_low = float(run.get("off_low") or 0) * 100.0
    min_run = float(getattr(s, "expiry_fast_vertical_burst_min_run_pct", 28.0) or 28.0)
    min_off = float(getattr(s, "expiry_fast_vertical_burst_min_off_extreme_pct", 3.0) or 3.0)
    max_off = float(getattr(s, "expiry_fast_vertical_burst_max_off_extreme_pct", 50.0) or 50.0)
    max_hist = int(getattr(s, "expiry_fast_vertical_burst_max_hist_len", 12) or 12)
    min_vol = float(getattr(s, "expiry_fast_vertical_burst_min_volume", 15000.0) or 15000.0)
    vol_bypass_run = float(
        getattr(s, "expiry_fast_vertical_burst_volume_bypass_run_pct", 45.0) or 45.0
    )

    if run_pct < min_run:
        return False, off_low, run_pct
    if not (min_off <= off_low <= max_off + 1e-6):
        return False, off_low, run_pct
    if float(effective_volume or 0) < min_vol and run_pct < vol_bypass_run:
        return False, off_low, run_pct
    if hist is not None and len(hist) > max_hist:
        return False, off_low, run_pct
    return True, off_low, run_pct


def alert_has_expiry_fast_vertical_burst(alert: Mapping[str, Any]) -> bool:
    if not isinstance(alert, Mapping):
        return False
    if bool(alert.get("expiryFastVerticalBurst")):
        return True
    return "fastVerticalBurst" in str(alert.get("reason") or "")


def snapshots_have_expiry_fast_vertical(
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """Session-halt bypass when live radar shows an in-progress expiry vertical."""
    for snap in snapshots.values():
        if not snap.dataAvailable:
            continue
        for alert in snap.explosionAlerts or []:
            if not alert_has_expiry_fast_vertical_burst(alert):
                continue
            tier = str(alert.get("tier") or "").upper()
            if tier not in ("BUILDING", "EXPLODING", "ELITE"):
                continue
            side = str(alert.get("side") or "").upper()
            if side in ("CALL", "PUT"):
                return True
    return False


def snapshots_have_put_slide_fast_vertical(
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """PUT slide off session high + live PUT fast-vertical on radar (CE/PE mirror path)."""
    from app.engines.index_rally_side_flip import index_rally_side_flip_bypass

    settings = get_settings()
    if not bool(getattr(settings, "expiry_put_slide_fast_vertical_bypass_enabled", True)):
        return False
    for snap in snapshots.values():
        if not snap.dataAvailable:
            continue
        sym = str(snap.symbol or "").upper()
        slide_ok, _, _ = index_rally_side_flip_bypass(sym, Side.PUT, snap, settings=settings)
        if not slide_ok:
            continue
        for alert in snap.explosionAlerts or []:
            if str(alert.get("side") or "").upper() != "PUT":
                continue
            if not alert_has_expiry_fast_vertical_burst(alert):
                continue
            tier = str(alert.get("tier") or "").upper()
            if tier in ("BUILDING", "EXPLODING", "ELITE"):
                return True
    return False


def snapshots_have_call_rally_fast_vertical(
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """CALL rally off session low + live CALL fast-vertical (PUT mirror)."""
    from app.engines.index_rally_side_flip import index_rally_side_flip_bypass

    settings = get_settings()
    if not bool(getattr(settings, "expiry_call_rally_fast_vertical_bypass_enabled", True)):
        return False
    for snap in snapshots.values():
        if not snap.dataAvailable:
            continue
        sym = str(snap.symbol or "").upper()
        rally_ok, _, _ = index_rally_side_flip_bypass(sym, Side.CALL, snap, settings=settings)
        if not rally_ok:
            continue
        for alert in snap.explosionAlerts or []:
            if str(alert.get("side") or "").upper() != "CALL":
                continue
            if not alert_has_expiry_fast_vertical_burst(alert):
                continue
            tier = str(alert.get("tier") or "").upper()
            if tier in ("BUILDING", "EXPLODING", "ELITE"):
                return True
    return False
