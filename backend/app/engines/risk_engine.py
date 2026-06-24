"""Risk engine — exposure, drawdown, safe mode gates."""

from datetime import datetime
from typing import Any

from app.config import get_settings
from app.models.schemas import AutoTraderState, PaperTrade, RiskProfile, Side


class RiskEngine:
    def __init__(self):
        self.profile = RiskProfile()
        self._daily_pnl: float = 0
        self._rejections: list[dict[str, Any]] = []

    def set_profile(self, profile: RiskProfile) -> None:
        self.profile = profile

    def update_daily_pnl(self, pnl: float) -> None:
        self._daily_pnl = pnl

    @property
    def safe_mode(self) -> bool:
        settings = get_settings()
        if self._daily_pnl <= -settings.emergency_stop_inr * 2:
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
    ) -> tuple[bool, str]:
        settings = get_settings()

        if self.safe_mode:
            return False, "safe_mode_active"

        if not state.running:
            return False, "auto_trader_stopped"

        open_trades = state.openPaperTrades
        if len(open_trades) >= self.profile.maxOpenTrades:
            return False, "max_open_trades"

        # Calibration block
        if state.calibrationBlocks.get(side.value, False):
            return False, f"calibration_block_{side.value}"

        # Exposure check
        exposure = sum(
            (t.currentPremium or t.entryPremium) * t.lots * lot_multiplier
            for t in open_trades
        )
        new_exposure = premium * lots * lot_multiplier
        if exposure + new_exposure > self.profile.maxExposureInr:
            return False, "max_exposure_exceeded"

        # Per-trade risk cap
        max_loss = settings.max_risk_per_trade_inr
        potential_loss = profile_stop_points(lots, lot_multiplier)
        if potential_loss > max_loss:
            return False, "per_trade_risk_exceeded"

        # Explosive lane cap
        explosive_open = sum(
            1 for t in open_trades if t.strategyType.value == "EXPLOSIVE"
        )
        if explosive_open >= 1:
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
        return {
            "safeMode": self.safe_mode,
            "dailyPnl": self._daily_pnl,
            "maxOpenTrades": self.profile.maxOpenTrades,
            "maxExposureInr": self.profile.maxExposureInr,
            "recentRejections": self._rejections[-10:],
        }


def profile_stop_points(lots: int, lot_multiplier: int, stop_pts: float = 3.0) -> float:
    return stop_pts * lots * lot_multiplier
