"""Health and deployment status."""

from fastapi import APIRouter

from app.config import get_settings
from app.engines.capital_allocator import get_lot_sizes_meta
from app.engines.paper_slippage import config_summary as slippage_config_summary
from app.services import trade_store
from app.services.redis_store import has_upstox_token
from app.services.token_manager import get_daily_token_status
from app.services.upstox import get_market_phase
from app.services.upstox_ws import ws_status

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/api/deployment/status")
async def deployment_status():
    settings = get_settings()
    token_status = await get_daily_token_status()
    store_health = trade_store.check_store_health()
    today_counts = trade_store.count_today_trades()
    return {
        "status": "ok",
        "commit": settings.commit_sha,
        "environment": settings.environment,
        "upstox": {
            "hasToken": await has_upstox_token(),
            "validToday": token_status.get("validToday", False),
            "expired": token_status.get("expired", False),
            "canLogin": token_status.get("canLogin", True),
            "sessionDate": token_status.get("sessionDate"),
            "generatedAt": token_status.get("generatedAt"),
            "expiresAt": token_status.get("expiresAt"),
            "recommendedLoginAfter": token_status.get("recommendedLoginAfter"),
            "oneTimePerDay": settings.daily_token_once,
            "message": token_status.get("message", ""),
        },
        "flags": {
            "symbols": settings.symbols,
            "enableLiveTrading": settings.enable_live_trading,
            "autoTradingEnabled": settings.auto_trading_enabled,
            "paperTrading": settings.paper_trading,
            "simpleProfitMode": settings.paper_simple_profit_mode,
            "dualStrategyEnabled": settings.paper_dual_strategy_enabled,
            "explosionCaptureMode": settings.explosion_capture_mode,
            "swingTradingEnabled": settings.swing_trading_enabled,
            "dailyProfitTargetInr": settings.daily_profit_target_inr,
            "dailyProfitTrailInr": settings.daily_profit_trail_inr,
            "dailyProfitStageLocksEnabled": settings.daily_profit_stage_locks_enabled,
            "dailyProfitStagePcts": settings.daily_profit_stage_pcts(),
            "perTradeCapitalPct": settings.per_trade_capital_pct,
            "fallbackCapitalInr": settings.fallback_capital_inr,
            "maxSizingCapitalInr": settings.max_sizing_capital_inr,
            "aggressiveLotSizing": settings.aggressive_lot_sizing,
            "maxLotsPerTrade": settings.max_lots_per_trade,
            "entryEarliestIst": f"{settings.entry_earliest_hour:02d}:{settings.entry_earliest_minute:02d}",
            "openCautionUntilIst": f"{settings.open_caution_until_hour:02d}:{settings.open_caution_until_minute:02d}",
            "openCautionMinExplosionScore": settings.open_caution_min_explosion_score,
            "aggressiveMinExplosionScore": settings.aggressive_min_explosion_score,
            "enhancedVelocityThreshold": settings.enhanced_velocity_threshold,
            "enhancedTqsEntry": settings.enhanced_tqs_entry,
            "runnerAlignmentOverrideScore": settings.runner_alignment_override_score,
            "explosionReentryCooldownSeconds": settings.explosion_reentry_cooldown_seconds,
            "explosionEmergencyCooldownSeconds": settings.explosion_emergency_cooldown_seconds,
            "useUpstoxCapital": settings.use_upstox_capital_for_sizing,
            "minOptionPremiumInr": settings.min_option_premium_inr,
            "maxOptionPremiumInr": settings.max_option_premium_inr,
            "enhancedMode": True,
            "shadowTradeAllSignals": settings.shadow_trade_all_signals,
            "backgroundMonitor": settings.background_market_monitor_enabled,
            "paperSlippageEnabled": settings.paper_slippage_enabled,
            "paperLiveParityEnabled": settings.paper_live_parity_enabled,
        },
        "paperSlippage": slippage_config_summary(),
        "cadence": {
            "marketPollSeconds": settings.market_poll_seconds,
            "snapshotCacheSeconds": settings.snapshot_cache_seconds,
            "tickSnapshotSeconds": settings.tick_snapshot_seconds,
            "marketPollSecondsWs": settings.market_poll_seconds_ws,
            "sseEnabled": settings.sse_enabled,
        },
        "websocket": ws_status(),
        "tradeLog": {
            "storeDir": store_health["storeDir"],
            "logFile": store_health["logFile"],
            "logSizeBytes": store_health["logSizeBytes"],
            "writable": store_health["checks"]["healthy"],
            "todayOpen": today_counts["open"],
            "todayClosed": today_counts["closed"],
        },
        **get_lot_sizes_meta(),
    }


