"""Health and deployment status."""

from fastapi import APIRouter

from app.config import get_settings
from app.engines.capital_allocator import get_lot_sizes_meta
from app.engines.paper_slippage import config_summary as slippage_config_summary
from app.services import trade_store
from app.services.redis_store import has_upstox_token
from app.services.token_manager import get_daily_token_status
from app.services.upstox import (
    clear_rate_limit_cooldown,
    get_market_phase,
    rate_limit_active,
    rate_limit_cooldown_remaining,
)
from app.services.upstox_ws import ws_status
from app.routers.market import latency_stats

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
            "emergencyStopEnabled": settings.emergency_stop_enabled,
            "emergencyStopInr": settings.emergency_stop_inr,
            "emergencyStopScaleWithPosition": settings.emergency_stop_scale_with_position,
            "scalpStopPoints": settings.scalp_stop_points,
            "explosionInitialStopPoints": settings.explosion_initial_stop_points,
            "entryEarliestIst": f"{settings.entry_earliest_hour:02d}:{settings.entry_earliest_minute:02d}",
            "openCautionUntilIst": f"{settings.open_caution_until_hour:02d}:{settings.open_caution_until_minute:02d}",
            "openCautionMinExplosionScore": settings.open_caution_min_explosion_score,
            "aggressiveMinExplosionScore": settings.aggressive_min_explosion_score,
            "explosionConfirmedMinScore": settings.explosion_confirmed_min_score,
            "explosionTargetStandard": settings.explosion_target_standard,
            "explosionMicroTargetPoints": settings.explosion_micro_target_points,
            "explosionTrailArmPoints": settings.explosion_trail_arm_points,
            "explosionMaxLots": settings.explosion_max_lots,
            "scalpMaxLots": settings.scalp_max_lots,
            "scalpTargetPoints": settings.scalp_target_points,
            "bullishHoldEnabled": settings.bullish_hold_enabled,
            "chopDayGuardsEnabled": settings.chop_day_guards_enabled,
            "fetchConstituentsInSnapshot": settings.fetch_constituents_in_snapshot,
            "indexMomentumEnabled": settings.index_momentum_enabled,
            "dailyLossStopInr": settings.daily_loss_stop_inr,
            "dailyMaxTradesChop": settings.daily_max_trades_chop,
            "primaryWindowStartIst": f"{settings.primary_window_start_hour:02d}:{settings.primary_window_start_minute:02d}",
            "sureShotModeEnabled": settings.sure_shot_mode_enabled,
            "rapidScalpModeEnabled": settings.rapid_scalp_mode_enabled,
            "quickSidewaysEnabled": settings.quick_sideways_enabled,
            "quickSidewaysMinRankScore": settings.quick_sideways_min_rank_score,
            "sureShotMinSymbolTqs": settings.sure_shot_min_symbol_tqs,
            "sureShotMinRankScore": settings.sure_shot_min_rank_score,
            "sureShotScalpMinScore": settings.sure_shot_scalp_min_score,
            "aggressiveMinTqs": settings.aggressive_min_tqs,
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
            "composerMonitor": settings.composer_monitor_enabled,
            "composerApiConfigured": bool(settings.cursor_api_key),
            "paperSlippageEnabled": settings.paper_slippage_enabled,
            "paperLiveParityEnabled": settings.paper_live_parity_enabled,
        },
        "paperSlippage": slippage_config_summary(),
        "cadence": {
            "marketPollSeconds": settings.market_poll_seconds,
            "snapshotCacheSeconds": settings.snapshot_cache_seconds,
            "tickSnapshotSeconds": settings.tick_snapshot_seconds,
            "marketPollSecondsWs": settings.market_poll_seconds_ws,
            "marketPollIntervalMs": settings.market_poll_interval_ms,
            "marketPollIntervalWsMs": settings.market_poll_interval_ws_ms,
            "tickSnapshotIntervalMs": settings.tick_snapshot_interval_ms,
            "snapshotCacheIntervalMs": settings.snapshot_cache_interval_ms,
            "tickWakeDebounceMs": settings.tick_wake_debounce_ms,
            "sseHeartbeatSeconds": settings.sse_heartbeat_seconds,
            "sseEnabled": settings.sse_enabled,
            "upstoxMinRequestIntervalMs": settings.upstox_min_request_interval_ms,
            "upstoxChainCacheSeconds": settings.upstox_chain_cache_seconds,
            "upstoxLtpCacheSeconds": settings.upstox_ltp_cache_seconds,
            "upstoxRateLimitCooldownSeconds": settings.upstox_rate_limit_cooldown_seconds,
            "upstoxRateLimitActive": rate_limit_active(),
            "upstoxRateLimitRemainingSeconds": round(rate_limit_cooldown_remaining(), 1),
            "tickFastExitEnabled": settings.tick_fast_exit_enabled,
            "entryScanIntervalMs": settings.entry_scan_interval_ms,
            "newsCacheSeconds": settings.news_cache_seconds,
        },
        "latency": latency_stats(),
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


@router.post("/api/deployment/clear-rate-limit")
async def clear_upstox_rate_limit():
    """Clear in-memory Upstox 429 backoff after deploy or quota recovery."""
    was_active = rate_limit_active()
    remaining = round(rate_limit_cooldown_remaining(), 1)
    clear_rate_limit_cooldown()
    return {
        "status": "ok",
        "wasActive": was_active,
        "previousRemainingSeconds": remaining,
        "message": "Upstox rate-limit cooldown cleared",
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
