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
    from app.engines.expiry_day_guards import is_expiry_session
    from app.routers.market import get_multi_snapshot

    status = monitor_status()
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

    snapshots = (await get_multi_snapshot(force=True)).snapshots
    brief = await run_monitor_cycle(snapshots, force=True)
    return brief.to_dict()
