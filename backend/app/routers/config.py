"""Capital and risk profile API."""

from fastapi import APIRouter

from app.engines.auto_trader import get_risk_engine, set_capital
from app.models.schemas import CapitalConfig, RiskProfile

router = APIRouter(prefix="/api", tags=["config"])

@router.post("/capital")
async def set_capital_endpoint(config: CapitalConfig):
    set_capital(config.allocatedInr)
    from app.engines.capital_risk_limits import capital_risk_limits_summary

    return {
        "status": "ok",
        **config.model_dump(),
        "capitalRiskLimits": capital_risk_limits_summary(),
    }


@router.post("/risk/profile")
async def set_risk_profile(profile: RiskProfile):
    get_risk_engine().set_profile(profile)
    return {"status": "ok", **profile.model_dump()}


@router.get("/risk/status")
async def risk_status():
    return get_risk_engine().get_status()
