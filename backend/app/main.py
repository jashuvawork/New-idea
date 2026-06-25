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


async def _background_monitor():
    """Poll market even without UI open."""
    settings = get_settings()
    while True:
        poll = settings.market_poll_seconds
        try:
            if settings.background_market_monitor_enabled:
                from app.routers.market import get_multi_snapshot
                from app.services.upstox_ws import is_ws_active

                await get_multi_snapshot(broadcast=True)
                if is_ws_active():
                    poll = settings.market_poll_seconds_ws
        except Exception as e:
            logger.warning("Background monitor error: %s", e)
        await asyncio.sleep(poll)


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
        logger.info("Background market monitor started (poll=%ds)", settings.market_poll_seconds)
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
