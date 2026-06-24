"""VWAP/POC bounce — mean reversion at value area (mid-session workhorse)."""

from typing import Any, Optional

from app.engines.strategies.base import BaseStrategy, StrategySignal
from app.models.schemas import Breadth, Greeks, MarketProfile, Orderflow, Regime, Side


class VwapBounceScalp(BaseStrategy):
    id = "vwap_bounce"
    name = "VWAP/POC Bounce"
    preferred_regimes = [Regime.RANGE_BOUND, Regime.CHOP]
    preferred_sessions = ["normal", "midday_chop"]

    def evaluate(self, symbol, spot, atm, chain, orderflow, greeks, breadth, profile, regime, session, heatmap):
        if regime == Regime.TREND_EXPANSION:
            return None

        poc = profile.poc
        if not poc:
            return None

        dist = abs(spot - poc)
        step = 100 if symbol != "SENSEX" else 100
        if dist > step * 0.5:
            return None

        # Bounce off POC: spot near POC with orderflow reversal
        side = Side.CALL if spot <= poc and orderflow.deltaVelocity > 40 else None
        if spot >= poc and orderflow.deltaVelocity > 40:
            side = Side.PUT

        if not side:
            return None

        opt = self._get_option(chain, atm, side)
        premium = opt.get("ltp") or opt.get("last_price", 0)
        if not premium:
            return None

        conf = min(88, 55 + (100 - dist) * 0.2 + orderflow.tickMomentum * 0.15)
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
            max_hold_seconds=150,
            reason=f"POC bounce at {poc:.0f}, dist={dist:.0f}",
            metadata={"poc": poc, "dist": dist},
        )
