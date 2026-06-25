"""Base strategy interface for Indian index options scalping."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.models.schemas import (
    Breadth,
    Greeks,
    MarketProfile,
    Orderflow,
    Regime,
    Side,
    StrategyType,
)

IST = ZoneInfo("Asia/Kolkata")


@dataclass
class StrategySignal:
    strategy_id: str
    strategy_name: str
    symbol: str
    side: Side
    strike: float
    premium: float
    confidence: float  # 0-100
    ml_score: float  # ML model probability
    tqs_boost: float = 0
    target_points: float = 6.0
    stop_points: float = 3.0
    max_hold_seconds: int = 180
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    id: str = "base"
    name: str = "Base Strategy"
    preferred_regimes: list[Regime] = []
    preferred_sessions: list[str] = []  # open_drive, normal, midday_chop, closing_momentum

    @abstractmethod
    def evaluate(
        self,
        symbol: str,
        spot: float,
        atm: float,
        chain: list[dict[str, Any]],
        orderflow: Orderflow,
        greeks: Greeks,
        breadth: Breadth,
        profile: MarketProfile,
        regime: Regime,
        session: str,
        heatmap: list,
    ) -> Optional[StrategySignal]:
        pass

    def _get_option(self, chain: list, strike: float, side: Side) -> dict:
        for row in chain:
            s = row.get("strike_price") or row.get("strike", 0)
            if abs(s - strike) < 1:
                key = "call_options" if side == Side.CALL else "put_options"
                alt = "CE" if side == Side.CALL else "PE"
                return row.get(key, {}) or row.get(alt, {})
        return {}

    def _session_now(self) -> str:
        now = datetime.now(IST)
        t = now.hour * 60 + now.minute
        if 9 * 60 + 15 <= t < 10 * 60:
            return "open_drive"
        if 11 * 60 + 30 <= t < 13 * 60:
            return "midday_chop"
        if 14 * 60 + 30 <= t < 15 * 60 + 15:
            return "closing_momentum"
        return "normal"


def compute_pcr(chain: list[dict]) -> float:
    call_oi = put_oi = 0
    for row in chain:
        ce = row.get("call_options", {}) or row.get("CE", {})
        pe = row.get("put_options", {}) or row.get("PE", {})
        call_oi += ce.get("oi", 0) or 0
        put_oi += pe.get("oi", 0) or 0
    return put_oi / call_oi if call_oi else 1.0


def compute_max_pain(chain: list[dict]) -> float:
    """Max pain strike — where option writers lose least."""
    strikes = []
    for row in chain:
        strike = row.get("strike_price") or row.get("strike", 0)
        ce = row.get("call_options", {}) or row.get("CE", {})
        pe = row.get("put_options", {}) or row.get("PE", {})
        strikes.append((strike, ce.get("oi", 0) or 0, pe.get("oi", 0) or 0))

    if not strikes:
        return 0

    min_pain = float("inf")
    max_pain_strike = strikes[len(strikes) // 2][0]

    for test_strike, _, _ in strikes:
        total_pain = 0
        for strike, call_oi, put_oi in strikes:
            if test_strike > strike:
                total_pain += (test_strike - strike) * call_oi
            if test_strike < strike:
                total_pain += (strike - test_strike) * put_oi
        if total_pain < min_pain:
            min_pain = total_pain
            max_pain_strike = test_strike

    return max_pain_strike
