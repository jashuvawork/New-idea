"""Auto-trader status and reporting API."""

from fastapi import APIRouter

from fastapi import HTTPException

from app.engines.auto_trader import (
    get_performance_analysis,
    get_readiness,
    get_state,
    reset_session,
    set_capital,
)
from app.engines.risk_engine import RiskEngine
from app.models.schemas import CapitalConfig, RiskProfile
from app.routers.market import _build_multi_snapshot
from app.services import trade_store

router = APIRouter(prefix="/api/auto-trader", tags=["auto-trader"])

_risk = RiskEngine()


@router.get("/status")
async def auto_trader_status():
    return get_state()


@router.get("/daily-report")
async def daily_report():
    return get_state().dailyReport


@router.get("/performance-analysis")
async def performance_analysis():
    return get_performance_analysis()


@router.post("/reset")
async def reset_paper_session():
    reset_session()
    return {"status": "reset", "message": "Paper session and calibration blocks cleared"}


@router.post("/capital")
async def set_trading_capital(config: CapitalConfig):
    set_capital(config.allocatedInr)
    return {"status": "ok", "allocatedInr": config.allocatedInr}


@router.get("/history")
async def trade_history(days: int = 30):
    """Daily paper trade summaries for learning and review."""
    return {
        "days": trade_store.get_history(days=min(days, 90)),
        "storeDir": str(trade_store.get_store_dir()),
    }


@router.get("/history/{date}")
async def trade_history_day(date: str):
    """Full trade + event log for a specific IST session date (YYYY-MM-DD)."""
    if len(date) != 10 or date[4] != "-" or date[7] != "-":
        raise HTTPException(status_code=400, detail="Date must be YYYY-MM-DD")
    return trade_store.get_day_detail(date)


@router.get("/history/trades/closed")
async def closed_trades_archive(limit: int = 100):
    """All closed paper trades across days, newest first."""
    return {"trades": trade_store.get_all_closed_trades(limit=min(limit, 500))}
