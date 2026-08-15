"""Upstox trade-manager dashboard API."""

from fastapi import APIRouter

from app.services.upstox import UpstoxClient
from app.services.upstox_trade_manager import build_upstox_trade_overview

router = APIRouter(prefix="/api/upstox-trading", tags=["upstox-trading"])


@router.get("/overview")
async def upstox_trading_overview():
    """Capital, allocation sleeves, broker positions/orders, and strategy P&L."""
    return await build_upstox_trade_overview(UpstoxClient())
