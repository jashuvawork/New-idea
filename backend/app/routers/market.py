"""Market snapshot API."""

import asyncio
import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from app.config import get_settings
from app.engines.auto_trader import get_state, process
from app.engines.realtime_engine import build_symbol_snapshot
from app.models.schemas import MultiSnapshot
from app.services.finnhub import fetch_market_news
from app.services.redis_store import has_upstox_token
from app.services.upstox import UpstoxClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/market", tags=["market"])

_cache: Optional[MultiSnapshot] = None
_cache_time: Optional[datetime] = None
IST = ZoneInfo("Asia/Kolkata")


async def _build_multi_snapshot() -> MultiSnapshot:
    settings = get_settings()
    now = datetime.now(IST)

    if not await has_upstox_token():
        return MultiSnapshot(
            timestamp=now,
            dataReady=False,
            waitingReason="Upstox not authenticated — open /api/upstox/login-url",
            snapshots={},
            autoTrader=get_state(),
        )

    news = await fetch_market_news()
    news_sentiment = "NEUTRAL"
    if news:
        sentiments = [n.get("sentiment", "NEUTRAL") for n in news[:5]]
        bullish = sentiments.count("BULLISH")
        bearish = sentiments.count("BEARISH")
        if bullish > bearish:
            news_sentiment = "BULLISH"
        elif bearish > bullish:
            news_sentiment = "BEARISH"

    client = UpstoxClient()
    snapshots = {}
    tasks = [build_symbol_snapshot(sym, client, news_sentiment) for sym in settings.symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for sym, result in zip(settings.symbols, results):
        if isinstance(result, Exception):
            logger.error("Snapshot failed for %s: %s", sym, result)
            continue
        snapshots[sym] = result

    data_ready = any(s.dataAvailable for s in snapshots.values())
    waiting_reason = None
    if not data_ready:
        errors = [s.error for s in snapshots.values() if s.error]
        waiting_reason = errors[0] if errors else "Waiting for real Upstox data"

    auto_state = process(snapshots) if data_ready else get_state()

    return MultiSnapshot(
        timestamp=now,
        dataReady=data_ready,
        waitingReason=waiting_reason,
        snapshots=snapshots,
        autoTrader=auto_state,
        news=news,
    )


@router.get("/snapshots")
async def get_snapshots():
    global _cache, _cache_time
    settings = get_settings()
    now = datetime.now(IST)

    if _cache and _cache_time:
        age = (now - _cache_time).total_seconds()
        if age < settings.snapshot_cache_seconds:
            return _cache

    snapshot = await _build_multi_snapshot()
    _cache = snapshot
    _cache_time = now
    return snapshot
