"""Execution control API."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.engines.auto_trader import get_state, resume_trading, stop_trading
from app.engines.realtime_engine import build_symbol_snapshot
from app.models.schemas import Side
from app.services.order_executor import place_entry_order
from app.services.upstox import UpstoxClient, UpstoxError

router = APIRouter(prefix="/api/execution", tags=["execution"])


class ScalpOrderRequest(BaseModel):
    symbol: str
    side: Side
    strike: float
    lots: int = 1
    order_type: str = "MARKET"


@router.post("/stop")
async def stop_auto_trading():
    stop_trading()
    return {"status": "stopped", "message": "Auto-trading halted — no new entries"}


@router.post("/resume")
async def resume_auto_trading():
    resume_trading()
    return {"status": "resumed", "message": "Auto-trading re-enabled"}


@router.get("/status")
async def execution_status():
    state = get_state()
    settings = get_settings()
    return {
        "running": state.running,
        "autoTradingEnabled": settings.auto_trading_enabled,
        "liveTradingEnabled": settings.enable_live_trading,
        "paperTrading": settings.paper_trading,
        "executionMode": "LIVE" if settings.enable_live_trading else "PAPER",
        "openTrades": len(state.openPaperTrades),
        "liveOrdersPlaced": state.liveOrdersPlaced,
        "lastEntry": state.lastEntry,
        "lastExit": state.lastExit,
        "skipped": state.skipped[-5:],
    }


@router.post("/scalp-order")
async def place_scalp_order(req: ScalpOrderRequest):
    settings = get_settings()
    if not settings.enable_live_trading:
        raise HTTPException(
            status_code=403,
            detail="Live trading disabled — set ENABLE_LIVE_TRADING=true",
        )

    client = UpstoxClient()
    try:
        snap = await build_symbol_snapshot(req.symbol.upper(), client)
        if not snap.dataAvailable:
            raise HTTPException(status_code=400, detail=snap.error or "Market data unavailable")
        result = await place_entry_order(
            client, snap, req.strike, req.side, req.lots, tag="nq_manual_scalp",
        )
        return {"status": "placed", "result": result}
    except UpstoxError as e:
        raise HTTPException(status_code=400, detail=str(e))
