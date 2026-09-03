"""NexusQuant FastAPI application."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import (
    ai,
    auto_trader,
    config,
    execution,
    health,
    market,
    playbook,
    signals,
    upstox_auth,
    upstox_trading,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

_background_task = None
_tick_wake = asyncio.Event()


async def _background_monitor():
    """Poll market even without UI open — tick-fast exits + periodic entry scans."""
    from app.routers.market import (
        can_run_tick_fast,
        entry_scan_due,
        full_rest_rebuild_due,
        full_rest_rebuild_running,
        get_multi_snapshot,
        invalidate_snapshot_cache,
        mark_full_rest_done,
        mark_full_scan_done,
        run_building_ltp_entry_cycle,
        run_entry_scan_on_cache,
        run_tick_fast_cycle,
        run_ws_overlay_cycle,
        schedule_full_rest_rebuild,
        ws_overlay_due,
    )
    from app.services.tick_store import set_tick_wake_event
    from app.services.upstox_ws import is_ws_active
    from app.services.upstox import (
        get_market_phase,
        rate_limit_active,
        rate_limit_recovery_active,
    )

    set_tick_wake_event(_tick_wake)
    try:
        from app.engines.index_tick_helpers import ensure_index_tick_observer

        ensure_index_tick_observer()
    except Exception:
        pass
    settings = get_settings()
    tick_driven = False
    last_composer_mono = 0.0
    last_analysis_mono = 0.0
    last_eod_playbook_date: Optional[str] = None
    last_radar_finalize_attempt_mono = 0.0
    last_eod_learning_date: Optional[str] = None

    while True:
        # Yield so /health and heartbeat can interleave under heavy sync work.
        await asyncio.sleep(0)
        poll_ms = (
            settings.market_poll_interval_ws_ms
            if is_ws_active()
            else settings.market_poll_interval_ms
        )
        debounce_s = max(0.01, settings.tick_wake_debounce_ms / 1000.0)

        try:
            if settings.background_market_monitor_enabled:
                rest_ok = (
                    not rate_limit_active()
                    and not rate_limit_recovery_active()
                )
                # Open positions: tick-fast exits + lightweight WS overlay only.
                # Do NOT run building_ltp/process on every tick — 20–35s cycles block
                # /snapshots/cached and freeze the UI at "Live cached 20s / fast 30s".
                if tick_driven and can_run_tick_fast():
                    await run_tick_fast_cycle(broadcast=False)
                    if is_ws_active() and ws_overlay_due():
                        await run_ws_overlay_cycle(broadcast=True)

                if entry_scan_due():
                    ws = is_ws_active()
                    if tick_driven and not ws:
                        invalidate_snapshot_cache()
                    if ws:
                        # Never await full REST on this loop — 30–90s builds freeze overlays.
                        if full_rest_rebuild_due() and not full_rest_rebuild_running():
                            schedule_full_rest_rebuild(
                                broadcast=True,
                                run_trader=rest_ok,
                            )
                        if full_rest_rebuild_running():
                            await run_building_ltp_entry_cycle(
                                broadcast=True,
                                run_trader=rest_ok,
                            )
                            if ws_overlay_due():
                                await run_ws_overlay_cycle(broadcast=True)
                        else:
                            await run_entry_scan_on_cache(
                                broadcast=True,
                                run_trader=rest_ok,
                            )
                            if rest_ok:
                                mark_full_scan_done()
                    else:
                        await get_multi_snapshot(
                            broadcast=True,
                            force=False,
                            run_trader=rest_ok,
                        )
                        mark_full_rest_done()
                        if rest_ok:
                            mark_full_scan_done()
                elif is_ws_active():
                    # Poll timeout between entry scans — catch BUILDING LTP moves.
                    await run_building_ltp_entry_cycle(
                        broadcast=True,
                        run_trader=rest_ok,
                    )
                    if ws_overlay_due():
                        await run_ws_overlay_cycle(broadcast=True)
                elif not tick_driven and not is_ws_active():
                    await get_multi_snapshot(broadcast=True, force=False)

            if (
                settings.composer_monitor_enabled
                and get_market_phase() == "LIVE_MARKET"
            ):
                from app.engines.composer_market_monitor import run_monitor_cycle

                now_mono = time.monotonic()
                if now_mono - last_composer_mono >= settings.composer_monitor_interval_seconds:
                    try:
                        from app.routers.market import get_multi_snapshot_fast

                        multi = await get_multi_snapshot_fast(overlay_ws=True)
                        if multi and multi.snapshots:
                            await run_monitor_cycle(multi.snapshots)
                            last_composer_mono = now_mono
                    except Exception as exc:
                        logger.warning("Composer monitor cycle error: %s", exc)

            if (
                settings.ai_analysis_monitor_enabled
                and get_market_phase() == "LIVE_MARKET"
            ):
                from app.engines.ai_market_analysis_monitor import run_analysis_cycle

                now_mono = time.monotonic()
                if now_mono - last_analysis_mono >= settings.ai_analysis_monitor_interval_seconds:
                    try:
                        from app.routers.market import get_multi_snapshot_fast

                        multi = await get_multi_snapshot_fast(overlay_ws=True)
                        if multi and multi.snapshots:
                            await run_analysis_cycle(multi.snapshots, source="interval")
                            last_analysis_mono = now_mono
                    except Exception as exc:
                        logger.warning("AI analysis monitor cycle error: %s", exc)

            if settings.eod_playbook_enabled and settings.background_market_monitor_enabled:
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
                            from app.routers.market import get_multi_snapshot_fast

                            multi = await get_multi_snapshot_fast(overlay_ws=False)
                            if multi and multi.snapshots:
                                await run_eod_playbook_cycle(
                                    multi.snapshots, get_state(), news=multi.news, force=False,
                                )
                                last_eod_playbook_date = target
                        except Exception as exc:
                            logger.warning("EOD playbook cycle error: %s", exc)

            if settings.radar_archive_enabled:
                radar_now = datetime.now(IST)
                radar_date = radar_now.strftime("%Y-%m-%d")
                finalize_due = (
                    radar_now.hour,
                    radar_now.minute,
                ) >= (
                    settings.radar_archive_finalize_hour,
                    settings.radar_archive_finalize_minute,
                )
                finalize_retry_due = (
                    time.monotonic() - last_radar_finalize_attempt_mono >= 300.0
                )
                if finalize_due and finalize_retry_due:
                    last_radar_finalize_attempt_mono = time.monotonic()
                    try:
                        from app.services.radar_archive import archive_path
                        from app.services.radar_learning import (
                            finalize_daily_review,
                            radar_review_is_current,
                        )

                        if (
                            archive_path(radar_date).exists()
                            and not radar_review_is_current(radar_date)
                        ):
                            await asyncio.to_thread(finalize_daily_review, radar_date)
                    except Exception as exc:
                        logger.warning("Daily radar finalization error: %s", exc)
                        try:
                            from app.services.radar_health import record_component_error

                            record_component_error("dailyRadarReview", exc)
                        except Exception:
                            pass

            # Automated EOD learning: distil today's FTV/V outcomes into the knowledge
            # profile once the archive is finalized, then prune raw archives past retention
            # (only for dates already learned). Runs once per day, after the finalize hour.
            if settings.eod_learning_enabled:
                learn_now = datetime.now(IST)
                learn_date = learn_now.strftime("%Y-%m-%d")
                learn_due = (learn_now.hour, learn_now.minute) >= (
                    settings.radar_archive_finalize_hour,
                    settings.radar_archive_finalize_minute,
                )
                if learn_due and last_eod_learning_date != learn_date:
                    try:
                        from app.engines.eod_ftv_learning import (
                            cleanup_learned_eod_archives,
                            run_eod_learning_cycle,
                        )

                        res = await asyncio.to_thread(run_eod_learning_cycle, learn_date)
                        if res.get("status") in ("learned", "already_learned", "no_data"):
                            last_eod_learning_date = learn_date
                            await asyncio.to_thread(cleanup_learned_eod_archives)
                    except Exception as exc:
                        logger.warning("EOD FTV learning error: %s", exc)
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
    from app.loop_watchdog import start_loop_watchdog, stop_loop_watchdog
    from app.services.upstox_ws import start_upstox_ws, stop_upstox_ws

    try:
        from app.services.radar_learning import (
            record_pipeline_event,
            restore_local_base_history,
        )

        restored = await asyncio.to_thread(restore_local_base_history)
        await asyncio.to_thread(
            record_pipeline_event,
            "SERVICE_START",
            source="lifespan",
            detail={
                "commit": str(getattr(settings, "commit_sha", "") or "")[:12],
                "localBaseRestore": restored,
                "backgroundMonitorEnabled": settings.background_market_monitor_enabled,
                "upstoxWsEnabled": settings.upstox_ws_enabled,
            },
        )
    except Exception as exc:
        logger.warning("Radar startup history recovery error: %s", exc)
    try:
        from app.engines.capital_allocator import (
            ensure_paper_sizing_capital,
            should_use_live_broker_capital,
        )

        if should_use_live_broker_capital():
            logger.info("Live broker capital sizing enabled — Upstox margin on first refresh")
        else:
            snap = ensure_paper_sizing_capital()
            logger.info(
                "Paper sizing capital initialized: ₹%.0f (source=%s)",
                snap.availableMarginInr,
                snap.source,
            )
    except Exception as exc:
        logger.warning("Capital sizing initialization error: %s", exc)
    if settings.upstox_ws_enabled:
        await start_upstox_ws()
        logger.info("Upstox WebSocket feed enabled (mode=%s)", settings.upstox_ws_mode)
    if settings.radar_archive_enabled:
        try:
            from app.services.radar_learning import finalize_pending_reviews

            recovered = await asyncio.to_thread(finalize_pending_reviews)
            if recovered:
                logger.info("Finalized %d pending radar review archive(s)", len(recovered))
        except Exception as exc:
            logger.warning("Pending radar archive recovery error: %s", exc)
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
    start_loop_watchdog(
        enabled=bool(getattr(settings, "event_loop_watchdog_enabled", True)),
        stale_seconds=float(
            getattr(settings, "event_loop_watchdog_stale_seconds", 20.0) or 20.0
        ),
        check_seconds=float(
            getattr(settings, "event_loop_watchdog_check_seconds", 2.0) or 2.0
        ),
        beat_interval_seconds=float(
            getattr(settings, "event_loop_watchdog_beat_interval_seconds", 1.0)
            or 1.0
        ),
        grace_seconds=float(
            getattr(settings, "event_loop_watchdog_grace_seconds", 45.0) or 45.0
        ),
    )
    yield
    stop_loop_watchdog()
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
    app.include_router(upstox_trading.router)
    app.include_router(config.router)
    app.include_router(upstox_auth.router)
    app.include_router(ai.router)
    app.include_router(signals.router)
    app.include_router(playbook.router)

    return app


app = create_app()
