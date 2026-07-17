"""Full REST rebuild must not block the monitor / overlay loop."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers import market


@pytest.mark.asyncio
async def test_schedule_full_rest_rebuild_returns_immediately():
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
