"""Market snapshot API."""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import orjson
from fastapi import APIRouter
from fastapi.responses import Response, StreamingResponse

from app.config import get_settings
from app.engines.auto_trader import get_state, process, process_exits_only, refresh_trading_capital
from app.engines.capital_allocator import refresh_lot_sizes
from app.engines.realtime_engine import build_symbol_snapshot
from app.engines.snapshot_fast import overlay_snapshot_live, overlay_snapshot_ltps
from app.engines.psychology_engine import analyze_psychology, psychology_to_dict
from app.engines.adaptive_exits import compute_adaptive_exit_plan
from app.models.schemas import MultiSnapshot, StrategyType
from app.services.finnhub import aggregate_sentiment
from app.services.finnhub import fetch_market_news
from app.services.redis_store import has_upstox_token
from app.services.upstox import UpstoxClient, UpstoxError, rate_limit_active, rate_limit_cooldown_remaining
from app.services.upstox_ws import is_ws_active
from app.engines.ws_snapshot import build_ws_index_snapshot

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/market", tags=["market"])

_cache: Optional[MultiSnapshot] = None
_cache_time: Optional[datetime] = None
_build_lock = asyncio.Lock()
_capital_refresh_at: Optional[datetime] = None
_news_cache: Optional[list] = None
_news_cache_at: Optional[datetime] = None
_last_full_scan_mono: float = 0.0
_last_fast_cycle_ms: Optional[float] = None
_last_full_cycle_ms: Optional[float] = None
_sse_queues: set[asyncio.Queue] = set()
_cache_json: Optional[bytes] = None
_last_touch_mono: float = 0.0
IST = ZoneInfo("Asia/Kolkata")

# Min interval between WS overlay + re-serialize on hot /snapshots/cached path
_CACHED_TOUCH_MIN_MS = 250
_build_in_progress: bool = False


def _serialize_snapshot(snap: MultiSnapshot) -> bytes:
    return orjson.dumps(snap.model_dump(mode="json"))


def _store_cache(snap: MultiSnapshot) -> None:
    global _cache, _cache_time, _cache_json
    _cache = snap
    _cache_time = datetime.now(IST)
    _cache_json = _serialize_snapshot(snap)


def _serve_stale_cache(*, reason: str = "") -> MultiSnapshot:
    """Instant read — never waits on _build_lock or REST rebuild."""
    now = datetime.now(IST)
    if _cache and _cache.snapshots:
        stale = _cache.model_copy(deep=True)
        stale.timestamp = now
        if stale.dataReady and reason:
            stale.waitingReason = reason
        elif stale.dataReady:
            stale.waitingReason = None
        stale.autoTrader = get_state()
        return stale
    return MultiSnapshot(
        timestamp=now,
        dataReady=False,
        waitingReason=reason or "Snapshot cache empty",
        snapshots={},
        autoTrader=get_state(),
    )


def _touch_cached_snapshot(
    *,
    overlay_ws: bool = False,
    light: bool = False,
    attach_trader: bool = True,
) -> Optional[MultiSnapshot]:
    """Refresh timestamp + WS overlay without a full REST rebuild."""
    global _cache
    if not _cache:
        return None
    settings = get_settings()
    snap = _cache.model_copy(deep=True)
    snap.timestamp = datetime.now(IST)
    if overlay_ws and is_ws_active() and snap.dataReady:
        if light:
            from app.engines.snapshot_fast import overlay_snapshot_spot_charts

            snap.snapshots = overlay_snapshot_spot_charts(
                snap.snapshots,
                max_age_seconds=settings.tick_overlay_max_age_seconds,
            )
        else:
            snap.snapshots = overlay_snapshot_live(
                snap.snapshots,
                max_age_seconds=settings.tick_overlay_max_age_seconds,
            )
    if attach_trader:
        snap.autoTrader = get_state()
    return snap


