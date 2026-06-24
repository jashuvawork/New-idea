"""OI shift momentum — detect sudden OI buildup at strike (institutional footprint)."""

from typing import Any, Optional

from app.engines.strategies.base import BaseStrategy, StrategySignal
from app.models.schemas import Breadth, Greeks, MarketProfile, Orderflow, Regime, Side


class OIShiftMomentum(BaseStrategy):
    id = "oi_shift"
    name = "OI Shift Momentum"
    preferred_regimes = [Regime.TREND_EXPANSION, Regime.VOLATILITY_SPIKE]
    preferred_sessions = ["open_drive", "normal", "closing_momentum"]

    def evaluate(self, symbol, spot, atm, chain, orderflow, greeks, breadth, profile, regime, session, heatmap):
        if not heatmap:
            return None

        # Find strike with highest liquidity score near ATM
        candidates = [h for h in heatmap if abs(h.strike - atm) <= 200]
        if not candidates:
            return None

        best = max(candidates, key=lambda h: h.liquidityScore + h.sweepRisk)
        if best.liquidityScore < 60:
            return None

        # OI buildup on call side → bullish, put side → bearish
        side = Side.CALL if best.callOi > best.putOi * 1.3 else Side.PUT if best.putOi > best.callOi * 1.3 else None
        if not side:
            return None

        if side == Side.CALL and breadth.bias == "BEARISH":
            return None
        if side == Side.PUT and breadth.bias == "BULLISH":
            return None

        opt = self._get_option(chain, best.strike, side)
        premium = opt.get("ltp") or opt.get("last_price", 0)
        if not premium:
            return None

        conf = min(92, 58 + best.liquidityScore * 0.25 + orderflow.volumeAcceleration * 0.15)
        return StrategySignal(
            strategy_id=self.id,
            strategy_name=self.name,
            symbol=symbol,
            side=side,
            strike=best.strike,
            premium=premium,
            confidence=conf,
            ml_score=conf / 100,
            target_points=6.5,
            stop_points=3.0,
            max_hold_seconds=180,
            reason=f"OI buildup at {best.strike}, liq={best.liquidityScore:.0f}",
            metadata={"callOi": best.callOi, "putOi": best.putOi, "gammaWall": best.gammaWall},
        )
