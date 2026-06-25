"""Max pain magnet — price gravitating toward max pain into close."""

from typing import Any, Optional

from app.engines.strategies.base import BaseStrategy, StrategySignal, compute_max_pain
from app.models.schemas import Breadth, Greeks, MarketProfile, Orderflow, Regime, Side


class MaxPainMagnet(BaseStrategy):
    id = "max_pain"
    name = "Max Pain Magnet"
    preferred_regimes = [Regime.RANGE_BOUND, Regime.CHOP]
    preferred_sessions = ["closing_momentum", "midday_chop"]

    def evaluate(self, symbol, spot, atm, chain, orderflow, greeks, breadth, profile, regime, session, heatmap):
        if session not in ("closing_momentum", "midday_chop"):
            return None

        max_pain = compute_max_pain(chain)
        if not max_pain:
            return None

        dist = max_pain - spot
        if abs(dist) < 20:
            return None  # already at max pain

        side = Side.CALL if dist > 0 else Side.PUT
        if orderflow.deltaVelocity < 30:
            return None

        opt = self._get_option(chain, atm, side)
        premium = opt.get("ltp") or opt.get("last_price", 0)
        if not premium:
            return None

        conf = min(85, 50 + min(abs(dist) / 5, 20) + orderflow.deltaVelocity * 0.2)
        return StrategySignal(
            strategy_id=self.id,
            strategy_name=self.name,
            symbol=symbol,
            side=side,
            strike=atm,
            premium=premium,
            confidence=conf,
            ml_score=conf / 100,
            target_points=5.0,
            stop_points=2.5,
            max_hold_seconds=120,
            reason=f"Max pain magnet {max_pain:.0f}, spot {spot:.0f}",
            metadata={"maxPain": max_pain, "dist": dist},
        )
