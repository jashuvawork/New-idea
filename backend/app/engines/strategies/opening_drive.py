"""Opening drive momentum — first 45min aggressive scalp (Indian market open 9:15)."""

from typing import Any, Optional

from app.engines.strategies.base import BaseStrategy, StrategySignal
from app.models.schemas import Breadth, Greeks, MarketProfile, Orderflow, Regime, Side


class OpeningDriveScalp(BaseStrategy):
    id = "opening_drive"
    name = "Opening Drive Momentum"
    preferred_regimes = [Regime.TREND_EXPANSION, Regime.VOLATILITY_SPIKE]
    preferred_sessions = ["open_drive"]

    def evaluate(self, symbol, spot, atm, chain, orderflow, greeks, breadth, profile, regime, session, heatmap):
        if session != "open_drive":
            return None
        if orderflow.breakoutVelocity < 50:
            return None

        # Break above ORH → CALL, below ORL → PUT
        side = None
        if spot > profile.openingRangeHigh and breadth.bias == "BULLISH":
            side = Side.CALL
        elif spot < profile.openingRangeLow and breadth.bias == "BEARISH":
            side = Side.PUT
        if not side:
            return None

        opt = self._get_option(chain, atm, side)
        premium = opt.get("ltp") or opt.get("last_price", 0)
        if not premium:
            return None

        conf = min(95, 60 + orderflow.breakoutVelocity * 0.3 + breadth.score * 0.2)
        return StrategySignal(
            strategy_id=self.id,
            strategy_name=self.name,
            symbol=symbol,
            side=side,
            strike=atm,
            premium=premium,
            confidence=conf,
            ml_score=conf / 100,
            target_points=7.0,
            stop_points=3.0,
            max_hold_seconds=120,
            reason=f"OR breakout {'above' if side == Side.CALL else 'below'} with velocity {orderflow.breakoutVelocity:.0f}",
            metadata={"orh": profile.openingRangeHigh, "orl": profile.openingRangeLow},
        )
