"""ATM premium acceleration — fastest scalp on ATM option premium velocity."""

from typing import Any, Optional

from app.engines.strategies.base import BaseStrategy, StrategySignal
from app.models.schemas import Breadth, Greeks, MarketProfile, Orderflow, Regime, Side


class ATMPremiumAcceleration(BaseStrategy):
    id = "atm_accel"
    name = "ATM Premium Acceleration"
    preferred_regimes = [Regime.TREND_EXPANSION, Regime.VOLATILITY_SPIKE]
    preferred_sessions = ["open_drive", "normal", "closing_momentum"]

    def evaluate(self, symbol, spot, atm, chain, orderflow, greeks, breadth, profile, regime, session, heatmap):
        if orderflow.tickMomentum < 40:
            return None

        side = Side.CALL if breadth.bias in ("BULLISH", "NEUTRAL") and orderflow.bidAskImbalance > 52 else None
        if breadth.bias == "BEARISH" or orderflow.bidAskImbalance < 48:
            side = Side.PUT
        if breadth.bias == "BULLISH" and orderflow.bidAskImbalance > 52:
            side = Side.CALL

        if not side:
            return None

        opt = self._get_option(chain, atm, side)
        premium = opt.get("ltp") or opt.get("last_price", 0)
        if not premium or premium < 30:
            return None

        conf = min(96, 60 + orderflow.tickMomentum * 0.3 + orderflow.volumeAcceleration * 0.15)
        return StrategySignal(
            strategy_id=self.id,
            strategy_name=self.name,
            symbol=symbol,
            side=side,
            strike=atm,
            premium=premium,
            confidence=conf,
            ml_score=conf / 100,
            target_points=6.0,
            stop_points=2.5,
            max_hold_seconds=100,
            reason=f"ATM accel tick={orderflow.tickMomentum:.0f}",
            metadata={"tickMomentum": orderflow.tickMomentum},
        )
