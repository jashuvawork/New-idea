"""Capital and risk profile API."""

from fastapi import APIRouter

from app.engines.auto_trader import set_capital
from app.engines.risk_engine import RiskEngine
from app.models.schemas import CapitalConfig, RiskProfile

router = APIRouter(prefix="/api", tags=["config"])

_risk = RiskEngine()


@router.post("/capital")
async def set_capital_endpoint(config: CapitalConfig):
    set_capital(config.allocatedInr)
    return {"status": "ok", **config.model_dump()}


@router.post("/risk/profile")
async def set_risk_profile(profile: RiskProfile):
    _risk.set_profile(profile)
    return {"status": "ok", **profile.model_dump()}


@router.get("/risk/status")
async def risk_status():
    return _risk.get_status()
