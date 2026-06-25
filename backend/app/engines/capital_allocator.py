"""Capital allocation from Upstox funds + static daily profit target/trail."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import AutoTraderState, StrategyType

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# Contract units per lot — NIFTY/BANKNIFTY=25, SENSEX=10
LOT_MULTIPLIERS: dict[str, int] = {
    "NIFTY": 25,
    "BANKNIFTY": 25,
    "SENSEX": 10,
}


@dataclass
class CapitalSnapshot:
    availableMarginInr: float = 500_000.0
    usedMarginInr: float = 0.0
    totalEquityInr: float = 500_000.0
    source: str = "fallback"
    perTradeRiskInr: float = 12_000.0
    perTradeCapitalInr: float = 330_000.0
    maxExposureInr: float = 330_000.0
    minLots: int = 25
    targetLots: int = 60
    maxLots: int = 100
    fetchedAt: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "availableMarginInr": round(self.availableMarginInr, 2),
            "usedMarginInr": round(self.usedMarginInr, 2),
            "totalEquityInr": round(self.totalEquityInr, 2),
            "source": self.source,
            "perTradeRiskInr": round(self.perTradeRiskInr, 2),
            "perTradeCapitalInr": round(self.perTradeCapitalInr, 2),
            "maxExposureInr": round(self.maxExposureInr, 2),
            "minLots": self.minLots,
            "targetLots": self.targetLots,
            "maxLots": self.maxLots,
            "fetchedAt": self.fetchedAt,
        }


@dataclass
class DailyProfitGate:
    targetInr: float = 200_000.0
    trailInr: float = 20_000.0
    sessionPnlInr: float = 0.0
    bestPnlInr: float = 0.0
    trailFloorInr: float = 0.0
    targetHit: bool = False
    trailLocked: bool = False
    newEntriesAllowed: bool = True
    status: str = "ACTIVE"
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        progress = min(100.0, (self.sessionPnlInr / self.targetInr * 100) if self.targetInr else 0)
        return {
            "targetInr": self.targetInr,
            "trailInr": self.trailInr,
            "sessionPnlInr": round(self.sessionPnlInr, 2),
            "bestPnlInr": round(self.bestPnlInr, 2),
            "trailFloorInr": round(self.trailFloorInr, 2),
            "targetHit": self.targetHit,
            "trailLocked": self.trailLocked,
            "newEntriesAllowed": self.newEntriesAllowed,
            "status": self.status,
            "message": self.message,
            "progressPct": round(progress, 1),
        }


_capital: Optional[CapitalSnapshot] = None
_session_date: str = ""
_best_pnl: float = 0.0


def lot_multiplier(symbol: str) -> int:
    """Units per lot for the index (NIFTY/BANKNIFTY=25, SENSEX=10)."""
    return LOT_MULTIPLIERS.get(symbol.upper(), 25)


def clamp_lots(lots: int) -> int:
    """Clamp lot count to configured analysis band (default 25–100)."""
    settings = get_settings()
    min_l = settings.min_lots_per_trade or settings.simple_min_lots
    max_l = settings.max_lots_per_trade or settings.simple_max_lots
    return max(min_l, min(lots, max_l))


def _lot_tiers(capital_inr: float) -> tuple[int, int, int]:
    """Lot bands for UI — scaled within 25–100 by available margin."""
    settings = get_settings()
    min_l = settings.simple_min_lots
    max_l = settings.simple_max_lots
    if capital_inr >= 2_000_000:
        tgt = min(max_l, 85)
    elif capital_inr >= 1_000_000:
        tgt = 75
    elif capital_inr >= 500_000:
        tgt = settings.simple_target_lots
    else:
        tgt = max(min_l, settings.simple_target_lots - 10)
    return min_l, tgt, max_l


def _parse_upstox_funds(data: dict[str, Any]) -> tuple[float, float, float]:
    equity = data.get("equity") or data
    available = float(
        equity.get("available_margin")
        or equity.get("available_margin_cash")
        or equity.get("available")
        or 0
    )
    used = float(equity.get("used_margin") or equity.get("utilised_margin") or 0)
    total = float(
        equity.get("net")
        or equity.get("total_margin")
        or (available + used)
        or 0
    )
    return available, used, total


async def refresh_capital_from_upstox(client) -> CapitalSnapshot:
    """Pull live margin from Upstox and derive static risk/lot tiers."""
    settings = get_settings()
    now = datetime.now(IST).isoformat()
    min_l, tgt_l, max_l = _lot_tiers(settings.fallback_capital_inr)

    try:
        funds = await client.get_funds()
        available, used, total = _parse_upstox_funds(funds if isinstance(funds, dict) else {})
        if available <= 0 and total > 0:
            available = total - used
        if available <= 0:
            raise ValueError("zero margin from Upstox")
        source = "upstox"
    except Exception as e:
        logger.warning("Upstox capital fetch failed, using fallback: %s", e)
        available = settings.fallback_capital_inr
        used = 0.0
        total = available
        source = "fallback"

    min_l, tgt_l, max_l = _lot_tiers(available)
    per_trade_capital = available * settings.per_trade_capital_pct
    per_trade = per_trade_capital
    max_exposure = per_trade_capital

    snap = CapitalSnapshot(
        availableMarginInr=available,
        usedMarginInr=used,
        totalEquityInr=total or available,
        source=source,
        perTradeRiskInr=per_trade,
        perTradeCapitalInr=per_trade_capital,
        maxExposureInr=max_exposure,
        minLots=min_l,
        targetLots=tgt_l,
        maxLots=max_l,
        fetchedAt=now,
    )
    global _capital
    _capital = snap
    return snap


def get_capital_snapshot() -> CapitalSnapshot:
    global _capital
    if _capital is not None:
        return _capital
    settings = get_settings()
    min_l, tgt_l, max_l = _lot_tiers(settings.fallback_capital_inr)
    budget = settings.fallback_capital_inr * settings.per_trade_capital_pct
    return CapitalSnapshot(
        availableMarginInr=settings.fallback_capital_inr,
        totalEquityInr=settings.fallback_capital_inr,
        source="fallback",
        perTradeRiskInr=budget,
        perTradeCapitalInr=budget,
        maxExposureInr=budget,
        minLots=min_l,
        targetLots=tgt_l,
        maxLots=max_l,
    )


def compute_session_pnl(state: AutoTraderState) -> float:
    """Realtime session PnL = closed today + open unrealized."""
    today = datetime.now(IST).strftime("%Y-%m-%d")
    closed = sum(
        t.pnlInr for t in state.closedPaperTrades
        if (t.sessionDate or today) == today
    )
    open_pnl = sum(t.pnlInr for t in state.openPaperTrades)
    return closed + open_pnl


def update_daily_profit_gate(state: AutoTraderState) -> DailyProfitGate:
    """₹2L target + ₹20K trail from session peak — blocks new entries when hit."""
    global _best_pnl, _session_date
    settings = get_settings()
    today = datetime.now(IST).strftime("%Y-%m-%d")

    if _session_date != today:
        _session_date = today
        _best_pnl = 0.0

    session_pnl = compute_session_pnl(state)
    _best_pnl = max(_best_pnl, session_pnl)
    trail_floor = max(0.0, _best_pnl - settings.daily_profit_trail_inr)

    gate = DailyProfitGate(
        targetInr=settings.daily_profit_target_inr,
        trailInr=settings.daily_profit_trail_inr,
        sessionPnlInr=session_pnl,
        bestPnlInr=_best_pnl,
        trailFloorInr=trail_floor,
    )

    if session_pnl >= settings.daily_profit_target_inr:
        gate.targetHit = True
        gate.newEntriesAllowed = False
        gate.status = "TARGET_HIT"
        gate.message = f"Daily target ₹{settings.daily_profit_target_inr:,.0f} reached — paper entries paused."
    elif _best_pnl >= settings.daily_profit_trail_inr and session_pnl <= trail_floor:
        gate.trailLocked = True
        gate.newEntriesAllowed = False
        gate.status = "TRAIL_LOCK"
        gate.message = (
            f"Trail lock: session fell ₹{settings.daily_profit_trail_inr:,.0f} from peak "
            f"₹{_best_pnl:,.0f} — protecting profits."
        )
    else:
        gate.newEntriesAllowed = True
        gate.status = "ACTIVE"
        if _best_pnl > 0:
            gate.message = f"Peak ₹{_best_pnl:,.0f} · trail floor ₹{trail_floor:,.0f} · target ₹{settings.daily_profit_target_inr:,.0f}"
        else:
            gate.message = f"Target ₹{settings.daily_profit_target_inr:,.0f} · trail ₹{settings.daily_profit_trail_inr:,.0f} from peak"

    return gate


def compute_lots(
    symbol: str,
    premium: float,
    stop_points: float,
    tqs: float = 70.0,
    strategy_type: StrategyType = StrategyType.SCALP,
    confidence: float = 70.0,
    tier: Optional[str] = None,
) -> int:
    """
    Lots from 66% of Upstox margin, per-index contract size.
    lots = floor(trade_capital / (premium × lot_multiplier[symbol]))
    """
    cap = get_capital_snapshot()
    settings = get_settings()
    mult = lot_multiplier(symbol)

    if premium <= 0:
        return 1

    trade_budget = cap.perTradeCapitalInr
    if trade_budget <= 0:
        trade_budget = cap.availableMarginInr * settings.per_trade_capital_pct

    margin_per_lot = premium * mult
    if margin_per_lot <= 0:
        return 1

    lots = int(trade_budget / margin_per_lot)

    if settings.aggressive_lot_sizing:
        return clamp_lots(max(1, lots))

    # Legacy conservative scaling (if aggressive disabled)
    risk_per_lot = stop_points * mult
    lots_by_risk = int(cap.perTradeRiskInr / risk_per_lot) if risk_per_lot > 0 else lots
    lots = min(lots, lots_by_risk, cap.maxLots)
    return clamp_lots(max(settings.simple_min_lots, lots))


def tune_exit_plan_for_position(
    plan_dict: dict[str, Any],
    lots: int,
    premium: float,
    symbol: str,
) -> dict[str, Any]:
    """Tune TP/SL for huge lot positions — INR risk caps on 66% trade capital."""
    settings = get_settings()
    cap = get_capital_snapshot()
    mult = lot_multiplier(symbol)
    trade_budget = cap.perTradeCapitalInr or (cap.availableMarginInr * settings.per_trade_capital_pct)
    units = lots * mult
    if units <= 0 or premium <= 0:
        return plan_dict

    position_inr = premium * units
    reasoning = list(plan_dict.get("reasoning") or [])

    if plan_dict.get("targetPct"):
        return plan_dict

    max_sl_inr = trade_budget * settings.position_sl_cap_pct
    sl_pts_cap = max_sl_inr / units
    target_inr = trade_budget * settings.position_tp_target_pct
    tp_pts_floor = target_inr / units

    stop = min(float(plan_dict.get("stopPoints", 3.0)), max(1.5, sl_pts_cap))
    target = max(float(plan_dict.get("targetPoints", 6.0)), min(30.0, tp_pts_floor))
    micro = min(float(plan_dict.get("microTargetPoints", 2.5)), stop * 0.6)
    trail_arm = max(float(plan_dict.get("trailArmPoints", 3.0)), target * 0.45)

    reasoning.append(
        f"Size tune: {lots} lots × {mult} units · ₹{position_inr:,.0f} notional · SL ≤₹{max_sl_inr:,.0f} ({stop:.1f}pt)"
    )
    reasoning.append(f"TP target ~₹{target_inr:,.0f} ({target:.1f}pt) on {settings.per_trade_capital_pct:.0%} capital")

    return {
        **plan_dict,
        "stopPoints": round(stop, 2),
        "targetPoints": round(target, 2),
        "microTargetPoints": round(micro, 2),
        "trailArmPoints": round(trail_arm, 2),
        "lots": lots,
        "lotMultiplier": mult,
        "positionInr": round(position_inr, 2),
        "tradeBudgetInr": round(trade_budget, 2),
        "reasoning": reasoning,
    }
