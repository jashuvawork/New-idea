"""Auto-trader status and reporting API."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.engines.auto_trader import (
    entries_execution_active,
    get_performance_analysis,
    get_readiness,
    get_state,
    reset_session,
    set_capital,
)
from app.models.schemas import CapitalConfig
from app.services import trade_store

router = APIRouter(prefix="/api/auto-trader", tags=["auto-trader"])

@router.get("/status")
async def auto_trader_status():
    state = get_state()
    try:
        from app.routers import market as market_router

        cache = getattr(market_router, "_cache", None)
        snaps = dict(cache.snapshots) if cache and cache.snapshots else {}
    except Exception:
        snaps = {}
    from app.engines.sep917_live_checklist import attach_sep917_checklist_to_chop_guards

    attach_sep917_checklist_to_chop_guards(state, snaps)
    payload = state.model_dump(mode="json")
    payload["running"] = entries_execution_active(state)
    return payload


@router.get("/daily-report")
async def daily_report():
    return get_state().dailyReport


@router.get("/performance-analysis")
async def performance_analysis():
    return get_performance_analysis()


@router.get("/milestone")
async def performance_milestone():
    """50-trade live readiness per rolling batch: PF 3+, WR 50%+, max DD 5%."""
    from app.engines.performance_milestone import compute_milestone_stats

    return compute_milestone_stats()


@router.get("/batches")
async def milestone_batches(limit: int = 20):
    """Archived 50-trade batch summaries (batch 1, 2, 3…)."""
    return {
        "batchSize": trade_store.MILESTONE_BATCH_SIZE,
        "batches": trade_store.list_milestone_batches(limit=min(limit, 50)),
    }


@router.post("/milestone/reset")
async def reset_milestone_batch(reason: str = "manual_reset"):
    """Archive current milestone window and start fresh 0/50 batch (keeps trade logs)."""
    from app.engines.auto_trader import reset_session_calibration

    result = trade_store.reset_milestone_batch(reason=reason)
    reset_session_calibration()
    from app.engines.performance_milestone import compute_milestone_stats

    return {
        "status": "reset",
        "message": "Milestone batch reset — new 50-trade window started",
        "reset": result,
        "milestone": compute_milestone_stats(),
    }


@router.post("/reset")
async def reset_paper_session():
    reset_session()
    return {
        "status": "reset",
        "message": "Calibration blocks cleared; open trades preserved",
    }


@router.post("/purge-logs")
async def purge_trade_logs():
    """Wipe all trade archives + log, reset session and milestone — unblocks stale gates."""
    from app.engines.auto_trader import reset_session_calibration
    from app.engines.performance_milestone import compute_milestone_stats

    purge = trade_store.purge_all_trade_data()
    reset_session(preserve_open_trades=False)
    reset_session_calibration()
    return {
        "status": "purged",
        "message": "All trade logs removed; session and gates cleared",
        "purge": purge,
        "milestone": compute_milestone_stats(),
    }


@router.post("/capital")
async def set_trading_capital(config: CapitalConfig):
    set_capital(config.allocatedInr)
    return {"status": "ok", "allocatedInr": config.allocatedInr}


@router.get("/history")
async def trade_history(days: int = 30):
    """Daily paper trade summaries for learning and review."""
    store_health = trade_store.check_store_health()
    return {
        "days": trade_store.get_history(days=min(days, 90)),
        "storeDir": store_health["storeDir"],
        "logFile": store_health["logFile"],
        "logSizeBytes": store_health["logSizeBytes"],
    }


@router.get("/log")
async def trade_log_tail(limit: int = 50):
    """Recent append-only trade log entries (paper + live)."""
    return {
        "logFile": str(trade_store.get_log_path()),
        "entries": trade_store.get_recent_log_lines(limit=min(limit, 500)),
    }


@router.get("/weekly-dashboard")
async def weekly_dashboard(days: int = 5):
    """Weekly review (Mon–Fri trading week) — trades, skips, expectancy, goals."""
    from app.engines.auto_trader import get_state
    from app.engines.weekly_dashboard import build_weekly_dashboard
    from app.routers.market import get_multi_snapshot

    state = get_state()
    snapshots: dict = {}
    try:
        payload = await get_multi_snapshot()
        snapshots = payload.snapshots or {}
    except Exception:
        snapshots = {}

    return build_weekly_dashboard(days=min(max(days, 1), 30), state=state, snapshots=snapshots)


@router.get("/history/{date}")
async def trade_history_day(date: str):
    """Full trade + event log for a specific IST session date (YYYY-MM-DD)."""
    if len(date) != 10 or date[4] != "-" or date[7] != "-":
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD")
    return trade_store.get_day_detail(date)


@router.get("/trade-archives")
async def trade_archives(limit: int = 90):
    """List daily paper+live trade ZIP archives (survives purge-logs)."""
    return {"archives": trade_store.list_trade_archives(limit=min(max(limit, 1), 365))}


@router.get("/trade-archives/{date}")
async def download_trade_archive(date: str):
    """Download trades-YYYY-MM-DD.zip for one session."""
    if len(date) != 10 or date[4] != "-" or date[7] != "-":
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD")
    try:
        path = trade_store.trade_archive_path(date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Trade archive not found — finalize runs at 16:00 IST or POST /api/ai/radar-finalize/{date}",
        )
    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name,
    )


@router.post("/trade-archives/{date}/build")
async def build_trade_archive(date: str):
    """Build or refresh the daily trade ZIP (admin/recovery)."""
    if len(date) != 10 or date[4] != "-" or date[7] != "-":
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD")
    import asyncio

    return await asyncio.to_thread(trade_store.finalize_daily_trades_archive, date)


@router.get("/history/trades/closed")
async def closed_trades_archive(limit: int = 100):
    """All closed paper trades across days, newest first."""
    return {"trades": trade_store.get_all_closed_trades(limit=min(limit, 500))}
