"""AI/ML strategy and learning API."""

from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from app.engines.ai_learning import get_ai_learning
from app.engines.composer_market_monitor import (
    get_brief_history,
    get_latest_brief,
    monitor_status,
    run_monitor_cycle,
)
from app.engines.ml_engine import get_ml_engine
from app.engines.strategy_orchestrator import ALL_STRATEGIES
from app.services.cursor_composer_client import get_composer_client

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/strategies")
async def list_strategies():
    return {
        "count": len(ALL_STRATEGIES),
        "strategies": [
            {
                "id": s.id,
                "name": s.name,
                "preferredSessions": s.preferred_sessions,
                "preferredRegimes": [r.value for r in s.preferred_regimes],
            }
            for s in ALL_STRATEGIES
        ],
    }


@router.get("/ml/status")
async def ml_status():
    ml = get_ml_engine()
    return {
        "trained": ml._trained,
        "featureImportance": ml.get_feature_importance(),
        "featureNames": ml.FEATURE_NAMES if hasattr(ml, 'FEATURE_NAMES') else [],
    }


@router.get("/learning/report")
async def learning_report():
    return get_ai_learning().get_learning_report()


@router.get("/composer/status")
async def composer_status():
    from app.engines.auto_trader import get_state
    from app.engines.expiry_day_guards import is_expiry_session
    from app.routers.market import get_multi_snapshot

    status = monitor_status()
    state = get_state()
    skipped = state.skipped or []
    status["tradingBlockers"] = [
        {
            "symbol": s.get("symbol"),
            "reason": s.get("reason"),
            "message": s.get("message"),
        }
        for s in skipped
        if s.get("symbol") == "SESSION" or s.get("reason", "").startswith(
            ("whipsaw_", "last_n_", "loss_streak", "controlled_", "daily_", "STAGE", "TRAIL", "expiry")
        )
    ]
    status["composerAdvisoryOnly"] = True
    try:
        multi = await get_multi_snapshot(force=False)
        status["isExpirySession"] = is_expiry_session(multi.snapshots) if multi else None
    except Exception:
        status["isExpirySession"] = None
    ping = await get_composer_client().ping()
    status["apiPing"] = ping
    return status


@router.get("/composer/brief")
async def composer_brief_latest():
    latest = get_latest_brief()
    if not latest:
        raise HTTPException(status_code=404, detail="No composer brief yet — wait for next monitor cycle")
    return latest


@router.get("/composer/history")
async def composer_brief_history(limit: int = 12):
    return {"briefs": get_brief_history(limit=limit)}


@router.post("/composer/refresh")
async def composer_refresh():
    """Force a new market brief (rules + Composer 2.5 when API key set)."""
    from app.routers.market import get_multi_snapshot
    from app.services.upstox import rate_limit_active, rate_limit_recovery_active

    force = not rate_limit_active() and not rate_limit_recovery_active()
    snapshots = (await get_multi_snapshot(force=force)).snapshots
    brief = await run_monitor_cycle(snapshots, force=True)
    return brief.to_dict()


@router.get("/missed-trades")
async def missed_trades_explainer():
    """Per-alert gate-by-gate explainer — why radar rips did not become trades."""
    from app.engines.auto_trader import get_state
    from app.engines.missed_trade_explainer import build_missed_trade_report
    from app.routers.market import get_multi_snapshot

    multi = await get_multi_snapshot(force=False)
    return build_missed_trade_report(multi.snapshots, get_state())


@router.get("/snapshot-analysis")
async def snapshot_analysis_rules():
    """Rules-based gap report: radar vs entry gates, misleading UI flags."""
    from app.engines.auto_trader import get_state
    from app.engines.snapshot_lag_analyzer import analyze_snapshot_lag
    from app.routers.market import get_multi_snapshot

    multi = await get_multi_snapshot(force=False)
    return analyze_snapshot_lag(multi.snapshots, get_state())


@router.post("/snapshot-analysis")
async def snapshot_analysis_ai():
    """Rules + Composer audit of where monitoring lags execution."""
    from app.engines.auto_trader import get_state
    from app.engines.snapshot_lag_analyzer import analyze_with_ai
    from app.routers.market import get_multi_snapshot
    from app.services.upstox import rate_limit_active, rate_limit_recovery_active

    force = not rate_limit_active() and not rate_limit_recovery_active()
    multi = await get_multi_snapshot(force=force)
    return await analyze_with_ai(multi.snapshots, get_state())


@router.get("/trade-reports")
async def trade_reports(limit: int = 30, days: int = 7):
    from app.services import trade_store

    return {
        "reports": trade_store.get_trade_reports_range(days=min(days, 30), limit=min(limit, 200)),
    }


@router.get("/analysis-monitor/status")
async def analysis_monitor_status():
    from app.engines.ai_market_analysis_monitor import monitor_status

    return monitor_status()


@router.get("/analysis-reports/latest")
async def analysis_reports_latest():
    from app.engines.ai_market_analysis_monitor import get_latest_report

    latest = get_latest_report()
    if not latest:
        from app.services import trade_store

        stored = trade_store.get_analysis_reports(limit=1)
        if stored:
            return stored[0]
        return {
            "waiting": True,
            "summary": "No analysis report yet — wait for next monitor cycle or POST /analysis-monitor/refresh",
            "reports": [],
        }
    return latest


@router.get("/analysis-reports")
async def analysis_reports(limit: int = 30, days: int = 7):
    from app.services import trade_store

    return {
        "reports": trade_store.get_analysis_reports_range(days=min(days, 30), limit=min(limit, 200)),
    }


@router.post("/analysis-monitor/refresh")
async def analysis_monitor_refresh():
    """Force a full market analysis cycle (rules + Composer when API key set)."""
    from app.engines.ai_market_analysis_monitor import run_analysis_cycle
    from app.routers.market import get_multi_snapshot
    from app.services.upstox import rate_limit_active, rate_limit_recovery_active

    force = not rate_limit_active() and not rate_limit_recovery_active()
    multi = await get_multi_snapshot(force=force)
    return await run_analysis_cycle(multi.snapshots, source="manual")
