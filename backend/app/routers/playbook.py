"""EOD next-day playbook API."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/playbook", tags=["playbook"])


@router.get("/tomorrow/status")
async def tomorrow_playbook_status():
    from app.engines.eod_playbook_engine import monitor_status

    return monitor_status()


@router.get("/tomorrow")
async def tomorrow_playbook():
    """Next-session EOD playbook for upcoming trading day."""
    from app.engines.eod_playbook_engine import get_latest_eod_playbook, next_trading_day
    from app.services import trade_store

    target = next_trading_day()
    stored = trade_store.get_eod_playbook(target)
    latest = get_latest_eod_playbook()
    playbook = stored or latest
    if not playbook:
        return {
            "waiting": True,
            "targetDate": target,
            "summary": "No EOD playbook yet — generates after 15:20 IST or use POST /tomorrow/refresh",
        }
    return playbook


@router.get("/tomorrow/history")
async def tomorrow_playbook_history(limit: int = 7):
    from app.services import trade_store

    return {"playbooks": trade_store.get_eod_playbook_history(limit=min(limit, 14))}


@router.post("/tomorrow/refresh")
async def tomorrow_playbook_refresh():
    """Force generate next-day EOD playbook (rules + Composer when API key set)."""
    from app.engines.auto_trader import get_state
    from app.engines.eod_playbook_engine import run_eod_playbook_cycle
    from app.routers.market import get_multi_snapshot
    from app.services.upstox import rate_limit_active, rate_limit_recovery_active

    force_rest = not rate_limit_active() and not rate_limit_recovery_active()
    multi = await get_multi_snapshot(force=force_rest)
    return await run_eod_playbook_cycle(multi.snapshots, get_state(), force=True)
