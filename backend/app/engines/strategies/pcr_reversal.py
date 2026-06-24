"""PCR extreme reversal — contrarian scalp when PCR hits extremes."""

from typing import Any, Optional

from app.engines.strategies.base import BaseStrategy, StrategySignal, compute_pcr
from app.models.schemas import Breadth, Greeks, MarketProfile, Orderflow, Regime, Side


class PCRReversalScalp(BaseStrategy):
    id = "pcr_reversal"
    name = "PCR Extreme Reversal"
    preferred_regimes = [Regime.RANGE_BOUND, Regime.CHOP, Regime.VOLATILITY_SPIKE]
    preferred_sessions = ["normal", "midday_chop", "closing_momentum"]

    def evaluate(self, symbol, spot, atm, chain, orderflow, greeks, breadth, profile, regime, session, heatmap):
        pcr = compute_pcr(chain)

        side = None
        # High PCR (>1.3) = oversold sentiment → CALL reversal
        if pcr > 1.3 and orderflow.deltaVelocity > 35:
            side = Side.CALL
        # Low PCR (<0.7) = overbought → PUT reversal
        elif pcr < 0.7 and orderflow.deltaVelocity > 35:
            side = Side.PUT

        if not side:
            return None

        opt = self._get_option(chain, atm, side)
        premium = opt.get("ltp") or opt.get("last_price", 0)
        if not premium:
            return None

        conf = min(90, 52 + abs(pcr - 1.0) * 30 + orderflow.deltaVelocity * 0.2)
        return StrategySignal(
            strategy_id=self.id,
            strategy_name=self.name,
            symbol=symbol,
            side=side,
            strike=atm,
            premium=premium,
            confidence=conf,
            ml_score=conf / 100,
            target_points=5.5,
            stop_points=3.0,
            max_hold_seconds=160,
            reason=f"PCR extreme {pcr:.2f} reversal",
            metadata={"pcr": round(pcr, 3)},
        )
