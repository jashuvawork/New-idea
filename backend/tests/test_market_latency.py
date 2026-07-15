"""Market router latency — stale-serve while rebuild in progress."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers import market as market_router


@pytest.fixture(autouse=True)
def _reset_market_cache():
    market_router._cache = None
    market_router._cache_time = None
    market_router._cache_json = None
    market_router._build_in_progress = False
    market_router._last_ws_overlay_mono = 0.0
    market_router._last_exit_eval_mono = 0.0
    market_router._last_full_rest_mono = 0.0
    market_router._sse_payload_dict = None
    yield
    market_router._cache = None
    market_router._cache_time = None
    market_router._cache_json = None
    market_router._build_in_progress = False
    market_router._last_ws_overlay_mono = 0.0
    market_router._last_exit_eval_mono = 0.0
    market_router._last_full_rest_mono = 0.0
    market_router._sse_payload_dict = None


def test_serve_stale_cache_when_build_in_progress():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.models.schemas import AutoTraderState, MarketPhase, MultiSnapshot, SymbolSnapshot

    IST = ZoneInfo("Asia/Kolkata")
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=50.0,
    )
    market_router._cache = MultiSnapshot(
        timestamp=datetime.now(IST),
        dataReady=True,
        snapshots={"NIFTY": snap},
        autoTrader=AutoTraderState(),
    )
    market_router._build_in_progress = True
    stale = market_router._serve_stale_cache(reason="Refresh in progress")
    assert stale.dataReady is True
    assert "Refresh in progress" in (stale.waitingReason or "")


def test_build_in_progress_flag_serves_stale():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.models.schemas import AutoTraderState, MarketPhase, MultiSnapshot, SymbolSnapshot

    IST = ZoneInfo("Asia/Kolkata")
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=50.0,
    )
    market_router._cache = MultiSnapshot(
        timestamp=datetime.now(IST),
        dataReady=True,
        snapshots={"NIFTY": snap},
        autoTrader=AutoTraderState(),
    )
    market_router._build_in_progress = True
    stale = market_router._serve_stale_cache(reason="Refresh in progress")
    assert stale.snapshots["NIFTY"].symbol == "NIFTY"


def test_constituents_due_respects_interval():
    from app.engines.realtime_engine import (
        constituents_due,
        record_constituent_heatmap,
        _constituent_cache,
    )

    _constituent_cache.clear()
    with patch("app.engines.realtime_engine.get_settings") as gs:
        gs.return_value = MagicMock(
            fetch_constituents_in_snapshot=True,
            fetch_constituents_interval_seconds=60,
        )
        assert constituents_due("NIFTY") is True
        record_constituent_heatmap("NIFTY", {"rows": []})
        assert constituents_due("NIFTY") is False


def test_cached_endpoint_returns_bytes_without_refresh():
    import asyncio
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.models.schemas import AutoTraderState, MarketPhase, MultiSnapshot, SymbolSnapshot

    IST = ZoneInfo("Asia/Kolkata")
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=50.0,
    )
    multi = MultiSnapshot(
        timestamp=datetime.now(IST),
        dataReady=True,
        snapshots={"NIFTY": snap},
        autoTrader=AutoTraderState(),
    )
    market_router._store_cache(multi)
    sentinel = market_router._cache_json

    async def _run():
        with patch.object(market_router, "_refresh_cached_json") as refresh:
            resp = await market_router.get_snapshots_cached()
            refresh.assert_not_called()
        return resp

    resp = asyncio.run(_run())
    assert resp.body == sentinel


def test_ws_overlay_cycle_updates_cache_without_trader():
    import asyncio
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.models.schemas import AutoTraderState, MarketPhase, MultiSnapshot, SymbolSnapshot

    IST = ZoneInfo("Asia/Kolkata")
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=50.0,
    )
    market_router._store_cache(
        MultiSnapshot(
            timestamp=datetime.now(IST),
            dataReady=True,
            snapshots={"NIFTY": snap},
            autoTrader=AutoTraderState(),
        ),
    )

    async def _run():
        with patch("app.routers.market.is_ws_active", return_value=True), patch(
            "app.routers.market.overlay_snapshot_live",
            return_value={"NIFTY": snap},
        ):
            return await market_router.run_ws_overlay_cycle()

    out = asyncio.run(_run())
    assert out is not None
    assert market_router._cache_json is not None


def test_ws_overlay_due_throttles_rapid_calls():
    import time

    market_router._last_ws_overlay_mono = time.monotonic()
    assert market_router.ws_overlay_due() is False
    market_router._last_ws_overlay_mono = 0.0
    assert market_router.ws_overlay_due() is True


def test_tick_fast_skips_serialize_when_throttled():
    import asyncio
    import time
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from unittest.mock import AsyncMock, patch

    from app.models.schemas import AutoTraderState, MarketPhase, MultiSnapshot, SymbolSnapshot

    IST = ZoneInfo("Asia/Kolkata")
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=50.0,
    )
    market_router._store_cache(
        MultiSnapshot(
            timestamp=datetime.now(IST),
            dataReady=True,
            snapshots={"NIFTY": snap},
            autoTrader=AutoTraderState(),
        ),
    )
    market_router._last_ws_overlay_mono = time.monotonic()

    async def _run():
        with patch("app.routers.market.is_ws_active", return_value=True), patch(
            "app.routers.market.overlay_snapshot_live",
            return_value={"NIFTY": snap},
        ), patch("app.routers.market.process_exits_only", new_callable=AsyncMock) as exits, patch.object(
            market_router, "_store_cache_async", new_callable=AsyncMock,
        ) as store:
            from app.engines.auto_trader import get_state

            exits.return_value = get_state()
            market_router._last_exit_eval_mono = 0.0
            await market_router.run_tick_fast_cycle()
            return store

    store = asyncio.run(_run())
    store.assert_not_called()
