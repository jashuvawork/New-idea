"""Fetch index OHLC for live spotChart — native 5m with 1m fallback/resample."""

from __future__ import annotations

import logging
from time import monotonic
from typing import Any

from app.config import Settings, get_settings
from app.engines.mtf_chart_analysis import resample_candles
from app.services.upstox import INDEX_KEYS, UpstoxClient

logger = logging.getLogger(__name__)

# Last good index OHLC from snapshot refresh — used when execution-chart fetch fails.
_snapshot_candle_cache: dict[str, tuple[float, list[Any], list[Any]]] = {}


def remember_snapshot_index_candles(
    symbol: str,
    candles_5m: list[Any],
    candles_1m: list[Any],
) -> None:
    """Store recent index candles for cash-candle rollover when live chart fetch fails."""
    sym = str(symbol or "").upper()
    if not sym:
        return
    c5 = list(candles_5m or [])
    c1 = list(candles_1m or [])
    if not c5 and not c1:
        return
    _snapshot_candle_cache[sym] = (monotonic(), c5, c1)


def cached_snapshot_index_candles(
    symbol: str,
    *,
    settings: Settings | None = None,
) -> tuple[list[Any], list[Any]]:
    """Return (candles_5m, candles_1m) from the last snapshot refresh, or empty if stale."""
    sym = str(symbol or "").upper()
    row = _snapshot_candle_cache.get(sym)
    if not row:
        return [], []
    s = settings or get_settings()
    ttl = float(
        getattr(s, "index_candle_snapshot_cache_ttl_seconds", 180.0) or 180.0
    )
    ts, c5, c1 = row
    if ttl > 0 and (monotonic() - ts) > ttl:
        return [], []
    return list(c5), list(c1)


async def fetch_index_chart_candles(
    client: UpstoxClient,
    symbol: str,
    *,
    force_refresh: bool = False,
) -> tuple[list[Any], list[Any]]:
    """
    Returns (candles_5m, candles_1m).
    5m from V3 intraday when available; otherwise resampled from extended 1m history.
    """
    settings = get_settings()
    sym = symbol.upper()
    key = INDEX_KEYS.get(sym)
    if not key:
        return [], []

    candles_1m = await client.get_historical_candles(
        key,
        interval="1minute",
        count=settings.spot_chart_1m_bars,
        force_refresh=force_refresh,
    )

    candles_5m: list[Any] = []
    if settings.execution_mtf_use_v3_native:
        try:
            candles_5m = await client.get_intraday_candles_v3(
                key,
                unit="minutes",
                interval=settings.spot_chart_timeframe_minutes,
                force_refresh=force_refresh,
            )
        except Exception as exc:
            logger.debug("V3 %sm candles failed for %s: %s", settings.spot_chart_timeframe_minutes, sym, exc)

    if not candles_5m and candles_1m:
        candles_5m = resample_candles(candles_1m, settings.spot_chart_timeframe_minutes)

    return candles_5m, candles_1m