def _refresh_cached_json(*, overlay_ws: bool = False) -> bytes:
    """Throttled serialize for hot UI poll — avoids 5–10s JSON rebuild per request."""
    global _cache_json, _last_touch_mono
    now_mono = time.monotonic()
    if _cache_json and (now_mono - _last_touch_mono) * 1000 < _CACHED_TOUCH_MIN_MS:
        return _cache_json
    _last_touch_mono = now_mono
    if not _cache or not _cache.snapshots:
        return _cache_json or b"{}"
    touched = _touch_cached_snapshot(overlay_ws=overlay_ws, light=True)
    snap = touched if touched else _cache
    payload = snap.model_dump(mode="json")
    payload["timestamp"] = datetime.now(IST).isoformat()
    if snap.dataReady:
        payload["waitingReason"] = None
    _cache_json = orjson.dumps(payload)
    return _cache_json


def _effective_cache_seconds() -> float:
    settings = get_settings()
    if is_ws_active():
        # WS overlays LTPs on cache — avoid full REST rebuild every tick (was 75ms → 429s)
        return max(1.0, settings.ws_snapshot_cache_interval_ms / 1000.0)
    return settings.snapshot_cache_interval_ms / 1000.0


def invalidate_snapshot_cache() -> None:
    """Force next snapshot build — used on WebSocket tick wake."""
    global _cache_time, _cache_json
    _cache_time = None
    _cache_json = None


def mark_full_scan_done() -> None:
    global _last_full_scan_mono
    _last_full_scan_mono = time.monotonic()


def entry_scan_due() -> bool:
    from app.engines.session_timing import effective_entry_scan_interval_ms

    if _last_full_scan_mono <= 0:
        return True
    elapsed_ms = (time.monotonic() - _last_full_scan_mono) * 1000
    return elapsed_ms >= effective_entry_scan_interval_ms()


def can_run_tick_fast() -> bool:
    settings = get_settings()
    if not settings.tick_fast_exit_enabled or not _cache or not _cache.dataReady:
        return False
    if not get_state().openPaperTrades:
        return False
    return is_ws_active()


def latency_stats() -> dict[str, Any]:
    settings = get_settings()
    return {
        "latencyMode": settings.latency_mode,
        "tickFastExitEnabled": settings.tick_fast_exit_enabled,
        "entryScanIntervalMs": settings.entry_scan_interval_ms,
        "expiryEntryScanIntervalMs": settings.expiry_entry_scan_interval_ms,
        "explosionOpenScanIntervalMs": settings.explosion_open_scan_interval_ms,
        "marketPollIntervalWsMs": settings.market_poll_interval_ws_ms,
        "marketPollIntervalMs": settings.market_poll_interval_ms,
        "tickSnapshotIntervalMs": settings.tick_snapshot_interval_ms,
        "snapshotCacheIntervalMs": settings.snapshot_cache_interval_ms,
        "wsSnapshotCacheIntervalMs": settings.ws_snapshot_cache_interval_ms,
        "sseHeartbeatSeconds": settings.sse_heartbeat_seconds,
        "lastFastCycleMs": _last_fast_cycle_ms,
        "lastFullCycleMs": _last_full_cycle_ms,
        "buildInProgress": _build_in_progress,
        "buildLockHeld": _build_lock.locked(),
        "entryScanDue": entry_scan_due(),
        "canRunTickFast": can_run_tick_fast(),
    }


async def _fetch_news_cached() -> list:
    global _news_cache, _news_cache_at
    settings = get_settings()
    now = datetime.now(IST)
    if _news_cache is not None and _news_cache_at is not None:
        age = (now - _news_cache_at).total_seconds()
        if age < settings.news_cache_seconds:
            return _news_cache
    _news_cache = await fetch_market_news()
    _news_cache_at = now
    return _news_cache


async def run_tick_fast_cycle(*, broadcast: bool = False) -> Optional[MultiSnapshot]:
    """Tick-fast path — overlay WS LTPs on cache and evaluate exits only."""
    global _cache, _cache_time, _last_fast_cycle_ms
    if not _cache or not _cache.dataReady:
        return None

    t0 = time.perf_counter()
    settings = get_settings()
    overlays = overlay_snapshot_live(
        _cache.snapshots,
        max_age_seconds=settings.tick_overlay_max_age_seconds,
    )
    client = UpstoxClient()
    auto_state = await process_exits_only(overlays, client=client)

    snapshot = _cache.model_copy(deep=True)
    snapshot.timestamp = datetime.now(IST)
    snapshot.snapshots = overlays
    snapshot.autoTrader = auto_state
    _store_cache(snapshot)
    _last_fast_cycle_ms = round((time.perf_counter() - t0) * 1000, 2)

    if broadcast:
        await broadcast_snapshot(snapshot)
    return snapshot


