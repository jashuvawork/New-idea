"""Precise BUILDING radar LTP monitor — re-evaluate and take on every meaningful tick."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot
from app.engines.snapshot_fast import resolve_trade_premium

# key "SYMBOL:SIDE:STRIKE" -> last observed LTP
_building_ltp_watch: dict[str, float] = {}
_last_building_cycle_mono: float = 0.0


def reset_building_ltp_monitor_for_tests() -> None:
    global _last_building_cycle_mono
    _building_ltp_watch.clear()
    _last_building_cycle_mono = 0.0


def _alert_key(symbol: str, side: str, strike: float) -> str:
    return f"{str(symbol).upper()}:{str(side).upper()}:{float(strike):.0f}"


def building_alerts_on_radar(
    snapshots: dict[str, SymbolSnapshot],
) -> list[dict[str, Any]]:
    """Collect BUILDING (and building-rip ready) rows currently on radar."""
    rows: list[dict[str, Any]] = []
    for symbol, snap in (snapshots or {}).items():
        if not getattr(snap, "dataAvailable", False):
            continue
        for alert in getattr(snap, "explosionAlerts", None) or []:
            if not isinstance(alert, dict):
                continue
            tier = str(alert.get("tier") or "").upper()
            buildingish = tier == "BUILDING" or bool(
                alert.get("ictBuildingRipReady")
            )
            if not buildingish:
                continue
            side = str(alert.get("side") or "").upper()
            try:
                strike = float(alert.get("strike") or 0)
            except (TypeError, ValueError):
                strike = 0.0
            if side not in ("CALL", "PUT") or strike <= 0:
                continue
            rows.append(
                {
                    "symbol": str(symbol).upper(),
                    "side": side,
                    "strike": strike,
                    "alert": alert,
                    "snap": snap,
                }
            )
    return rows


def sync_building_ltp_watch(
    snapshots: dict[str, SymbolSnapshot],
    *,
    max_age_seconds: float = 2.0,
) -> dict[str, float]:
    """Refresh the BUILDING watch set from current radar + live LTPs."""
    settings = get_settings()
    max_age = float(
        getattr(settings, "tick_overlay_max_age_seconds", max_age_seconds)
        or max_age_seconds
    )
    live: dict[str, float] = {}
    for row in building_alerts_on_radar(snapshots):
        snap = row["snap"]
        side = Side(row["side"])
        ltp = resolve_trade_premium(
            snap,
            row["strike"],
            side,
            max_age_seconds=max_age,
        )
        if ltp is None or float(ltp) <= 0:
            try:
                ltp = float(row["alert"].get("premium") or 0)
            except (TypeError, ValueError):
                ltp = 0.0
        if float(ltp or 0) <= 0:
            continue
        key = _alert_key(row["symbol"], row["side"], row["strike"])
        live[key] = float(ltp)

    # Drop names that left BUILDING radar; keep current set only.
    stale = [k for k in _building_ltp_watch if k not in live]
    for key in stale:
        _building_ltp_watch.pop(key, None)
    for key, ltp in live.items():
        _building_ltp_watch.setdefault(key, ltp)
    return dict(live)


def peek_building_ltp_moves(
    snapshots: dict[str, SymbolSnapshot],
    *,
    max_age_seconds: float = 2.0,
) -> tuple[bool, list[str], dict[str, float]]:
    """Detect meaningful BUILDING LTP moves without consuming fingerprints."""
    settings = get_settings()
    min_pct = float(
        getattr(settings, "building_ltp_min_change_pct", 0.15) or 0.15
    )
    min_abs = float(
        getattr(settings, "building_ltp_min_change_abs", 0.05) or 0.05
    )
    live = sync_building_ltp_watch(
        snapshots, max_age_seconds=max_age_seconds,
    )
    if not live:
        return False, [], live

    moved: list[str] = []
    for key, ltp in live.items():
        prev = _building_ltp_watch.get(key)
        if prev is None or prev <= 0:
            continue
        delta = abs(ltp - prev)
        pct = (delta / prev) * 100.0 if prev > 0 else 0.0
        if delta >= min_abs or pct >= min_pct:
            moved.append(key)
    return bool(moved), moved, live


def building_ltp_moved(
    snapshots: dict[str, SymbolSnapshot],
    *,
    max_age_seconds: float = 2.0,
) -> tuple[bool, list[str]]:
    """True when any watched BUILDING contract printed a meaningful new LTP."""
    moved, keys, live = peek_building_ltp_moves(
        snapshots, max_age_seconds=max_age_seconds,
    )
    if moved:
        for key in keys:
            if key in live:
                _building_ltp_watch[key] = live[key]
    elif live:
        # Seed first samples so the next tick can detect a move.
        for key, ltp in live.items():
            _building_ltp_watch.setdefault(key, ltp)
    return moved, keys


def mark_building_ltps_seen(snapshots: dict[str, SymbolSnapshot]) -> None:
    """Align watch fingerprints after a full BUILDING entry cycle."""
    live = sync_building_ltp_watch(snapshots)
    _building_ltp_watch.clear()
    _building_ltp_watch.update(live)


def building_ltp_monitor_due(
    snapshots: Optional[dict[str, SymbolSnapshot]],
    *,
    now_mono: Optional[float] = None,
) -> bool:
    """Whether the BUILDING LTP entry cycle should run now."""
    import time

    settings = get_settings()
    if not bool(getattr(settings, "building_ltp_monitor_enabled", True)):
        return False
    if not snapshots:
        return False

    has_building = bool(building_alerts_on_radar(snapshots))
    if not has_building and not _building_ltp_watch:
        return False

    mono = time.monotonic() if now_mono is None else float(now_mono)
    min_ms = float(
        getattr(settings, "building_ltp_monitor_min_ms", 75.0) or 75.0
    )
    if _last_building_cycle_mono > 0 and (mono - _last_building_cycle_mono) * 1000 < min_ms:
        return False

    moved, _, live = peek_building_ltp_moves(snapshots)
    if not moved:
        # First sighting: seed fingerprints and wait for the next LTP print.
        for key, ltp in live.items():
            _building_ltp_watch.setdefault(key, ltp)
        return False
    return True


def mark_building_ltp_cycle_done(*, now_mono: Optional[float] = None) -> None:
    import time

    global _last_building_cycle_mono
    _last_building_cycle_mono = (
        time.monotonic() if now_mono is None else float(now_mono)
    )


def building_watch_snapshot() -> dict[str, Any]:
    return {
        "watched": dict(_building_ltp_watch),
        "count": len(_building_ltp_watch),
        "lastCycleMono": _last_building_cycle_mono,
    }
