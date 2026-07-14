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
