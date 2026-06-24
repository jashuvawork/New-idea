"""Lunch hour chop fade — fade false breakouts during 11:30-13:00 IST low volume."""

from typing import Any, Optional

from app.engines.strategies.base import BaseStrategy, StrategySignal
from app.models.schemas import Breadth, Greeks, MarketProfile, Orderflow, Regime, Side


class LunchChopFade(BaseStrategy):
    id = "lunch_fade"
    name = "Lunch Chop Fade"
    preferred_regimes = [Regime.CHOP, Regime.RANGE_BOUND]
    preferred_sessions = ["midday_chop"]

    def evaluate(self, symbol, spot, atm, chain, orderflow, greeks, breadth, profile, regime, session, heatmap):
        if session != "midday_chop":
            return None
        if regime not in (Regime.CHOP, Regime.RANGE_BOUND):
            return None

        # Fade move outside VAH/VAL back into value
        side = None
        if spot > profile.vah and orderflow.volumeAcceleration < 50:
            side = Side.PUT  # fade overextension
        elif spot < profile.val and orderflow.volumeAcceleration < 50:
            side = Side.CALL

        if not side:
            return None

        opt = self._get_option(chain, atm, side)
        premium = opt.get("ltp") or opt.get("last_price", 0)
        if not premium:
            return None

        conf = min(82, 55 + (100 - orderflow.volumeAcceleration) * 0.2)
        return StrategySignal(
            strategy_id=self.id,
            strategy_name=self.name,
            symbol=symbol,
            side=side,
            strike=atm,
            premium=premium,
            confidence=conf,
            ml_score=conf / 100,
            target_points=4.5,
            stop_points=2.5,
            max_hold_seconds=120,
            reason="Lunch fade outside value area",
            metadata={"vah": profile.vah, "val": profile.val},
        )
