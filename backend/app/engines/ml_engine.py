"""ML engine — win probability prediction from trade features."""

import logging
import os
from pathlib import Path
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)

MODEL_DIR = Path(os.environ.get("ML_MODEL_DIR", "/tmp/nexusquant_models"))
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# Feature order for model
FEATURE_NAMES = [
    "tqs", "delta_velocity", "volume_accel", "breakout_vel", "tick_momentum",
    "breadth_score", "iv_expansion", "iv_rank", "pcr", "liquidity_score",
    "velocity_pct", "regime_trend", "regime_chop", "session_open", "session_close",
    "side_call", "hour_ist", "confidence",
]


class MLEngine:
    """Gradient boosting classifier for scalp win probability."""

    def __init__(self):
        self._model = None
        self._trained = False
        self._training_samples: list[tuple[list[float], int]] = []
        self._load_or_init()

    def _load_or_init(self):
        model_path = MODEL_DIR / "scalp_classifier.joblib"
        try:
            if model_path.exists():
                import joblib
                self._model = joblib.load(model_path)
                self._trained = True
                logger.info("ML model loaded from %s", model_path)
                return
        except Exception as e:
            logger.warning("ML model load failed: %s", e)
        self._init_default_model()

    def _init_default_model(self):
        """Bootstrap with heuristic weights until real outcomes train the model."""
        try:
            from sklearn.ensemble import GradientBoostingClassifier
            # Seed with synthetic Indian market patterns
            X, y = self._generate_bootstrap_data()
            self._model = GradientBoostingClassifier(
                n_estimators=50, max_depth=4, learning_rate=0.1, random_state=42
            )
            self._model.fit(X, y)
            self._trained = True
            self._save()
            logger.info("ML model bootstrapped with %d samples", len(y))
        except Exception as e:
            logger.warning("ML init failed: %s", e)
            self._model = None

    def _generate_bootstrap_data(self) -> tuple[np.ndarray, np.ndarray]:
        """Bootstrap training data based on Indian market scalp heuristics."""
        rng = np.random.default_rng(42)
        X, y = [], []
        for _ in range(500):
            tqs = rng.uniform(50, 95)
            delta_vel = rng.uniform(20, 90)
            vol_accel = rng.uniform(20, 90)
            breakout = rng.uniform(10, 85)
            tick_mom = rng.uniform(10, 80)
            breadth = rng.uniform(40, 90)
            iv_exp = rng.uniform(0.9, 1.4)
            iv_rank = rng.uniform(20, 80)
            pcr = rng.uniform(0.6, 1.5)
            liq = rng.uniform(30, 95)
            vel_pct = rng.uniform(0.5, 4.0)
            regime_trend = rng.choice([0, 1])
            regime_chop = 1 - regime_trend if rng.random() > 0.5 else 0
            session_open = rng.choice([0, 1])
            session_close = rng.choice([0, 1])
            side_call = rng.choice([0, 1])
            hour = rng.uniform(9.5, 15.0)
            conf = rng.uniform(50, 95)

            features = [tqs, delta_vel, vol_accel, breakout, tick_mom, breadth,
                        iv_exp, iv_rank, pcr, liq, vel_pct, regime_trend,
                        regime_chop, session_open, session_close, side_call, hour, conf]
            # Heuristic win label
            score = (tqs * 0.2 + delta_vel * 0.15 + vol_accel * 0.1 +
                     breadth * 0.15 + vel_pct * 10 + conf * 0.1)
            if session_open:
                score += 5
            win = 1 if score > 65 and rng.random() > 0.35 else 0
            X.append(features)
            y.append(win)
        return np.array(X), np.array(y)

    def extract_features(self, signal: Any, context: dict[str, Any]) -> list[float]:
        regime = context.get("regime", "RANGE_BOUND")
        session = context.get("session", "normal")
        return [
            context.get("tqs", 50),
            context.get("delta_velocity", 0),
            context.get("volume_accel", 0),
            context.get("breakout_vel", 0),
            context.get("tick_momentum", 0),
            context.get("breadth_score", 50),
            context.get("iv_expansion", 1.0),
            context.get("iv_rank", 50),
            context.get("pcr", 1.0),
            context.get("liquidity_score", 50),
            context.get("velocity_pct", 0),
            1.0 if regime == "TREND_EXPANSION" else 0.0,
            1.0 if regime == "CHOP" else 0.0,
            1.0 if session == "open_drive" else 0.0,
            1.0 if session == "closing_momentum" else 0.0,
            1.0 if getattr(signal, "side", None) and signal.side.value == "CALL" else 0.0,
            context.get("hour_ist", 12.0),
            getattr(signal, "confidence", 50),
        ]

    def predict_win_probability(self, features: list[float]) -> float:
        if not self._model or not self._trained:
            # Fallback heuristic
            tqs, delta_vel, vel_pct, conf = features[0], features[1], features[10], features[17]
            return min(0.95, max(0.1, (tqs * 0.003 + delta_vel * 0.004 + vel_pct * 0.08 + conf * 0.003)))

        try:
            proba = self._model.predict_proba([features])[0]
            return float(proba[1]) if len(proba) > 1 else float(proba[0])
        except Exception:
            return 0.5

    def record_outcome(self, features: list[float], won: bool) -> None:
        self._training_samples.append((features, 1 if won else 0))
        if len(self._training_samples) >= 20:
            self._retrain()

    def _retrain(self):
        if not self._training_samples or not self._model:
            return
        try:
            from sklearn.ensemble import GradientBoostingClassifier
            X = np.array([s[0] for s in self._training_samples])
            y = np.array([s[1] for s in self._training_samples])
            self._model = GradientBoostingClassifier(
                n_estimators=50, max_depth=4, learning_rate=0.1, random_state=42
            )
            self._model.fit(X, y)
            self._trained = True
            self._save()
            logger.info("ML model retrained on %d samples", len(y))
        except Exception as e:
            logger.warning("ML retrain failed: %s", e)

    def _save(self):
        try:
            import joblib
            joblib.dump(self._model, MODEL_DIR / "scalp_classifier.joblib")
        except Exception as e:
            logger.warning("ML save failed: %s", e)

    def get_feature_importance(self) -> dict[str, float]:
        if not self._model or not hasattr(self._model, "feature_importances_"):
            return {}
        return dict(zip(FEATURE_NAMES, self._model.feature_importances_.tolist()))


_ml_engine: Optional[MLEngine] = None


def get_ml_engine() -> MLEngine:
    global _ml_engine
    if _ml_engine is None:
        _ml_engine = MLEngine()
    return _ml_engine
