"""Premium Explosion — primary strategy for daily chart moments."""

from typing import Any, Optional

from app.engines.explosion_detector import ExplosionEvent
from app.engines.strategies.base import BaseStrategy, StrategySignal


class PremiumExplosion(BaseStrategy):
    id = "premium_explosion"
    name = "Premium Explosion Capture"
    preferred_sessions = ["open_drive", "normal", "midday_chop", "closing_momentum"]
    preferred_regimes = []  # works in all regimes

    def __init__(self):
        self._last_events: list[ExplosionEvent] = []

    def set_events(self, events: list[ExplosionEvent]) -> None:
        self._last_events = events

    def evaluate(self, symbol, spot, atm, chain, orderflow, greeks, breadth, profile, regime, session, heatmap):
        tradeable = [e for e in self._last_events if e.symbol == symbol and e.tier in ("EXPLODING", "ELITE")]
        if not tradeable:
            return None

        best = tradeable[0]
        conf = min(98, 50 + best.explosion_score * 0.45 + best.velocity_3s * 3)

        target = 25.0 if best.tier == "ELITE" else 12.0
        stop = 4.0

        return StrategySignal(
            strategy_id=self.id,
            strategy_name=self.name,
            symbol=symbol,
            side=best.side,
            strike=best.strike,
            premium=best.premium,
            confidence=conf,
            ml_score=conf / 100,
            target_points=target,
            stop_points=stop,
            max_hold_seconds=240,
            reason=f"{best.tier}: {best.reason}",
            metadata={
                "tier": best.tier,
                "velocity3s": best.velocity_3s,
                "velocity9s": best.velocity_9s,
                "volumeSurge": best.volume_surge,
                "explosionScore": best.explosion_score,
            },
        )
