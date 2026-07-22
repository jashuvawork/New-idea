"""Risk engine — exposure, drawdown, safe mode gates."""

from datetime import datetime
from typing import Any

from app.config import get_settings
from app.engines.capital_allocator import get_capital_snapshot
from app.models.schemas import AutoTraderState, PaperTrade, RiskProfile, Side, StrategyType


class RiskEngine:
    def __init__(self):
        settings = get_settings()
        self.profile = RiskProfile(
            maxOpenTrades=settings.aggressive_max_open_scalps if settings.aggressive_lot_sizing else 3,
            maxExposureInr=500_000 * settings.per_trade_capital_pct,
        )
        self._daily_pnl: float = 0
        self._rejections: list[dict[str, Any]] = []

    def set_profile(self, profile: RiskProfile) -> None:
        self.profile = profile

    def update_daily_pnl(self, pnl: float) -> None:
        self._daily_pnl = pnl

    @property
    def safe_mode(self) -> bool:
        settings = get_settings()
        if settings.emergency_stop_enabled and self._daily_pnl <= -settings.emergency_stop_inr:
            return True
        loss_stop = float(getattr(settings, "daily_loss_stop_inr", 0) or 0)
        if loss_stop > 0 and self._daily_pnl <= -abs(loss_stop):
            return True
        return self.profile.safeMode

    def check_new_entry(
        self,
        state: AutoTraderState,
        symbol: str,
        side: Side,
        lots: int,
        premium: float,
        lot_multiplier: int = 25,
        strategy_type: StrategyType = StrategyType.SCALP,
        strike: float = 0.0,
    ) -> tuple[bool, str]:
        settings = get_settings()
        cap = get_capital_snapshot()

        if self.safe_mode:
            return False, "safe_mode_active"

        if not state.running:
            return False, "auto_trader_stopped"

        open_trades = state.openPaperTrades
        is_swing = strategy_type == StrategyType.SWING
        max_scalps = settings.aggressive_max_open_scalps if settings.aggressive_lot_sizing else self.profile.maxOpenTrades

        if is_swing:
            swing_open = sum(1 for t in open_trades if t.strategyType == StrategyType.SWING)
            if swing_open >= settings.swing_max_open:
                return False, "swing_max_open"
        else:
            scalp_open = sum(1 for t in open_trades if t.strategyType != StrategyType.SWING)
            if scalp_open >= max_scalps:
                return False, "max_open_trades"

        if state.calibrationBlocks.get(side.value, False):
            return False, f"calibration_block_{side.value}"

        new_exposure = premium * lots * lot_multiplier
        per_trade_cap = cap.perTradeCapitalInr or (cap.availableMarginInr * settings.per_trade_capital_pct)

        if new_exposure > per_trade_cap * 1.02:
            return False, "per_trade_capital_exceeded"

        # Each open leg uses ITS OWN symbol multiplier — not the new trade's — so a
        # mixed NIFTY(75)/SENSEX(20) book computes true exposure.
        from app.engines.capital_allocator import lot_multiplier as _symbol_lot_mult

        exposure = sum(
            (t.currentPremium or t.entryPremium) * t.lots * _symbol_lot_mult(t.symbol)
            for t in open_trades
        )
        if exposure + new_exposure > cap.availableMarginInr * 0.98:
            return False, "total_margin_exceeded"

        max_loss = settings.swing_max_loss_inr if is_swing else settings.max_risk_per_trade_inr
        stop_pts = 8.0 if is_swing else 3.0
        potential_loss = profile_stop_points(lots, lot_multiplier, stop_pts)
        if potential_loss > max_loss:
            return False, "per_trade_risk_exceeded"

        if not is_swing and settings.block_duplicate_open_leg and strike > 0:
            for t in open_trades:
                if (
                    t.strategyType != StrategyType.SWING
                    and t.symbol.upper() == symbol.upper()
                    and t.side == side
                    and abs(float(t.strike) - float(strike)) < 0.01
                ):
                    return False, "same_leg_already_open"

        if not is_swing:
            explosive_open = sum(
                1 for t in open_trades if t.strategyType == StrategyType.EXPLOSIVE
            )
            if explosive_open >= 1 and strategy_type == StrategyType.EXPLOSIVE:
                return False, "explosive_lane_cap"

        return True, "passed"

    def record_rejection(self, reason: str, context: dict[str, Any]) -> None:
        self._rejections.append({
            "reason": reason,
            "context": context,
            "timestamp": datetime.utcnow().isoformat(),
        })
        if len(self._rejections) > 100:
            self._rejections = self._rejections[-100:]

    def get_status(self) -> dict[str, Any]:
        cap = get_capital_snapshot()
        return {
            "safeMode": self.safe_mode,
            "dailyPnl": self._daily_pnl,
            "maxOpenTrades": self.profile.maxOpenTrades,
            "maxExposureInr": self.profile.maxExposureInr,
            "perTradeCapitalInr": cap.perTradeCapitalInr,
            "recentRejections": self._rejections[-10:],
        }


def profile_stop_points(lots: int, lot_multiplier: int, stop_pts: float = 3.0) -> float:
    return stop_pts * lots * lot_multiplier
