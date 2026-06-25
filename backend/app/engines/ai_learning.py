"""AI learning — rolling calibration from paper trade outcomes."""

import logging
from collections import defaultdict
from typing import Any

from app.engines.ml_engine import get_ml_engine
from app.models.schemas import PaperTrade

logger = logging.getLogger(__name__)


class AILearningEngine:
    """Learn from paper trade outcomes to improve ML model and strategy weights."""

    def __init__(self):
        self._strategy_stats: dict[str, dict[str, float]] = defaultdict(
            lambda: {"wins": 0, "losses": 0, "pnl": 0.0, "weight": 1.0}
        )
        self._feature_cache: dict[str, list[float]] = {}

    def record_trade_open(self, trade_id: str, features: list[float], strategy_id: str = "") -> None:
        self._feature_cache[trade_id] = features

    def record_trade_close(self, trade: PaperTrade) -> None:
        ml = get_ml_engine()
        features = self._feature_cache.pop(trade.id, None)

        won = trade.pnlInr > 0
        if features:
            ml.record_outcome(features, won)

        strategy_id = trade.strategyType.value if trade.strategyType else "unknown"
        stats = self._strategy_stats[strategy_id]
        if won:
            stats["wins"] += 1
        else:
            stats["losses"] += 1
        stats["pnl"] += trade.pnlInr

        # Adjust strategy weight based on rolling PF
        total = stats["wins"] + stats["losses"]
        if total >= 5:
            wr = stats["wins"] / total
            stats["weight"] = max(0.3, min(1.5, 0.5 + wr))

        logger.info(
            "AI learning: trade %s %s pnl=%.0f strategy=%s weight=%.2f",
            trade.id, "WIN" if won else "LOSS", trade.pnlInr, strategy_id, stats["weight"],
        )

    def get_strategy_weights(self) -> dict[str, float]:
        return {k: v["weight"] for k, v in self._strategy_stats.items()}

    def get_learning_report(self) -> dict[str, Any]:
        ml = get_ml_engine()
        return {
            "strategyStats": dict(self._strategy_stats),
            "strategyWeights": self.get_strategy_weights(),
            "featureImportance": ml.get_feature_importance(),
            "modelTrained": ml._trained,
            "pendingFeatures": len(self._feature_cache),
        }


_ai_learning: AILearningEngine | None = None


def get_ai_learning() -> AILearningEngine:
    global _ai_learning
    if _ai_learning is None:
        _ai_learning = AILearningEngine()
    return _ai_learning
