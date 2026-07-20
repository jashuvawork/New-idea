"""Lightweight snapshot overlay — WS tick LTPs on cached heatmap without REST rebuild."""

from __future__ import annotations

from typing import Optional

from app.models.schemas import Side, SymbolSnapshot
from app.services.tick_store import get_index_spot, get_ltp


def _heatmap_instrument_key(snap: SymbolSnapshot, strike: float, side: Side) -> Optional[str]:
    for row in snap.heatmap:
        if abs(row.strike - strike) < 1:
            return row.callInstrumentKey if side == Side.CALL else row.putInstrumentKey
    return None


def resolve_trade_premium(
    snap: SymbolSnapshot,
    strike: float,
    side: Side,
    instrument_key: Optional[str] = None,
    *,
    max_age_seconds: float = 1.0,
) -> Optional[float]:
    """Prefer fresh WebSocket LTP, then heatmap/rest snapshot."""
    keys: list[Optional[str]] = [instrument_key, _heatmap_instrument_key(snap, strike, side)]
    for key in keys:
        if not key:
            continue
        ltp = get_ltp(key, max_age_seconds=max_age_seconds)
        if ltp is not None:
            return ltp

    for row in snap.heatmap:
        if abs(row.strike - strike) < 1:
            if side == Side.CALL:
                return row.callLtp
            return row.putLtp
    if snap.explosiveRunner.strike == strike:
        return snap.explosiveRunner.premium
    return None


def overlay_snapshot_ltps(
    snapshots: dict[str, SymbolSnapshot],
    *,
    max_age_seconds: float = 1.0,
) -> dict[str, SymbolSnapshot]:
    """Shallow-clone only mutated rows — deep=True freezes the event loop."""
    out: dict[str, SymbolSnapshot] = {}
    for sym, snap in snapshots.items():
        if not snap.dataAvailable:
            out[sym] = snap
            continue

        new_heatmap = None
        for idx, row in enumerate(snap.heatmap):
            call_ltp = (
                get_ltp(row.callInstrumentKey, max_age_seconds=max_age_seconds)
                if row.callInstrumentKey
                else None
            )
            put_ltp = (
                get_ltp(row.putInstrumentKey, max_age_seconds=max_age_seconds)
                if row.putInstrumentKey
                else None
            )
            if call_ltp is None and put_ltp is None:
                continue
            if new_heatmap is None:
                new_heatmap = list(snap.heatmap)
            updated = row.model_copy(deep=False)
            if call_ltp is not None:
                updated.callLtp = call_ltp
            if put_ltp is not None:
                updated.putLtp = put_ltp
            new_heatmap[idx] = updated

        runner_ltp = None
        runner = snap.explosiveRunner
        if runner and runner.premium is not None and runner.strike:
            ik = _heatmap_instrument_key(
                snap, runner.strike, runner.side or Side.CALL,
            )
            if ik:
                runner_ltp = get_ltp(ik, max_age_seconds=max_age_seconds)

        if new_heatmap is None and runner_ltp is None:
            out[sym] = snap
            continue

        cloned = snap.model_copy(deep=False)
        if new_heatmap is not None:
            cloned.heatmap = new_heatmap
        if runner_ltp is not None and runner is not None:
            cloned.explosiveRunner = runner.model_copy(deep=False)
            cloned.explosiveRunner.premium = runner_ltp
        out[sym] = cloned
    return out


def overlay_snapshot_spot_charts(
    snapshots: dict[str, SymbolSnapshot],
    *,
    max_age_seconds: float = 1.0,
) -> dict[str, SymbolSnapshot]:
    """Refresh index spot + spotChart — shallow clone only (no deep tree copy)."""
    from app.engines.spot_direction import refresh_spot_chart_live

    out: dict[str, SymbolSnapshot] = {}
    for sym, snap in snapshots.items():
        if not snap.dataAvailable or not snap.spotChart:
            out[sym] = snap
            continue

        live_spot = get_index_spot(sym, max_age_seconds=max_age_seconds)
        if live_spot is None:
            out[sym] = snap
            continue

        cloned = snap.model_copy(deep=False)
        cloned.spot = live_spot
        breadth_bias = cloned.breadth.bias if cloned.breadth else "NEUTRAL"
        cloned.spotChart = refresh_spot_chart_live(
            cloned.spotChart,
            live_spot=live_spot,
            profile=cloned.marketProfile,
            chart_analysis=cloned.chartAnalysis,
            breadth_bias=breadth_bias,
        )
        out[sym] = cloned
    return out


def overlay_snapshot_live(
    snapshots: dict[str, SymbolSnapshot],
    *,
    max_age_seconds: float = 1.0,
) -> dict[str, SymbolSnapshot]:
    """WS overlay for heatmap premiums + index spotChart refresh."""
    with_spot = overlay_snapshot_spot_charts(snapshots, max_age_seconds=max_age_seconds)
    return overlay_snapshot_ltps(with_spot, max_age_seconds=max_age_seconds)