async def _serve_ws_fallback_during_cooldown(*, broadcast: bool = False) -> Optional[MultiSnapshot]:
    """Index LTP from WebSocket when REST is cooling down and no stale cache exists."""
    ws_snap = build_ws_index_snapshot()
    if not ws_snap:
        return None
    if broadcast:
        await broadcast_snapshot(ws_snap)
    return ws_snap


async def _serve_stale_during_cooldown(*, broadcast: bool = False) -> Optional[MultiSnapshot]:
    """Serve last good snapshot while Upstox REST is in 429 cooldown — no API hammering."""
    global _cache
    if not _cache or not _cache.dataReady:
        return None
    secs = int(rate_limit_cooldown_remaining())
    stale = _cache.model_copy(deep=True)
    stale.timestamp = datetime.now(IST)
    stale.waitingReason = f"Upstox cooling down — retry in {secs}s · showing last good data"
    if broadcast:
        await broadcast_snapshot(stale)
    return stale


def _enrich_smt_divergence(snapshots: dict) -> None:
    """Cross-index SMT divergence between first two available symbols."""
    from app.engines.chart_advanced_analysis import detect_smt_divergence

    symbols = [s for s, snap in snapshots.items() if snap.dataAvailable and snap.chartAnalysis]
    if len(symbols) < 2:
        return
    primary, compare = symbols[0], symbols[1]
    p_snap = snapshots[primary]
    c_snap = snapshots[compare]
    p_closes = (p_snap.chartAnalysis.recentCloses or []) if p_snap.chartAnalysis else []
    c_closes = (c_snap.chartAnalysis.recentCloses or []) if c_snap.chartAnalysis else []
    if len(p_closes) < 15 or len(c_closes) < 15:
        return
    smt = detect_smt_divergence(p_closes, c_closes, primary_symbol=primary, compare_symbol=compare)
    if smt and p_snap.chartAnalysis:
        updated = p_snap.chartAnalysis.model_copy(update={"smtDivergence": smt})
        p_snap.chartAnalysis = updated
        if smt.get("bias") == "BEARISH":
            p_snap.chartAnalysis.keySignals = (p_snap.chartAnalysis.keySignals or [])[:8] + [
                f"SMT: {smt.get('message', '')}",
            ]


async def _build_multi_snapshot(*, run_trader: bool = True) -> MultiSnapshot:
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

    if rate_limit_active():
        secs = int(rate_limit_cooldown_remaining())
        raise UpstoxError(f"Upstox cooling down — retry in {secs}s")

    news = await _fetch_news_cached()
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
    try:
        await refresh_lot_sizes(client)
    except Exception as e:
        logger.warning("Lot size refresh failed: %s", e)

    if settings.use_upstox_capital_for_sizing or settings.paper_live_parity_enabled:
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
    # Parallel symbol builds — throttle lock still serializes Upstox HTTP per request
    async def _build_one(sym: str):
        try:
            return sym, await build_symbol_snapshot(sym, client, news_sentiment)
        except Exception as e:
            logger.error("Snapshot failed for %s: %s", sym, e)
            return sym, e

    results = await asyncio.gather(*[_build_one(sym) for sym in settings.symbols])
    for sym, result in results:
        if isinstance(result, Exception):
            err_msg = str(result)
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
        else:
            snapshots[sym] = result

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

    _enrich_smt_divergence(snapshots)

    from app.engines.expiry_day_guards import refresh_expiry_session

    refresh_expiry_session(snapshots)

    if data_ready and run_trader:
        auto_state = await process(snapshots, news=news, client=client)
    else:
        auto_state = get_state()

    return MultiSnapshot(
        timestamp=now,
        dataReady=data_ready,
        waitingReason=waiting_reason,
        snapshots=snapshots,
        autoTrader=auto_state,
        news=news,
    )


