"""NexusQuant FastAPI application."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import ai, auto_trader, config, execution, health, market, playbook, signals, upstox_auth

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_background_task = None
_tick_wake = asyncio.Event()


async def _background_monitor():
    """Poll market even without UI open — tick-fast exits + periodic entry scans."""
    from app.routers.market import (
        can_run_tick_fast,
        entry_scan_due,
        get_multi_snapshot,
        invalidate_snapshot_cache,
        run_tick_fast_cycle,
    )
    from app.services.tick_store import set_tick_wake_event
    from app.services.upstox_ws import is_ws_active
    from app.services.upstox import (
        get_market_phase,
        rate_limit_active,
        rate_limit_recovery_active,
    )

    set_tick_wake_event(_tick_wake)
    settings = get_settings()
    tick_driven = False
    last_composer_mono = 0.0
    last_analysis_mono = 0.0
    last_eod_playbook_date: Optional[str] = None

    while True:
        poll_ms = (
            settings.market_poll_interval_ws_ms
            if is_ws_active()
            else settings.market_poll_interval_ms
        )
        debounce_s = max(0.01, settings.tick_wake_debounce_ms / 1000.0)

        try:
            if settings.background_market_monitor_enabled:
                if tick_driven and can_run_tick_fast():
                    await run_tick_fast_cycle(broadcast=True)
                elif entry_scan_due():
                    ws = is_ws_active()
                    # Tick-fast exits use WS LTP overlay — don't bust REST cache on every tick wake
                    if tick_driven and not ws:
                        invalidate_snapshot_cache()
                    rest_ok = not rate_limit_active() and not rate_limit_recovery_active()
                    await get_multi_snapshot(
                        broadcast=True,
                        force=rest_ok and not ws,
                    )
                elif not tick_driven:
                    await get_multi_snapshot(broadcast=True, force=False)

            if (
                settings.composer_monitor_enabled
                and get_market_phase() == "LIVE_MARKET"
            ):
                import time
                from app.engines.composer_market_monitor import run_monitor_cycle

                now_mono = time.monotonic()
                if now_mono - last_composer_mono >= settings.composer_monitor_interval_seconds:
                    try:
                        multi = await get_multi_snapshot(broadcast=False, force=False)
                        if multi and multi.snapshots:
                            await run_monitor_cycle(multi.snapshots)
                            last_composer_mono = now_mono
                    except Exception as exc:
                        logger.warning("Composer monitor cycle error: %s", exc)

            if (
                settings.ai_analysis_monitor_enabled
                and get_market_phase() == "LIVE_MARKET"
            ):
                import time
                from app.engines.ai_market_analysis_monitor import run_analysis_cycle

                now_mono = time.monotonic()
                if now_mono - last_analysis_mono >= settings.ai_analysis_monitor_interval_seconds:
                    try:
                        multi = await get_multi_snapshot(broadcast=False, force=False)
                        if multi and multi.snapshots:
                            await run_analysis_cycle(multi.snapshots, source="interval")
                            last_analysis_mono = now_mono
                    except Exception as exc:
                        logger.warning("AI analysis monitor cycle error: %s", exc)

            if settings.eod_playbook_enabled and settings.background_market_monitor_enabled:
                import time
                from app.engines.eod_playbook_engine import (
                    in_eod_playbook_window,
                    next_trading_day,
                    run_eod_playbook_cycle,
                )
                from app.engines.auto_trader import get_state

                if in_eod_playbook_window():
                    target = next_trading_day()
                    if last_eod_playbook_date != target:
                        try:
                            multi = await get_multi_snapshot(broadcast=False, force=False)
                            if multi and multi.snapshots:
                                await run_eod_playbook_cycle(
                                    multi.snapshots, get_state(), force=False,
                                )
                                last_eod_playbook_date = target
                        except Exception as exc:
                            logger.warning("EOD playbook cycle error: %s", exc)
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
            "Background monitor: latency=%s tick_fast=%s entry_scan_ms=%d debounce_ms=%d composer=%s analysis=%s",
            settings.latency_mode,
            settings.tick_fast_exit_enabled,
            settings.entry_scan_interval_ms,
            settings.tick_wake_debounce_ms,
            settings.composer_monitor_enabled,
            settings.ai_analysis_monitor_enabled,
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
    app.include_router(signals.router)
    app.include_router(playbook.router)

    return app


app = create_app()
