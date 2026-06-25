"""Gamma wall breakout — price approaching high-OI gamma wall with sweep risk."""

from typing import Any, Optional

from app.engines.strategies.base import BaseStrategy, StrategySignal
from app.models.schemas import Breadth, Greeks, MarketProfile, Orderflow, Regime, Side


class GammaWallBreakout(BaseStrategy):
    id = "gamma_wall"
    name = "Gamma Wall Breakout"
    preferred_regimes = [Regime.TREND_EXPANSION, Regime.VOLATILITY_SPIKE]
    preferred_sessions = ["open_drive", "normal", "closing_momentum"]

    def evaluate(self, symbol, spot, atm, chain, orderflow, greeks, breadth, profile, regime, session, heatmap):
        walls = [h for h in heatmap if h.gammaWall and h.sweepRisk > 40]
        if not walls:
            return None

        # Nearest gamma wall to spot
        wall = min(walls, key=lambda h: abs(h.strike - spot))
        dist = wall.strike - spot
        step = 50

        # Approaching wall with momentum — bet on break
        if abs(dist) > step * 2:
            return None
        if orderflow.breakoutVelocity < 45:
            return None

        side = Side.CALL if dist > 0 else Side.PUT  # price below wall → call break up

        opt = self._get_option(chain, wall.strike, side)
        premium = opt.get("ltp") or opt.get("last_price", 0)
        if not premium:
            return None

        conf = min(94, 62 + wall.sweepRisk * 0.3 + orderflow.breakoutVelocity * 0.2)
        return StrategySignal(
            strategy_id=self.id,
            strategy_name=self.name,
            symbol=symbol,
            side=side,
            strike=wall.strike,
            premium=premium,
            confidence=conf,
            ml_score=conf / 100,
            target_points=7.0,
            stop_points=3.5,
            max_hold_seconds=140,
            reason=f"Gamma wall break at {wall.strike}, sweep={wall.sweepRisk:.0f}",
            metadata={"wallStrike": wall.strike, "sweepRisk": wall.sweepRisk},
        )
