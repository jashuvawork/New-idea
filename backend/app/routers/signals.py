"""Forward signals API — future moments and trade setups."""

import logging

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("/forward")
async def forward_signals():
    """Unified forward-looking dashboard: moments, explosions, swings, risk."""
    from app.engines.auto_trader import get_state
    from app.engines.forward_signals_engine import build_forward_signals
    from app.routers.market import get_multi_snapshot_fast

    try:
        multi = await get_multi_snapshot_fast()
        return build_forward_signals(multi.snapshots, get_state())
    except Exception:
        logger.exception("forward_signals failed")
        raise HTTPException(status_code=500, detail="forward_signals_build_failed")


@router.get("/ftv-probability")
async def ftv_probability():
    """Upstox-backed historical and live CE/PE time-to-breakout advisory."""
    from app.engines.ftv_probability import build_ftv_probability_dashboard
    from app.routers.market import get_multi_snapshot_fast

    try:
        multi = await get_multi_snapshot_fast()
        return await build_ftv_probability_dashboard(multi.snapshots)
    except Exception:
        logger.exception("ftv_probability failed")
        raise HTTPException(status_code=500, detail="ftv_probability_build_failed")


@router.get("/strike-watchlist")
async def strike_watchlist(per_side: int = 3):
    """CE + PE priority strikes for NIFTY and SENSEX — live trade-priority board."""
    from app.engines.strike_watchlist import build_strike_watchlist
    from app.routers.market import get_multi_snapshot_fast

    try:
        multi = await get_multi_snapshot_fast()
        payload = build_strike_watchlist(
            multi.snapshots,
            per_side=max(1, min(int(per_side or 3), 6)),
        )
        payload["live"] = True
        return payload
    except Exception:
        logger.exception("strike_watchlist failed")
        raise HTTPException(status_code=500, detail="strike_watchlist_build_failed")
