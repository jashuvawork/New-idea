"""Execution control API."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.engines.auto_trader import resume_trading, stop_trading
from app.models.schemas import Side
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
        result = await client.place_order({
            "quantity": req.lots,
            "product": "I",
            "validity": "DAY",
            "price": 0,
            "tag": "nexusquant_scalp",
            "instrument_token": f"{req.symbol}_{req.strike}_{req.side.value}",
            "order_type": req.order_type,
            "transaction_type": "BUY",
            "disclosed_quantity": 0,
            "trigger_price": 0,
            "is_amo": False,
        })
        return {"status": "placed", "result": result}
    except UpstoxError as e:
        raise HTTPException(status_code=400, detail=str(e))
