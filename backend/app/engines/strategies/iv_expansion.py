"""IV expansion scalp — trade when IV expanding with directional bias."""

from typing import Any, Optional

from app.engines.strategies.base import BaseStrategy, StrategySignal
from app.models.schemas import Breadth, Greeks, MarketProfile, Orderflow, Regime, Side


class IVExpansionScalp(BaseStrategy):
    id = "iv_expansion"
    name = "IV Expansion Scalp"
    preferred_regimes = [Regime.VOLATILITY_SPIKE, Regime.TREND_EXPANSION]
    preferred_sessions = ["open_drive", "normal"]

    def evaluate(self, symbol, spot, atm, chain, orderflow, greeks, breadth, profile, regime, session, heatmap):
        if greeks.ivExpansion < 1.1 or greeks.ivRank < 40:
            return None
        if orderflow.deltaVelocity < 40:
            return None

        side = Side.CALL if breadth.bias == "BULLISH" else Side.PUT if breadth.bias == "BEARISH" else None
        if not side:
            return None

        opt = self._get_option(chain, atm, side)
        premium = opt.get("ltp") or opt.get("last_price", 0)
        if not premium:
            return None

        conf = min(91, 55 + (greeks.ivExpansion - 1) * 80 + orderflow.deltaVelocity * 0.2)
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
            stop_points=3.5,
            max_hold_seconds=150,
            reason=f"IV expansion {greeks.ivExpansion:.2f}x, rank={greeks.ivRank:.0f}",
            metadata={"ivExpansion": greeks.ivExpansion, "ivRank": greeks.ivRank},
        )