async def broadcast_snapshot(snapshot: MultiSnapshot) -> None:
    """Push snapshot to all SSE subscribers."""
    if not _sse_queues:
        return
    payload = snapshot.model_dump(mode="json")
    dead: list[asyncio.Queue] = []
    for q in list(_sse_queues):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                q.get_nowait()
                q.put_nowait(payload)
            except Exception:
                dead.append(q)
    for q in dead:
        _sse_queues.discard(q)


async def get_multi_snapshot_fast(*, overlay_ws: bool = True) -> MultiSnapshot:
    """Fast read for diagnostics — never triggers a full REST rebuild."""
    now = datetime.now(IST)
    if _cache and _cache.snapshots:
        touched = _touch_cached_snapshot(overlay_ws=overlay_ws and is_ws_active())
        snap = touched if touched else _cache
        fresh = snap.model_copy(deep=True)
        fresh.timestamp = now
        if fresh.dataReady:
            fresh.waitingReason = None
        return fresh
    if _cache:
        stale = _cache.model_copy(deep=True)
        stale.timestamp = now
        stale.waitingReason = stale.waitingReason or "No fresh snapshot — serving stale cache"
        return stale
    return MultiSnapshot(
        timestamp=now,
        dataReady=False,
        waitingReason="Snapshot cache empty",
        snapshots={},
        autoTrader=get_state(),
    )


async def get_multi_snapshot(
    *,
    broadcast: bool = False,
    force: bool = False,
    run_trader: Optional[bool] = None,
) -> MultiSnapshot:
    """Cached snapshot with single-flight — UI + background monitor share one build."""
    global _cache, _cache_time, _last_full_cycle_ms, _build_in_progress
    cache_ttl = _effective_cache_seconds()
    now = datetime.now(IST)
    trader_pass = entry_scan_due() if run_trader is None else bool(run_trader)

    if _build_in_progress and _cache and _cache.dataReady:
        stale = _serve_stale_cache(reason="Refresh in progress — serving last good data")
        if broadcast:
            await broadcast_snapshot(stale)
        return stale

    if rate_limit_active():
        stale = await _serve_stale_during_cooldown(broadcast=broadcast)
        if stale:
            return stale
        ws_snap = await _serve_ws_fallback_during_cooldown(broadcast=broadcast)
        if ws_snap:
            return ws_snap
        secs = int(rate_limit_cooldown_remaining())
        return MultiSnapshot(
            timestamp=now,
            dataReady=False,
            waitingReason=f"Upstox cooling down — retry in {secs}s",
            snapshots={},
            autoTrader=get_state(),
        )

    if not force and _cache and _cache_time:
        age = (now - _cache_time).total_seconds()
        if age < cache_ttl:
            _refresh_cached_json(overlay_ws=is_ws_active())
            snap = _cache
            if snap and broadcast:
                await broadcast_snapshot(snap)
            return snap

    t0 = time.perf_counter()
    if _build_lock.locked() and _cache and _cache.dataReady:
        stale = _serve_stale_cache(reason="Refresh in progress — serving last good data")
        if broadcast:
            await broadcast_snapshot(stale)
        return stale

    async with _build_lock:
        if _cache and _cache.dataReady and not force:
            age = (datetime.now(IST) - _cache_time).total_seconds() if _cache_time else 999
            if age < cache_ttl:
                _refresh_cached_json(overlay_ws=is_ws_active())
                snap = _cache
                if snap and broadcast:
                    await broadcast_snapshot(snap)
                return snap

        if rate_limit_active():
            stale = await _serve_stale_during_cooldown(broadcast=broadcast)
            if stale:
                return stale
            ws_snap = await _serve_ws_fallback_during_cooldown(broadcast=broadcast)
            if ws_snap:
                return ws_snap
            secs = int(rate_limit_cooldown_remaining())
            return MultiSnapshot(
                timestamp=now,
                dataReady=False,
                waitingReason=f"Upstox cooling down — retry in {secs}s",
                snapshots={},
                autoTrader=get_state(),
            )

        if not force and _cache and _cache_time:
            age = (datetime.now(IST) - _cache_time).total_seconds()
            if age < cache_ttl:
                _refresh_cached_json(overlay_ws=is_ws_active())
                snap = _cache
                if snap and broadcast:
                    await broadcast_snapshot(snap)
                return snap
        _build_in_progress = True
        try:
            snapshot = await _build_multi_snapshot(run_trader=trader_pass)
        except Exception as e:
            err = str(e)
            if _cache and _cache.dataReady and ("cooling down" in err.lower() or "rate limit" in err.lower()):
                logger.warning("Serving stale snapshot during Upstox cooldown: %s", e)
                stale = _cache.model_copy(deep=True)
                stale.timestamp = datetime.now(IST)
                stale.waitingReason = f"{err} · showing last good data"
                if broadcast:
                    await broadcast_snapshot(stale)
                return stale
            if "cooling down" in err.lower() or "rate limit" in err.lower():
                ws_snap = await _serve_ws_fallback_during_cooldown(broadcast=broadcast)
                if ws_snap:
                    return ws_snap
            if _cache:
                logger.warning("Serving stale snapshot after build error: %s", e)
                stale = _cache.model_copy(deep=True)
                stale.waitingReason = f"Stale data — {e}"
                return stale
            raise
        finally:
            _build_in_progress = False
        if not snapshot.dataReady and _cache and _cache.dataReady:
            reason = snapshot.waitingReason or "Data refresh paused"
            logger.warning("Serving stale snapshot — fresh build unavailable: %s", reason)
            stale = _cache.model_copy(deep=True)
            stale.waitingReason = f"{reason} · showing last good data"
            if broadcast:
                await broadcast_snapshot(stale)
            return stale
        _store_cache(snapshot)
        _last_full_cycle_ms = round((time.perf_counter() - t0) * 1000, 2)
        if force:
            mark_full_scan_done()
        if broadcast:
            await broadcast_snapshot(snapshot)
        return snapshot


