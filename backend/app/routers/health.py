"""Health and deployment status."""

from fastapi import APIRouter

from app.config import get_settings
from app.services.redis_store import has_upstox_token

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/api/deployment/status")
async def deployment_status():
    settings = get_settings()
    return {
        "status": "ok",
        "commit": settings.commit_sha,
        "environment": settings.environment,
        "upstox": {"hasToken": await has_upstox_token()},
        "flags": {
            "enableLiveTrading": settings.enable_live_trading,
            "paperTrading": settings.paper_trading,
            "simpleProfitMode": settings.paper_simple_profit_mode,
            "dualStrategyEnabled": settings.paper_dual_strategy_enabled,
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
    from app.routers.market import _build_multi_snapshot

    snapshot = await _build_multi_snapshot()
    return get_readiness(symbol.upper(), snapshot.snapshots)