@router.get("/api/deployment/readiness")
async def deployment_readiness():
    """Live deployment checklist — paper log + broker + risk gates."""
    from app.engines.auto_trader import get_state
    from app.engines.risk_engine import RiskEngine
    from app.routers.market import get_multi_snapshot

    settings = get_settings()
    token_status = await get_daily_token_status()
    store_health = trade_store.check_store_health()
    risk = RiskEngine()
    state = get_state()

    market_live = False
    upstox_data = False
    try:
        snapshot = await get_multi_snapshot()
        for sym in settings.symbols:
            snap = snapshot.snapshots.get(sym)
            if snap and snap.dataAvailable:
                upstox_data = True
            if snap and getattr(snap.marketPhase, "value", snap.marketPhase) == "LIVE_MARKET":
                market_live = True
    except Exception:
        pass

    if not market_live:
        market_live = get_market_phase() == "LIVE_MARKET"

    checks = {
        "upstoxTokenValid": bool(token_status.get("validToday")),
        "upstoxDataReady": upstox_data,
        "marketLive": market_live,
        "tradeStoreWritable": store_health["checks"]["healthy"],
        "autoTradingEnabled": settings.auto_trading_enabled,
        "riskEngineOk": not risk.safe_mode,
        "calibrationClear": not any(state.calibrationBlocks.values()),
        "liveTradingFlagSet": settings.enable_live_trading,
        "paperTradingActive": settings.paper_trading,
    }

    paper_ready = all([
        checks["upstoxTokenValid"],
        checks["tradeStoreWritable"],
        checks["autoTradingEnabled"],
        checks["riskEngineOk"],
    ])

    live_ready = all([
        checks["upstoxTokenValid"],
        checks["upstoxDataReady"],
        checks["tradeStoreWritable"],
        checks["autoTradingEnabled"],
        checks["riskEngineOk"],
        checks["calibrationClear"],
        settings.enable_live_trading,
    ])

    arm_live_steps = []
    if not checks["upstoxTokenValid"]:
        arm_live_steps.append("Login to Upstox (valid IST-day token required)")
    if not checks["upstoxDataReady"]:
        arm_live_steps.append("Wait for market data snapshots to load")
    if not checks["tradeStoreWritable"]:
        arm_live_steps.append(f"Fix trade store permissions at {store_health['storeDir']}")
    if not checks["riskEngineOk"]:
        arm_live_steps.append("Clear risk engine safe mode")
    if not checks["calibrationClear"]:
        arm_live_steps.append("Clear calibration blocks or reset session")
    if not settings.enable_live_trading:
        arm_live_steps.append("Set ENABLE_LIVE_TRADING=true in env and redeploy")

    from app.engines.performance_milestone import compute_milestone_stats
    milestone = compute_milestone_stats()
    checks["milestonePassed"] = milestone["readyForLiveMilestone"]
    if not milestone["readyForLiveMilestone"]:
        arm_live_steps.append(milestone["message"])

    return {
        "readyForPaper": paper_ready,
        "readyForLive": live_ready and milestone["readyForLiveMilestone"],
        "executionMode": "LIVE" if settings.enable_live_trading else "PAPER",
        "checks": checks,
        "milestone": milestone,
        "tradeLog": {
            "storeDir": store_health["storeDir"],
            "logFile": store_health["logFile"],
            "logSizeBytes": store_health["logSizeBytes"],
            "todayCounts": trade_store.count_today_trades(),
        },
        "armLiveSteps": arm_live_steps,
        "openTrades": len(state.openPaperTrades),
    }


@router.get("/api/institutional/readiness/{symbol}")
async def institutional_readiness(symbol: str):
    from app.engines.auto_trader import get_readiness
    from app.routers.market import get_multi_snapshot

    snapshot = await get_multi_snapshot()
    return get_readiness(symbol.upper(), snapshot.snapshots)
