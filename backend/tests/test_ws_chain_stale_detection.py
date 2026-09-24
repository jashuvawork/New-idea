"""WS overlay must refresh explosions on live LTPs; stale REST chain must force rebuild."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from app.models.schemas import AutoTraderState, MarketPhase, MultiSnapshot, SymbolSnapshot
from app.routers import market as market_router

IST = ZoneInfo("Asia/Kolkata")


def _sym_snap(*, age_seconds: float = 0.0) -> SymbolSnapshot:
    ts = datetime.now(IST) - timedelta(seconds=age_seconds)
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=ts,
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=50.0,
        heatmap=[],
    )


def test_chain_data_stale_when_symbol_timestamp_old():
    market_router._cache = None
    snaps = {"NIFTY": _sym_snap(age_seconds=200.0)}
    assert market_router.chain_data_stale(snaps) is True
    assert market_router.chain_data_stale({"NIFTY": _sym_snap(age_seconds=5.0)}) is False


def test_ws_overlay_refreshes_explosions_after_ltp_overlay():
    snap = _sym_snap(age_seconds=30.0)
    market_router._store_cache(
        MultiSnapshot(
            timestamp=datetime.now(IST),
            dataReady=True,
            snapshots={"NIFTY": snap},
            autoTrader=AutoTraderState(),
        ),
    )
    market_router._last_ws_overlay_mono = 0.0

    with (
        patch.object(market_router, "is_ws_active", return_value=True),
        patch.object(market_router, "ws_overlay_due", return_value=True),
        patch.object(
            market_router,
            "overlay_snapshot_live",
            return_value={"NIFTY": snap.model_copy(deep=False)},
        ) as overlay,
        patch.object(
            market_router,
            "_refresh_explosion_alerts_async",
            new_callable=AsyncMock,
        ) as refresh,
        patch.object(market_router, "_store_cache_async", new_callable=AsyncMock),
    ):
        asyncio.run(market_router.run_ws_overlay_cycle(broadcast=False))

    overlay.assert_called_once()
    refresh.assert_awaited_once()
    args, _kwargs = refresh.call_args
    assert args[0] is overlay.return_value


def test_entry_scan_forces_rebuild_when_chain_stale():
    old = _sym_snap(age_seconds=500.0)
    market_router._store_cache(
        MultiSnapshot(
            timestamp=datetime.now(IST),
            dataReady=True,
            snapshots={"NIFTY": old},
            autoTrader=AutoTraderState(),
        ),
    )

    with (
        patch.object(market_router, "rebuild_load_active", return_value=False),
        patch.object(
            market_router,
            "get_multi_snapshot",
            new_callable=AsyncMock,
            return_value=market_router._cache,
        ) as full,
    ):
        asyncio.run(market_router.run_entry_scan_on_cache(broadcast=False, run_trader=False))

    full.assert_awaited_once()
    assert full.call_args.kwargs.get("force") is True