@router.get("/snapshots")
async def get_snapshots():
    return await get_multi_snapshot()


@router.get("/snapshots/cached")
async def get_snapshots_cached():
    """Return pre-serialized cache instantly — no overlay/serialize on read path."""
    if _build_in_progress and _cache_json:
        return Response(content=_cache_json, media_type="application/json")
    if _cache_json and not _build_lock.locked():
        now_mono = time.monotonic()
        if (now_mono - _last_touch_mono) * 1000 >= _CACHED_TOUCH_MIN_MS:
            body = _refresh_cached_json(overlay_ws=is_ws_active())
            return Response(content=body, media_type="application/json")
    if _cache_json:
        return Response(content=_cache_json, media_type="application/json")
    if _cache and _cache.snapshots:
        body = _refresh_cached_json(overlay_ws=is_ws_active())
        return Response(content=body, media_type="application/json")
    fast = await get_multi_snapshot_fast(overlay_ws=False)
    if fast.snapshots:
        _store_cache(fast)
        return Response(content=_cache_json or _serialize_snapshot(fast), media_type="application/json")
    return await get_multi_snapshot()


@router.get("/stream")
async def market_stream():
    """Server-Sent Events — push snapshots ~0.5s when WebSocket feed is active."""
    settings = get_settings()

    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue(maxsize=4)
        _sse_queues.add(queue)
        try:
            # Instant first frame — EventSource times out if full rebuild blocks the handshake
            if _cache_json:
                yield f"data: {_cache_json.decode()}\n\n"
            else:
                fast = await get_multi_snapshot_fast(overlay_ws=is_ws_active())
                yield f"data: {orjson.dumps(fast.model_dump(mode='json')).decode()}\n\n"

            while True:
                try:
                    data: dict[str, Any] = await asyncio.wait_for(
                        queue.get(),
                        timeout=settings.sse_heartbeat_seconds,
                    )
                    yield f"data: {orjson.dumps(data).decode()}\n\n"
                except asyncio.TimeoutError:
                    if _cache_json:
                        yield f"data: {_cache_json.decode()}\n\n"
                    else:
                        fast = await get_multi_snapshot_fast(overlay_ws=False)
                        yield f"data: {orjson.dumps(fast.model_dump(mode='json')).decode()}\n\n"
        except asyncio.CancelledError:
            raise
        finally:
            _sse_queues.discard(queue)

    if not settings.sse_enabled:
        return await get_snapshots()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
