"""Forward signals API — future moments and trade setups."""

from fastapi import APIRouter

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("/forward")
async def forward_signals():
    """Unified forward-looking dashboard: moments, explosions, swings, risk."""
    from app.engines.auto_trader import get_state
    from app.engines.forward_signals_engine import build_forward_signals
    from app.routers.market import get_multi_snapshot

    multi = await get_multi_snapshot(force=False)
    return build_forward_signals(multi.snapshots, get_state())
