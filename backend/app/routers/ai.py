"""AI/ML strategy and learning API."""

from fastapi import APIRouter

from app.engines.ai_learning import get_ai_learning
from app.engines.ml_engine import get_ml_engine
from app.engines.strategy_orchestrator import ALL_STRATEGIES

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
