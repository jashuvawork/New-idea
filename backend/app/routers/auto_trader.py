"""Auto-trader status and reporting API."""

from fastapi import APIRouter

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
