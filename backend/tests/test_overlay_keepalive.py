"""SSE overlay keepalive during heavy trader passes."""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from app.engines.auto_trader import AutoTraderState
from app.models.schemas import MarketPhase, MultiSnapshot, SymbolSnapshot
from app.routers import market as market_router

IST = ZoneInfo("Asia/Kolkata")


def test_broadcast_sets_overlay_age():
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=25000.0,
    )
    market_router._sse_queues.clear()
    q: asyncio.Queue = asyncio.Queue(maxsize=2)
    market_router._sse_queues.add(q)

    async def _run():
        market_router._store_cache(
            MultiSnapshot(
                timestamp=datetime.now(IST),
                dataReady=True,
                snapshots={"NIFTY": snap},
                autoTrader=AutoTraderState(),
            )
        )
        await market_router.broadcast_snapshot()

    asyncio.run(_run())
    stats = market_router.latency_stats()
    assert stats.get("lastOverlayBroadcastAgeMs") is not None
    assert stats["lastOverlayBroadcastAgeMs"] < 500


def test_keepalive_runs_during_slow_trader():
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=25000.0,
    )
    market_router._sse_queues.clear()
    q: asyncio.Queue = asyncio.Queue(maxsize=8)
    market_router._sse_queues.add(q)
    market_router._store_cache(
        MultiSnapshot(
            timestamp=datetime.now(IST),
            dataReady=True,
            snapshots={"NIFTY": snap},
            autoTrader=AutoTraderState(),
        )
    )
    broadcasts: list[int] = []

    async def slow_trader():
        await asyncio.sleep(1.1)
        return AutoTraderState()

    async def _track_broadcast(*_a, **_k):
        broadcasts.append(1)

    async def _run():
        with patch.object(
            market_router,
            "broadcast_snapshot",
            side_effect=_track_broadcast,
        ):
            await market_router._run_with_overlay_keepalive(
                slow_trader(),
                snapshots={"NIFTY": snap},
                broadcast=True,
            )

    asyncio.run(_run())
    assert len(broadcasts) >= 1
