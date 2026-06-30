"""Lightweight snapshot overlay — WS tick LTPs on cached heatmap without REST rebuild."""

from __future__ import annotations

from typing import Optional

from app.models.schemas import Side, SymbolSnapshot
from app.services.tick_store import get_ltp


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
    """Clone cached snapshots and merge fresh tick LTPs into heatmap rows."""
    out: dict[str, SymbolSnapshot] = {}
    for sym, snap in snapshots.items():
        if not snap.dataAvailable:
            out[sym] = snap
            continue
        cloned = snap.model_copy(deep=True)
        for row in cloned.heatmap:
            if row.callInstrumentKey:
                ltp = get_ltp(row.callInstrumentKey, max_age_seconds=max_age_seconds)
                if ltp is not None:
                    row.callLtp = ltp
            if row.putInstrumentKey:
                ltp = get_ltp(row.putInstrumentKey, max_age_seconds=max_age_seconds)
                if ltp is not None:
                    row.putLtp = ltp
        if cloned.explosiveRunner.premium is not None and cloned.explosiveRunner.strike:
            ik = _heatmap_instrument_key(
                cloned, cloned.explosiveRunner.strike, cloned.explosiveRunner.side or Side.CALL,
            )
            if ik:
                ltp = get_ltp(ik, max_age_seconds=max_age_seconds)
                if ltp is not None:
                    cloned.explosiveRunner.premium = ltp
        out[sym] = cloned
    return out
