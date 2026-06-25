"""In-memory LTP cache from Upstox WebSocket ticks."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

from app.services.upstox import INDEX_KEYS

# symbol -> index instrument key
_SYMBOL_BY_INDEX_KEY = {v: k for k, v in INDEX_KEYS.items()}


@dataclass
class Tick:
    instrument_key: str
    ltp: float
    received_mono: float
    ltt_ms: int = 0
    volume: int = 0


_ticks: dict[str, Tick] = {}
_tick_count: int = 0
_last_tick_mono: float = 0.0


def _norm_key(key: str) -> str:
    return key.replace(":", "|")


def record_tick(
    instrument_key: str,
    ltp: float,
    *,
    ltt_ms: int = 0,
    volume: int = 0,
) -> None:
    """Store latest tick for an instrument."""
    global _tick_count, _last_tick_mono
    if not instrument_key or ltp is None or ltp <= 0:
        return
    key = _norm_key(instrument_key)
    now = time.monotonic()
    _ticks[key] = Tick(
        instrument_key=key,
        ltp=float(ltp),
        received_mono=now,
        ltt_ms=ltt_ms,
        volume=volume,
    )
    _tick_count += 1
    _last_tick_mono = now


def get_tick(instrument_key: str, max_age_seconds: float = 30.0) -> Optional[Tick]:
    key = _norm_key(instrument_key)
    tick = _ticks.get(key)
    if not tick:
        return None
    if time.monotonic() - tick.received_mono > max_age_seconds:
        return None
    return tick


def get_ltp(instrument_key: str, max_age_seconds: float = 30.0) -> Optional[float]:
    tick = get_tick(instrument_key, max_age_seconds)
    return tick.ltp if tick else None


def get_index_spot(symbol: str, max_age_seconds: float = 30.0) -> Optional[float]:
    key = INDEX_KEYS.get(symbol.upper())
    if not key:
        return None
    return get_ltp(key, max_age_seconds)


def overlay_chain_ltps(chain: list[dict[str, Any]], max_age_seconds: float = 30.0) -> list[dict[str, Any]]:
    """Merge fresher WebSocket LTPs into option chain rows."""
    if not chain or not _ticks:
        return chain

    out: list[dict[str, Any]] = []
    for row in chain:
        row = dict(row)
        ce = dict(row.get("call_options") or row.get("CE") or {})
        pe = dict(row.get("put_options") or row.get("PE") or {})

        ce_key = ce.get("instrument_key")
        pe_key = pe.get("instrument_key")
        ce_ltp = get_ltp(ce_key, max_age_seconds) if ce_key else None
        pe_ltp = get_ltp(pe_key, max_age_seconds) if pe_key else None

        if ce_ltp is not None:
            ce["ltp"] = ce_ltp
            ce["last_price"] = ce_ltp
        if pe_ltp is not None:
            pe["ltp"] = pe_ltp
            pe["last_price"] = pe_ltp

        if ce:
            row["call_options"] = ce
            row["CE"] = ce
        if pe:
            row["put_options"] = pe
            row["PE"] = pe
        out.append(row)
    return out


def overlay_index_ltp(symbol: str, rest_ltp: float, max_age_seconds: float = 30.0) -> float:
    """Prefer WebSocket index spot when tick is fresh."""
    ws_ltp = get_index_spot(symbol, max_age_seconds)
    return ws_ltp if ws_ltp is not None else rest_ltp


def collect_option_keys_from_chain(
    chain: list[dict[str, Any]],
    atm: float,
    scan_range: float,
) -> list[str]:
    """Instrument keys for ATM ± scan_range strikes (call + put)."""
    keys: list[str] = []
    for row in chain:
        strike = row.get("strike_price") or row.get("strike", 0)
        if abs(float(strike) - atm) > scan_range:
            continue
        ce = row.get("call_options") or row.get("CE") or {}
        pe = row.get("put_options") or row.get("PE") or {}
        for leg in (ce, pe):
            ik = leg.get("instrument_key")
            if ik:
                keys.append(_norm_key(ik))
    return keys


def status() -> dict[str, Any]:
    now = time.monotonic()
    age_ms = int((now - _last_tick_mono) * 1000) if _last_tick_mono else None
    return {
        "tickCount": _tick_count,
        "instrumentCount": len(_ticks),
        "lastTickAgeMs": age_ms,
        "hasRecentTicks": age_ms is not None and age_ms < 5000,
    }


def clear() -> None:
    global _tick_count, _last_tick_mono
    _ticks.clear()
    _tick_count = 0
    _last_tick_mono = 0.0
