"""Market snapshot API."""

import asyncio
import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter

from app.config import get_settings
from app.engines.auto_trader import get_state, process, refresh_trading_capital
from app.engines.realtime_engine import build_symbol_snapshot
from app.engines.psychology_engine import analyze_psychology, psychology_to_dict
from app.engines.adaptive_exits import compute_adaptive_exit_plan
from app.models.schemas import MultiSnapshot, StrategyType
from app.services.finnhub import aggregate_sentiment
from app.services.finnhub import fetch_market_news
from app.services.redis_store import has_upstox_token
from app.services.upstox import UpstoxClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/market", tags=["market"])

_cache: Optional[MultiSnapshot] = None
_cache_time: Optional[datetime] = None
_build_lock = asyncio.Lock()
_capital_refresh_at: Optional[datetime] = None
IST = ZoneInfo("Asia/Kolkata")


async def _build_multi_snapshot() -> MultiSnapshot:
    global _capital_refresh_at
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
    if settings.use_upstox_capital_for_sizing:
        refresh_due = (
            _capital_refresh_at is None
            or (now - _capital_refresh_at).total_seconds() >= settings.capital_refresh_seconds
        )
        if refresh_due:
            try:
                await refresh_trading_capital(client)
                _capital_refresh_at = now
            except Exception as e:
                logger.warning("Capital refresh failed: %s", e)

    snapshots = {}
    # Sequential symbol builds to reduce burst load on Upstox (throttle still applies per request)
    for sym in settings.symbols:
        try:
            snapshots[sym] = await build_symbol_snapshot(sym, client, news_sentiment)
        except Exception as e:
            logger.error("Snapshot failed for %s: %s", sym, e)
            err_msg = str(e)
            if _cache and sym in _cache.snapshots and _cache.snapshots[sym].dataAvailable:
                logger.info("Reusing stale snapshot for %s", sym)
                snapshots[sym] = _cache.snapshots[sym]
            else:
                from app.models.schemas import MarketPhase, SymbolSnapshot
                snapshots[sym] = SymbolSnapshot(
                    symbol=sym,
                    timestamp=now,
                    marketPhase=MarketPhase.LIVE_MARKET,
                    dataAvailable=False,
                    error=err_msg[:200],
                )

    data_ready = any(s.dataAvailable for s in snapshots.values())
    waiting_reason = None
    if not data_ready:
        errors = [s.error for s in snapshots.values() if s.error]
        waiting_reason = errors[0] if errors else "Waiting for real Upstox data"

    news_sentiment_agg = aggregate_sentiment(news)
    for sym, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        ps = analyze_psychology(snap, news)
        snap.psychology = psychology_to_dict(ps)
        hint = compute_adaptive_exit_plan(
            snap, StrategyType.SCALP, ps, snap.optimizedProfile, confidence=snap.tradeQualityScore, news=news,
        )
        snap.adaptiveExitHint = hint.to_dict()
        snap.psychology["newsAggregate"] = news_sentiment_agg

    auto_state = await process(snapshots, news=news, client=client) if data_ready else get_state()

    return MultiSnapshot(
        timestamp=now,
        dataReady=data_ready,
        waitingReason=waiting_reason,
        snapshots=snapshots,
        autoTrader=auto_state,
        news=news,
    )


async def get_multi_snapshot() -> MultiSnapshot:
    """Cached snapshot with single-flight — UI + background monitor share one build."""
    global _cache, _cache_time
    settings = get_settings()
    now = datetime.now(IST)

    if _cache and _cache_time:
        age = (now - _cache_time).total_seconds()
        if age < settings.snapshot_cache_seconds:
            return _cache

    async with _build_lock:
        if _cache and _cache_time:
            age = (datetime.now(IST) - _cache_time).total_seconds()
            if age < settings.snapshot_cache_seconds:
                return _cache
        try:
            snapshot = await _build_multi_snapshot()
        except Exception as e:
            if _cache:
                logger.warning("Serving stale snapshot after build error: %s", e)
                stale = _cache.model_copy(deep=True)
                stale.waitingReason = f"Stale data — {e}"
                return stale
            raise
        _cache = snapshot
        _cache_time = datetime.now(IST)
        return snapshot


@router.get("/snapshots")
async def get_snapshots():
    return await get_multi_snapshot()


@router.get("/premarket/{symbol}")
async def get_premarket_analysis(symbol: str):
    """Dedicated pre-open gap/volume analysis (9:00–9:15 IST and early open)."""
    if not await has_upstox_token():
        return {"dataAvailable": False, "error": "Upstox not authenticated", "symbol": symbol.upper()}
    from app.engines.premarket_engine import build_premarket_analysis

    client = UpstoxClient()
    news = await fetch_market_news()
    news_sentiment = aggregate_sentiment(news).get("bias", "NEUTRAL")
    try:
        analysis = await build_premarket_analysis(symbol.upper(), client, news_sentiment)
        return {"dataAvailable": True, "symbol": symbol.upper(), "premarket": analysis.model_dump(mode="json")}
    except Exception as e:
        logger.warning("Premarket API error for %s: %s", symbol, e)
        return {"dataAvailable": False, "error": str(e), "symbol": symbol.upper()}


@router.get("/constituents/{symbol}")
async def get_constituent_heatmap(symbol: str):
    """NIFTY/SENSEX/BANKNIFTY constituent heatmap with breadth analysis."""
    if not await has_upstox_token():
        return {
            "dataAvailable": False,
            "error": "Upstox not authenticated",
            "symbol": symbol.upper(),
        }
    from app.engines.constituent_engine import build_constituent_heatmap

    client = UpstoxClient()
    hm = await build_constituent_heatmap(symbol.upper(), client, force_refresh=False)
    return hm.model_dump(mode="json")
