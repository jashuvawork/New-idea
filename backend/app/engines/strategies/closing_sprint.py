"""Closing momentum sprint — last 45min directional push."""

from typing import Any, Optional

from app.engines.strategies.base import BaseStrategy, StrategySignal
from app.models.schemas import Breadth, Greeks, MarketProfile, Orderflow, Regime, Side


class ClosingMomentumSprint(BaseStrategy):
    id = "closing_sprint"
    name = "Closing Momentum Sprint"
    preferred_regimes = [Regime.TREND_EXPANSION]
    preferred_sessions = ["closing_momentum"]

    def evaluate(self, symbol, spot, atm, chain, orderflow, greeks, breadth, profile, regime, session, heatmap):
        if session != "closing_momentum":
            return None
        if orderflow.deltaVelocity < 55 or orderflow.volumeAcceleration < 50:
            return None
        if not breadth.aligned:
            return None

        side = Side.CALL if breadth.bias == "BULLISH" else Side.PUT if breadth.bias == "BEARISH" else None
        if not side:
            return None

        opt = self._get_option(chain, atm, side)
        premium = opt.get("ltp") or opt.get("last_price", 0)
        if not premium:
            return None

        conf = min(93, 65 + orderflow.deltaVelocity * 0.25 + breadth.score * 0.15)
        return StrategySignal(
            strategy_id=self.id,
            strategy_name=self.name,
            symbol=symbol,
            side=side,
            strike=atm,
            premium=premium,
            confidence=conf,
            ml_score=conf / 100,
            target_points=6.5,
            stop_points=3.0,
            max_hold_seconds=90,
            reason=f"Closing sprint {breadth.bias}, delta={orderflow.deltaVelocity:.0f}",
            metadata={"breadth": breadth.score},
        )
