"""Resolve rolling MCX commodity futures keys from Upstox instrument master."""

from __future__ import annotations

import gzip
import json
import logging
import time
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

_INSTRUMENTS_URL = (
    "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"
)
_CACHE_TTL_SECONDS = 6 * 3600
_rows: list[dict[str, Any]] | None = None
_loaded_at: float = 0.0
_resolved_fut: dict[str, tuple[float, str]] = {}


async def _fetch_rows() -> list[dict[str, Any]]:
    global _rows, _loaded_at
    now = time.monotonic()
    if _rows is not None and now - _loaded_at < _CACHE_TTL_SECONDS:
        return _rows
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(_INSTRUMENTS_URL)
        resp.raise_for_status()
        raw = gzip.decompress(resp.content)
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, list):
            raise ValueError("Upstox instruments payload is not a list")
        _rows = parsed
        _loaded_at = now
        _resolved_fut.clear()
        logger.info("Upstox instruments loaded: %d rows", len(_rows))
        return _rows


def _ms_to_date(ms: Any) -> Optional[datetime]:
    try:
        val = int(ms)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(val / 1000.0, tz=IST)


def resolve_nearest_mcx_futures_key(
    rows: list[dict[str, Any]],
    futures_asset_symbol: str,
    *,
    as_of: Optional[datetime] = None,
) -> Optional[str]:
    """Nearest MCX_FO FUT contract instrument_key for an options asset symbol (e.g. CRUDEOILM)."""
    now = as_of or datetime.now(IST)
    today = now.date()
    best_key: Optional[str] = None
    best_expiry: Optional[datetime] = None
    asset = str(futures_asset_symbol or "").strip().upper()
    if not asset:
        return None
    for row in rows:
        if row.get("segment") != "MCX_FO":
            continue
        if str(row.get("instrument_type") or "").upper() != "FUT":
            continue
        if str(row.get("asset_symbol") or "").upper() != asset:
            continue
        exp = _ms_to_date(row.get("expiry"))
        if exp is None or exp.date() < today:
            continue
        key = row.get("instrument_key")
        if not key:
            continue
        if best_expiry is None or exp < best_expiry:
            best_expiry = exp
            best_key = str(key)
    return best_key


async def commodity_futures_instrument_key(
    futures_asset_symbol: str,
    *,
    fallback: str = "",
) -> str:
    """Cached async resolve for live commodity option-chain / quote keys."""
    asset = str(futures_asset_symbol or "").strip().upper()
    if not asset:
        return fallback
    now = time.monotonic()
    cached = _resolved_fut.get(asset)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]
    rows = await _fetch_rows()
    resolved = resolve_nearest_mcx_futures_key(rows, asset) or fallback
    if resolved:
        _resolved_fut[asset] = (now, resolved)
    return resolved


def list_option_expiries_from_master(
    rows: list[dict[str, Any]],
    futures_asset_symbol: str,
    *,
    as_of: Optional[datetime] = None,
    limit: int = 8,
) -> list[str]:
    """Distinct YYYY-MM-DD option expiries for an MCX mini asset (instrument-master fallback)."""
    now = as_of or datetime.now(IST)
    today = now.date().isoformat()
    asset = str(futures_asset_symbol or "").strip().upper()
    if not asset:
        return []
    expiries: set[str] = set()
    for row in rows:
        if row.get("segment") != "MCX_FO":
            continue
        if str(row.get("instrument_type") or "").upper() not in ("CE", "PE"):
            continue
        if str(row.get("asset_symbol") or "").upper() != asset:
            continue
        exp = _ms_to_date(row.get("expiry"))
        if exp is None:
            continue
        iso = exp.date().isoformat()
        if iso >= today:
            expiries.add(iso)
    return sorted(expiries)[: max(1, limit)]


async def commodity_option_expiries(
    futures_asset_symbol: str,
    *,
    limit: int = 8,
) -> list[str]:
    rows = await _fetch_rows()
    return list_option_expiries_from_master(rows, futures_asset_symbol, limit=limit)


def invalidate_instrument_cache() -> None:
    """Test hook — clear downloaded master + resolved keys."""
    global _rows, _loaded_at
    _rows = None
    _loaded_at = 0.0
    _resolved_fut.clear()