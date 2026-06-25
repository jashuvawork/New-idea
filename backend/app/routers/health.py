"""Health and deployment status."""

from fastapi import APIRouter

from app.config import get_settings
from app.services.redis_store import has_upstox_token
from app.services.token_manager import get_daily_token_status

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/api/deployment/status")
async def deployment_status():
    settings = get_settings()
    token_status = await get_daily_token_status()
    return {
        "status": "ok",
        "commit": settings.commit_sha,
        "environment": settings.environment,
        "upstox": {
            "hasToken": await has_upstox_token(),
            "validToday": token_status.get("validToday", False),
            "canLogin": token_status.get("canLogin", True),
            "sessionDate": token_status.get("sessionDate"),
            "generatedAt": token_status.get("generatedAt"),
            "oneTimePerDay": settings.daily_token_once,
            "message": token_status.get("message", ""),
        },
        "flags": {
            "enableLiveTrading": settings.enable_live_trading,
            "autoTradingEnabled": settings.auto_trading_enabled,
            "paperTrading": settings.paper_trading,
            "simpleProfitMode": settings.paper_simple_profit_mode,
            "dualStrategyEnabled": settings.paper_dual_strategy_enabled,
            "explosionCaptureMode": settings.explosion_capture_mode,
            "swingTradingEnabled": settings.swing_trading_enabled,
            "dailyProfitTargetInr": settings.daily_profit_target_inr,
            "dailyProfitTrailInr": settings.daily_profit_trail_inr,
            "useUpstoxCapital": settings.use_upstox_capital_for_sizing,
            "perTradeCapitalPct": settings.per_trade_capital_pct,
            "aggressiveLotSizing": settings.aggressive_lot_sizing,
            "minOptionPremiumInr": settings.min_option_premium_inr,
            "maxOptionPremiumInr": settings.max_option_premium_inr,
            "enhancedMode": True,
            "shadowTradeAllSignals": settings.shadow_trade_all_signals,
            "backgroundMonitor": settings.background_market_monitor_enabled,
        },
        "cadence": {
            "marketPollSeconds": settings.market_poll_seconds,
            "snapshotCacheSeconds": settings.snapshot_cache_seconds,
        },
    }


@router.get("/api/institutional/readiness/{symbol}")
async def institutional_readiness(symbol: str):
    from app.engines.auto_trader import get_readiness
    from app.routers.market import get_multi_snapshot

    snapshot = await get_multi_snapshot()
    return get_readiness(symbol.upper(), snapshot.snapshots)
