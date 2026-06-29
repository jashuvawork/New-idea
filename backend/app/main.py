"""NexusQuant FastAPI application."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import ai, auto_trader, config, execution, health, market, upstox_auth

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_background_task = None
_tick_wake = asyncio.Event()


async def _background_monitor():
    """Poll market even without UI open — wake early on WebSocket ticks."""
    from app.routers.market import get_multi_snapshot
    from app.services.tick_store import set_tick_wake_event
    from app.services.upstox_ws import is_ws_active

    set_tick_wake_event(_tick_wake)
    settings = get_settings()
    tick_driven = False

    while True:
        poll_ms = (
            settings.market_poll_interval_ws_ms
            if is_ws_active()
            else settings.market_poll_interval_ms
        )
        debounce_s = max(0.05, settings.tick_wake_debounce_ms / 1000.0)

        try:
            if settings.background_market_monitor_enabled:
                if tick_driven:
                    from app.routers.market import invalidate_snapshot_cache
                    invalidate_snapshot_cache()
                await get_multi_snapshot(broadcast=True, force=tick_driven)
        except Exception as e:
            logger.warning("Background monitor error: %s", e)

        tick_driven = False
        _tick_wake.clear()
        try:
            await asyncio.wait_for(_tick_wake.wait(), timeout=poll_ms / 1000.0)
            while True:
                try:
                    await asyncio.wait_for(_tick_wake.wait(), timeout=debounce_s)
                    _tick_wake.clear()
                except asyncio.TimeoutError:
                    break
            tick_driven = True
        except asyncio.TimeoutError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _background_task
    settings = get_settings()
    from app.services.upstox_ws import start_upstox_ws, stop_upstox_ws

    if settings.upstox_ws_enabled:
        await start_upstox_ws()
        logger.info("Upstox WebSocket feed enabled (mode=%s)", settings.upstox_ws_mode)
    if settings.background_market_monitor_enabled:
        _background_task = asyncio.create_task(_background_monitor())
        logger.info(
            "Background market monitor started (poll=%dms, ws_poll=%dms, tick_wake=%dms)",
            settings.market_poll_interval_ms,
            settings.market_poll_interval_ws_ms,
            settings.tick_wake_debounce_ms,
        )
    yield
    if _background_task:
        _background_task.cancel()
    await stop_upstox_ws()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description="Institutional-style Indian index options scalping terminal",
        version="2.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(market.router)
    app.include_router(execution.router)
    app.include_router(auto_trader.router)
    app.include_router(config.router)
    app.include_router(upstox_auth.router)
    app.include_router(ai.router)

    return app


app = create_app()
