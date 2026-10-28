"""Full REST rebuild must not block the monitor / overlay loop."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.routers import market


def test_schedule_full_rest_rebuild_returns_immediately():
    """Sync wrapper — avoids requiring pytest-asyncio plugin."""

    async def _exercise():
        market._full_rest_task = None
        market._build_in_progress = False

        slow = asyncio.Event()

        async def _hang(**kwargs):
            await slow.wait()
            return MagicMock()

        with patch.object(market, "get_multi_snapshot", new=AsyncMock(side_effect=_hang)):
            started = market.schedule_full_rest_rebuild(broadcast=False, run_trader=False)
            assert started is True
            assert market.full_rest_rebuild_running() is True
            # Second schedule is a no-op while first runs
            assert market.schedule_full_rest_rebuild() is False

            slow.set()
            await market._full_rest_task
            assert market.full_rest_rebuild_running() is False

    asyncio.run(_exercise())


def test_full_rest_backoff_after_slow_cycle():
    market._last_full_rest_mono = 0.0
    market._last_full_cycle_ms = 93000.0
    settings = MagicMock()
    settings.full_rest_min_seconds = 45.0
    settings.full_rest_backoff_slow_ms = 15000.0
    settings.full_rest_backoff_seconds = 75.0
    with patch.object(market, "get_settings", return_value=settings):
        with patch.object(market.time, "monotonic", return_value=50.0):
            # 50s since last rest < 75s backoff → not due
            assert market.full_rest_rebuild_due() is False
        with patch.object(market.time, "monotonic", return_value=80.0):
            assert market.full_rest_rebuild_due() is True


def test_chain_refresh_does_not_run_a_second_trader_pass():
    async def _exercise():
        market._full_rest_task = None
        market._build_in_progress = False
        with patch.object(market, "get_multi_snapshot", new=AsyncMock()) as snap:
            started = market.schedule_chain_refresh(broadcast=False)
            assert started is True
            await market._full_rest_task
            snap.assert_awaited()
            assert snap.await_args.kwargs["run_trader"] is False

    asyncio.run(_exercise())


def test_overlapping_trader_pass_returns_without_waiting():
    from app.engines import auto_trader
    from app.models.schemas import AutoTraderState

    async def _exercise():
        auto_trader._process_running = False
        auto_trader._state_loaded = True
        auto_trader._auto_trader_state = AutoTraderState()
        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow(snapshots, news=None, client=None):
            started.set()
            await release.wait()
            return auto_trader.get_state()

        with patch.object(auto_trader, "_process_locked", side_effect=_slow):
            first = asyncio.create_task(auto_trader.process({}))
            await started.wait()
            second = await auto_trader.process({})
            assert second is auto_trader._auto_trader_state
            release.set()
            await first

        auto_trader._auto_trader_state = None
        auto_trader._state_loaded = False

    try:
        asyncio.run(_exercise())
    finally:
        auto_trader._process_running = False
        auto_trader._auto_trader_state = None
        auto_trader._state_loaded = False


def test_trader_pass_runs_again_on_a_new_event_loop():
    """A pass on one loop must not leave the next loop waiting."""
    from app.engines import auto_trader
    from app.models.schemas import AutoTraderState

    async def _once():
        auto_trader._state_loaded = True
        auto_trader._auto_trader_state = AutoTraderState()
        with patch.object(
            auto_trader,
            "_process_locked",
            new=AsyncMock(return_value=auto_trader._auto_trader_state),
        ):
            return await auto_trader.process({})

    try:
        auto_trader._process_running = False
        first = asyncio.run(_once())
        second = asyncio.run(_once())
        assert first is not None
        assert second is not None
        assert auto_trader._process_running is False
    finally:
        auto_trader._process_running = False
        auto_trader._auto_trader_state = None
        auto_trader._state_loaded = False
