"""Capital allocation from Upstox funds + static daily profit target/trail."""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Sequence
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import AutoTraderState, StrategyType

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# Fallback — overridden by config LOT_SIZE_* (authoritative when USE_UPSTOX_LOT_SIZES=false)
FALLBACK_LOT_SIZES: dict[str, int] = {
    "NIFTY": 65,
    "BANKNIFTY": 30,
    "SENSEX": 20,
}

_lot_sizes: dict[str, int] = {}
_lot_sizes_source: str = "config"
_lot_sizes_fetched_at: Optional[str] = None
_lot_sizes_last_mono: float = 0.0


def _configured_lot_sizes() -> dict[str, int]:
    settings = get_settings()
    return {
        "NIFTY": settings.lot_size_nifty,
        "BANKNIFTY": settings.lot_size_banknifty,
        "SENSEX": settings.lot_size_sensex,
    }


def _seed_lot_sizes_from_config() -> None:
    global _lot_sizes_source
    configured = _configured_lot_sizes()
    for sym, lot in configured.items():
        _lot_sizes[sym] = lot
    _lot_sizes_source = "config"


@dataclass
class CapitalSnapshot:
    availableMarginInr: float = 200_000.0
    usedMarginInr: float = 0.0
    totalEquityInr: float = 200_000.0
    source: str = "fallback"
    perTradeRiskInr: float = 12_000.0
    perTradeCapitalInr: float = 180_000.0
    maxExposureInr: float = 180_000.0
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


@dataclass(frozen=True)
class RankedAllocation:
    rank: int
    budgetInr: float
    remainingBeforeInr: float
    cashReserveInr: float
    capitalBaseInr: float
    committedInr: float
    weight: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "budgetInr": round(self.budgetInr, 2),
            "remainingBeforeInr": round(self.remainingBeforeInr, 2),
            "cashReserveInr": round(self.cashReserveInr, 2),
            "capitalBaseInr": round(self.capitalBaseInr, 2),
            "committedInr": round(self.committedInr, 2),
            "weight": round(self.weight, 4),
        }


@dataclass
class ProfitStage:
    stage: int
    pct: float
    thresholdInr: float
    reached: bool
    label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "pct": self.pct,
            "thresholdInr": round(self.thresholdInr, 2),
            "reached": self.reached,
            "label": self.label,
        }


@dataclass
class DailyProfitGate:
    targetInr: float = 22_000.0
    trailInr: float = 5_000.0
    capitalBaseInr: float = 200_000.0
    sessionPnlInr: float = 0.0
    bestPnlInr: float = 0.0
    trailFloorInr: float = 0.0
    lockedFloorInr: float = 0.0
    currentStage: int = 0
    minTargetHit: bool = False
    targetHit: bool = False
    trailLocked: bool = False
    newEntriesAllowed: bool = True
    status: str = "ACTIVE"
    message: str = ""
    stages: Optional[list[ProfitStage]] = None

    def to_dict(self) -> dict[str, Any]:
        progress = min(100.0, (self.sessionPnlInr / self.targetInr * 100) if self.targetInr else 0)
        return {
            "targetInr": self.targetInr,
            "minTargetInr": self.targetInr,
            "trailInr": self.trailInr,
            "capitalBaseInr": self.capitalBaseInr,
            "sessionPnlInr": round(self.sessionPnlInr, 2),
            "bestPnlInr": round(self.bestPnlInr, 2),
            "trailFloorInr": round(self.trailFloorInr, 2),
            "lockedFloorInr": round(self.lockedFloorInr, 2),
            "currentStage": self.currentStage,
            "minTargetHit": self.minTargetHit,
            "targetHit": self.minTargetHit,
            "trailLocked": self.trailLocked,
            "newEntriesAllowed": self.newEntriesAllowed,
            "status": self.status,
            "message": self.message,
            "progressPct": round(progress, 1),
            "stages": [s.to_dict() for s in (self.stages or [])],
            "stageLockMode": True,
        }


_capital: Optional[CapitalSnapshot] = None
_manual_capital_limit_inr: Optional[float] = None
_session_date: str = ""
_best_pnl: float = 0.0
_highest_stage: int = 0


def reset_session_profit_gate() -> None:
    """Clear staged profit lock memory — used on session reset / purge."""
    global _session_date, _best_pnl, _highest_stage
    _session_date = ""
    _best_pnl = 0.0
    _highest_stage = 0


def reset_capital_for_tests() -> None:
    global _capital, _manual_capital_limit_inr
    _capital = None
    _manual_capital_limit_inr = None


def lot_multiplier(symbol: str) -> int:
    """Units per lot — from config (default) or Upstox when enabled."""
    settings = get_settings()
    sym = symbol.upper()
    configured = _configured_lot_sizes()

    if not settings.use_upstox_lot_sizes:
        return configured.get(sym, settings.lot_size_nifty)

    if sym in _lot_sizes:
        return _lot_sizes[sym]
    return configured.get(sym, settings.lot_size_nifty)


def get_lot_sizes() -> dict[str, int]:
    """Current lot sizes for all configured symbols."""
    settings = get_settings()
    _seed_lot_sizes_from_config()
    if settings.use_upstox_lot_sizes:
        return {sym: lot_multiplier(sym) for sym in settings.symbols}
    return _configured_lot_sizes()


def get_lot_sizes_meta() -> dict[str, Any]:
    return {
        "lotSizes": get_lot_sizes(),
        "lotSizesSource": _lot_sizes_source,
        "lotSizesFetchedAt": _lot_sizes_fetched_at,
    }


def set_lot_size(symbol: str, lot_size: int) -> None:
    """Update cached lot size (e.g. from a resolved option contract)."""
    sym = symbol.upper()
    lot = int(lot_size)
    if lot <= 0:
        return
    if _lot_sizes.get(sym) != lot:
        logger.info("Lot size updated %s: %s → %d", sym, _lot_sizes.get(sym), lot)
    _lot_sizes[sym] = lot


async def refresh_lot_sizes(client, force: bool = False) -> dict[str, int]:
    """Pull lot_size from Upstox when USE_UPSTOX_LOT_SIZES=true; else use config."""
    global _lot_sizes_source, _lot_sizes_fetched_at, _lot_sizes_last_mono
    settings = get_settings()
    _seed_lot_sizes_from_config()

    if not settings.use_upstox_lot_sizes:
        return get_lot_sizes()

    ttl = settings.upstox_expiries_cache_seconds
    if not force and _lot_sizes and (time.monotonic() - _lot_sizes_last_mono) < ttl:
        return get_lot_sizes()

    updated = 0
    for sym in settings.symbols:
        try:
            lot = await client.get_lot_size(sym)
            set_lot_size(sym, lot)
            updated += 1
        except Exception as e:
            logger.warning("Upstox lot_size fetch failed for %s: %s", sym, e)

    if updated:
        _lot_sizes_source = "upstox"
        _lot_sizes_fetched_at = datetime.now(IST).isoformat()
        _lot_sizes_last_mono = time.monotonic()
        logger.info("Lot sizes from Upstox: %s", get_lot_sizes())
    return get_lot_sizes()


def _effective_capital_inr(available: float) -> float:
    """Cap sizing book at configured max (e.g. ₹2L) for realistic live deployment."""
    settings = get_settings()
    cap = settings.max_sizing_capital_inr or settings.fallback_capital_inr
    if _manual_capital_limit_inr is not None:
        cap = min(cap, _manual_capital_limit_inr) if cap > 0 else _manual_capital_limit_inr
    if cap > 0:
        return min(available, cap)
    return available


def ranked_allocation_weights() -> list[float]:
    """Effective book shares for the configured sequential allocation model."""
    settings = get_settings()
    max_positions = max(
        1,
        int(getattr(settings, "ftv_allocation_max_positions", 3) or 3),
    )
    remaining_pct = max(
        0.0,
        min(
            1.0,
            float(getattr(settings, "ftv_allocation_remaining_pct", 0) or 0),
        ),
    )
    if remaining_pct > 0:
        return [
            remaining_pct * ((1.0 - remaining_pct) ** index)
            for index in range(max_positions)
        ]

    raw = str(
        getattr(settings, "ftv_allocation_weights_csv", "0.60,0.25,0.10")
        or "0.60,0.25,0.10"
    )
    weights: list[float] = []
    for item in raw.split(","):
        try:
            value = float(item.strip())
        except ValueError:
            continue
        if value > 0:
            weights.append(value)
    weights = weights[:max_positions] or [1.0]
    reserve_pct = max(
        0.0,
        min(
            0.50,
            float(getattr(settings, "ftv_allocation_cash_reserve_pct", 0.05) or 0),
        ),
    )
    deployable_pct = 1.0 - reserve_pct
    total = sum(weights)
    if total > deployable_pct and total > 0:
        weights = [weight * deployable_pct / total for weight in weights]
    return weights


def trade_exposure_inr(trade: Any) -> float:
    """Cash committed to a long option; a losing mark never frees entry capital."""
    entry_premium = float(getattr(trade, "entryPremium", 0) or 0)
    current_premium = float(getattr(trade, "currentPremium", 0) or 0)
    premium = max(entry_premium, current_premium)
    lots = max(0, int(getattr(trade, "lots", 0) or 0))
    symbol = str(getattr(trade, "symbol", "") or "")
    return max(0.0, premium * lots * lot_multiplier(symbol))


def open_exposure_inr(state: AutoTraderState) -> float:
    return sum(trade_exposure_inr(trade) for trade in state.openPaperTrades)


def _allocation_capital_base(cap: CapitalSnapshot) -> float:
    total = float(cap.totalEquityInr or 0)
    if total <= 0:
        total = float(cap.availableMarginInr or 0) + float(cap.usedMarginInr or 0)
    if total <= 0:
        total = float(cap.availableMarginInr or 0)
    return max(0.0, _effective_capital_inr(total))


def ranked_allocation_for_state(
    state: AutoTraderState,
    rank: int,
) -> RankedAllocation:
    """Budget the next ranked FTV leg from the currently remaining book."""
    cap = get_capital_snapshot()
    settings = get_settings()
    weights = ranked_allocation_weights()
    rank = max(1, int(rank))
    capital_base = _allocation_capital_base(cap)
    reserve_pct = max(
        0.0,
        min(
            0.50,
            float(getattr(settings, "ftv_allocation_cash_reserve_pct", 0.05) or 0),
        ),
    )
    cash_reserve = capital_base * reserve_pct
    committed = open_exposure_inr(state)
    strategy_remaining = max(0.0, capital_base - cash_reserve - committed)
    broker_remaining = max(0.0, float(cap.availableMarginInr or 0))
    if cap.source == "fallback":
        broker_remaining = max(0.0, broker_remaining - committed)
    remaining = min(strategy_remaining, broker_remaining)

    index = rank - 1
    remaining_pct = max(
        0.0,
        min(
            1.0,
            float(getattr(settings, "ftv_allocation_remaining_pct", 0) or 0),
        ),
    )
    if index >= len(weights):
        budget = 0.0
        weight = 0.0
    elif remaining_pct > 0:
        # Each approved ranked entry gets the configured share of capital that is
        # still free at that moment. This cannot overspend the original book.
        budget = remaining * remaining_pct
        weight = remaining_pct
    else:
        future_reserved = capital_base * sum(weights[index + 1 :])
        budget = max(0.0, remaining - future_reserved)
        # Unused cash from a better-ranked sleeve rolls forward, but a slot never
        # borrows the capital explicitly reserved for lower-ranked opportunities.
        budget = min(remaining, budget)
        weight = weights[index]

    return RankedAllocation(
        rank=rank,
        budgetInr=budget,
        remainingBeforeInr=remaining,
        cashReserveInr=cash_reserve,
        capitalBaseInr=capital_base,
        committedInr=committed,
        weight=weight,
    )


def next_ranked_allocation_rank(state: AutoTraderState) -> int | None:
    """Return the first vacant sleeve; never infer rank from open-position count."""
    settings = get_settings()
    max_positions = max(
        1,
        int(getattr(settings, "ftv_allocation_max_positions", 3) or 3),
    )
    occupied: set[int] = set()
    unranked = 0
    for trade in state.openPaperTrades:
        if getattr(trade, "strategyType", None) != StrategyType.EXPLOSIVE:
            continue
        ctx = getattr(trade, "entryContext", None) or {}
        try:
            rank = int(ctx.get("allocationRank") or 0)
        except (TypeError, ValueError):
            rank = 0
        if 1 <= rank <= max_positions:
            occupied.add(rank)
        else:
            unranked += 1
    # Legacy/restored explosive positions without allocation metadata consume the
    # lowest free sleeves so they cannot be ignored by a new ranked entry.
    for rank in range(1, max_positions + 1):
        if unranked <= 0:
            break
        if rank not in occupied:
            occupied.add(rank)
            unranked -= 1
    return next(
        (rank for rank in range(1, max_positions + 1) if rank not in occupied),
        None,
    )


def cap_lots_to_allocation(
    lots: int,
    symbol: str,
    premium: float,
    allocation: RankedAllocation | None,
) -> int:
    """Apply the final cash sleeve after all strategy force-max sizing paths."""
    if allocation is None:
        return max(0, int(lots))
    unit_cost = float(premium or 0) * lot_multiplier(symbol)
    if unit_cost <= 0 or allocation.budgetInr <= 0:
        return 0
    affordable = int(allocation.budgetInr / unit_cost)
    return max(0, min(int(lots), affordable))


def capital_book_summary(
    state: AutoTraderState,
    *,
    planned: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One reconciled view for execution state and the Upstox manager UI."""
    cap = get_capital_snapshot()
    settings = get_settings()
    capital_base = _allocation_capital_base(cap)
    committed = open_exposure_inr(state)
    reserve_pct = max(
        0.0,
        min(
            0.50,
            float(getattr(settings, "ftv_allocation_cash_reserve_pct", 0.05) or 0),
        ),
    )
    reserve = capital_base * reserve_pct
    strategy_remaining = max(0.0, capital_base - reserve - committed)
    broker_remaining = max(0.0, float(cap.availableMarginInr or 0))
    if cap.source == "fallback":
        broker_remaining = max(0.0, broker_remaining - committed)
    remaining = min(strategy_remaining, broker_remaining)
    active = []
    for trade in state.openPaperTrades:
        ctx = getattr(trade, "entryContext", None) or {}
        active.append(
            {
                "tradeId": getattr(trade, "id", ""),
                "symbol": getattr(trade, "symbol", ""),
                "side": getattr(getattr(trade, "side", ""), "value", getattr(trade, "side", "")),
                "strike": float(getattr(trade, "strike", 0) or 0),
                "lots": int(getattr(trade, "lots", 0) or 0),
                "rank": ctx.get("allocationRank"),
                "budgetInr": ctx.get("allocationBudgetInr"),
                "committedInr": round(trade_exposure_inr(trade), 2),
            }
        )
    return {
        "enabled": bool(getattr(settings, "ftv_ranked_allocation_enabled", True)),
        "capitalBaseInr": round(capital_base, 2),
        "committedInr": round(committed, 2),
        "cashReserveInr": round(reserve, 2),
        "remainingInr": round(remaining, 2),
        "remainingAllocationPct": round(
            max(
                0.0,
                min(
                    1.0,
                    float(
                        getattr(settings, "ftv_allocation_remaining_pct", 0) or 0
                    ),
                ),
            ),
            4,
        ),
        "nextTradeBudgetInr": round(
            remaining
            * max(
                0.0,
                min(
                    1.0,
                    float(
                        getattr(settings, "ftv_allocation_remaining_pct", 0) or 0
                    ),
                ),
            ),
            2,
        ),
        "utilizationPct": round((committed / capital_base * 100) if capital_base else 0, 1),
        "weights": ranked_allocation_weights(),
        "maxPositions": max(
            1,
            int(getattr(settings, "ftv_allocation_max_positions", 3) or 3),
        ),
        "maxSameSide": max(
            1,
            int(getattr(settings, "ftv_allocation_max_same_side", 2) or 2),
        ),
        "activeAllocations": active,
        "plannedAllocations": list(planned or []),
    }


def max_lots_for_capital(symbol: str, premium: float) -> int:
    """Max lots affordably within the configured per-trade capital budget."""
    cap = get_capital_snapshot()
    settings = get_settings()
    mult = lot_multiplier(symbol)
    if premium <= 0 or mult <= 0:
        return 1
    budget = cap.perTradeCapitalInr
    if budget <= 0:
        budget = _effective_capital_inr(cap.availableMarginInr) * settings.per_trade_capital_pct
    return max(1, int(budget / (premium * mult)))


def max_lots_for_capital_pct(symbol: str, premium: float, capital_pct: float) -> int:
    """Affordable lots for an explicit share of currently available capital."""
    cap = get_capital_snapshot()
    mult = lot_multiplier(symbol)
    if premium <= 0 or mult <= 0:
        return 1
    pct = max(0.0, min(1.0, float(capital_pct or 0.0)))
    budget = _effective_capital_inr(cap.availableMarginInr) * pct
    return max(1, int(budget / (premium * mult)))


def clamp_lots(lots: int, symbol: str = "", premium: float = 0.0) -> int:
    """Clamp to min lots and capital-derived max (optional hard ceiling)."""
    settings = get_settings()
    min_l = max(1, settings.min_lots_per_trade or settings.simple_min_lots or 1)
    if symbol and premium > 0:
        cap_max = max_lots_for_capital(symbol, premium)
    elif settings.max_lots_per_trade > 0:
        cap_max = settings.max_lots_per_trade
    else:
        cap_max = lots
    hard = settings.max_lots_per_trade
    if hard > 0:
        cap_max = min(cap_max, hard)
    return max(min_l, min(lots, cap_max))


def _lot_tiers(capital_inr: float) -> tuple[int, int, int]:
    """Lot bands for UI — derived from capital, not fixed 100-lot ceiling."""
    settings = get_settings()
    min_l = max(1, settings.simple_min_lots or 1)
    ref_premium = 45.0
    ref_mult = lot_multiplier("NIFTY")
    budget = capital_inr * settings.per_trade_capital_pct
    cap_max = max(1, int(budget / (ref_premium * ref_mult))) if ref_mult else 50
    tgt = max(min_l, int(cap_max * 0.75))
    return min_l, tgt, cap_max


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


async def refresh_capital_from_upstox(
    client,
    *,
    force: bool = False,
) -> CapitalSnapshot:
    """Pull live margin from Upstox and derive static risk/lot tiers."""
    settings = get_settings()
    now = datetime.now(IST).isoformat()
    min_l, tgt_l, max_l = _lot_tiers(settings.fallback_capital_inr)

    await refresh_lot_sizes(client)

    try:
        funds = (
            await client.get_funds(force=True)
            if force
            else await client.get_funds()
        )
        available, used, total = _parse_upstox_funds(funds if isinstance(funds, dict) else {})
        if available <= 0 and total > 0:
            available = total - used
        if available <= 0:
            raise ValueError("zero margin from Upstox")
        available = _effective_capital_inr(available)
        total = _effective_capital_inr(total) if total > 0 else available
        source = "upstox"
    except Exception as e:
        if force:
            raise
        logger.warning("Upstox capital fetch failed, using fallback: %s", e)
        available = settings.fallback_capital_inr
        available = _effective_capital_inr(available)
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


def set_manual_capital_limit(amount: float) -> CapitalSnapshot:
    """Set the operator sizing ceiling used by every capital calculation."""
    value = float(amount)
    if value <= 0:
        raise ValueError("Capital allocation must be positive")
    global _capital, _manual_capital_limit_inr
    _manual_capital_limit_inr = value
    effective = _effective_capital_inr(value)
    settings = get_settings()
    min_l, tgt_l, max_l = _lot_tiers(effective)
    budget = effective * settings.per_trade_capital_pct
    _capital = CapitalSnapshot(
        availableMarginInr=effective,
        totalEquityInr=effective,
        source="manual",
        perTradeRiskInr=budget,
        perTradeCapitalInr=budget,
        maxExposureInr=budget,
        minLots=min_l,
        targetLots=tgt_l,
        maxLots=max_l,
        fetchedAt=datetime.now(IST).isoformat(),
    )
    return _capital


def compute_session_pnl(state: AutoTraderState) -> float:
    """Realtime session PnL = closed today + open unrealized."""
    today = datetime.now(IST).strftime("%Y-%m-%d")
    closed = sum(
        t.pnlInr for t in state.closedPaperTrades
        if (t.sessionDate or today) == today
    )
    open_pnl = sum(t.pnlInr for t in state.openPaperTrades)
    return closed + open_pnl


def _capital_base_for_stages() -> float:
    settings = get_settings()
    return settings.max_sizing_capital_inr or settings.fallback_capital_inr


def _resolve_daily_target_inr(capital_base: float) -> float:
    from app.engines.daily_18pct_strategy import resolve_daily_target_inr
    return resolve_daily_target_inr(capital_base)


def _stage_pcts_from_settings(settings) -> list[float]:
    raw = getattr(settings, "daily_profit_stage_pcts", None)
    if callable(raw):
        return raw()
    if isinstance(raw, list):
        return raw
    csv = getattr(settings, "daily_profit_stage_pcts_csv", "0.55,0.88,1.12")
    return [float(x.strip()) for x in str(csv).split(",") if x.strip()]


def _stage_thresholds(capital_base: float, daily_target: float, settings) -> list[float]:
    """Profit lock thresholds — multiples of daily 18% target or legacy capital %."""
    if settings.daily_profit_stage_from_target and daily_target > 0:
        mults = settings.daily_profit_stage_target_mults()
        return [daily_target * m for m in mults[:3]]
    pcts = _stage_pcts_from_settings(settings) or [0.55, 0.88, 1.12]
    return [capital_base * p for p in pcts[:3]]


def _build_profit_stages(
    capital_base: float,
    best_pnl: float,
    thresholds: list[float],
    *,
    from_target: bool = False,
) -> list[ProfitStage]:
    if from_target:
        labels = ["50% of daily target", "100% of daily target (18%)", "150% of daily target"]
    else:
        labels = ["55% lock", "88% lock", "112% lock"]
    stages: list[ProfitStage] = []
    for i, threshold in enumerate(thresholds[:3]):
        pct = (threshold / capital_base) if capital_base > 0 and not from_target else 0.0
        stages.append(
            ProfitStage(
                stage=i + 1,
                pct=pct,
                thresholdInr=threshold,
                reached=best_pnl >= threshold,
                label=labels[i] if i < len(labels) else f"Stage {i + 1}",
            )
        )
    if len(thresholds) >= 3 and best_pnl > thresholds[2]:
        stages.append(
            ProfitStage(
                stage=4,
                pct=0.0,
                thresholdInr=best_pnl,
                reached=True,
                label="Peak lock (max day)",
            )
        )
    return stages


def _compute_stage_lock(
    session_pnl: float,
    best_pnl: float,
    highest_stage: int,
    thresholds: list[float],
) -> tuple[int, float, int]:
    """
    Returns (highest_stage, locked_floor_inr, current_stage_display).
    Stage 1–3: floor = threshold when that stage is reached.
    Stage 4: floor trails session peak once above final threshold.
    """
    if len(thresholds) < 3:
        thresholds = thresholds + [0.0] * (3 - len(thresholds))

    if best_pnl >= thresholds[0]:
        highest_stage = max(highest_stage, 1)
    if best_pnl >= thresholds[1]:
        highest_stage = max(highest_stage, 2)
    if best_pnl >= thresholds[2]:
        highest_stage = max(highest_stage, 3)

    if highest_stage >= 3 and best_pnl > thresholds[2]:
        return highest_stage, best_pnl, 4

    if highest_stage >= 3:
        return highest_stage, thresholds[2], 3
    if highest_stage >= 2:
        return highest_stage, thresholds[1], 2
    if highest_stage >= 1:
        return highest_stage, thresholds[0], 1
    return highest_stage, 0.0, 0


def update_daily_profit_gate(state: AutoTraderState) -> DailyProfitGate:
    """
    Staged profit locks on sizing capital (₹2L default):
      Min ₹22K milestone (no stop) · Lock 1: 55% · Lock 2: 88% · Lock 3: 112% · Lock 4: peak of day
    New entries pause if session PnL falls below the highest stage floor reached.
    """
    global _best_pnl, _session_date, _highest_stage
    settings = get_settings()
    today = datetime.now(IST).strftime("%Y-%m-%d")

    if _session_date != today:
        _session_date = today
        _best_pnl = 0.0
        _highest_stage = 0

    capital_base = _capital_base_for_stages()
    session_pnl = compute_session_pnl(state)
    _best_pnl = max(_best_pnl, session_pnl)
    min_target = _resolve_daily_target_inr(capital_base)
    min_hit = _best_pnl >= min_target

    from_target = getattr(settings, "daily_profit_stage_from_target", False)
    thresholds = _stage_thresholds(capital_base, min_target, settings)
    stages = _build_profit_stages(
        capital_base, _best_pnl, thresholds, from_target=from_target,
    )

    if settings.daily_profit_stage_locks_enabled:
        _highest_stage, locked_floor, current_stage = _compute_stage_lock(
            session_pnl, _best_pnl, _highest_stage, thresholds,
        )
    else:
        # Legacy single trail
        locked_floor = max(0.0, _best_pnl - settings.daily_profit_trail_inr)
        current_stage = 0
        if _best_pnl >= settings.daily_profit_trail_inr and session_pnl <= locked_floor:
            pass  # handled below

    gate = DailyProfitGate(
        targetInr=min_target,
        trailInr=settings.daily_profit_trail_inr,
        capitalBaseInr=capital_base,
        sessionPnlInr=session_pnl,
        bestPnlInr=_best_pnl,
        trailFloorInr=locked_floor,
        lockedFloorInr=locked_floor,
        currentStage=current_stage,
        minTargetHit=min_hit,
        targetHit=min_hit,
        stages=stages,
    )

    loss_stop = float(getattr(settings, "daily_loss_stop_inr", 0) or 0)
    if loss_stop > 0 and session_pnl <= -abs(loss_stop):
        gate.newEntriesAllowed = False
        gate.status = "DAILY_LOSS_STOP"
        gate.message = (
            f"Daily loss stop: session ₹{session_pnl:,.0f} ≤ −₹{loss_stop:,.0f} "
            "— new entries paused."
        )
        return gate

    if settings.daily_profit_stage_locks_enabled:
        block_min_stage = max(1, int(settings.daily_profit_stage_block_entries_min_stage))
        below_floor = locked_floor > 0 and session_pnl < locked_floor
        should_block = below_floor and current_stage >= block_min_stage
        if should_block:
            gate.trailLocked = True
            gate.newEntriesAllowed = False
            gate.status = "STAGE_LOCK"
            if current_stage >= 4:
                gate.message = (
                    f"Peak lock: session ₹{session_pnl:,.0f} below day high floor "
                    f"₹{locked_floor:,.0f} — entries paused."
                )
            else:
                pct_label = ""
                if 0 < current_stage <= len(thresholds):
                    pct_label = f"₹{thresholds[current_stage - 1]:,.0f} floor"
                gate.message = (
                    f"Stage {current_stage} lock ({pct_label}): "
                    f"session ₹{session_pnl:,.0f} < floor ₹{locked_floor:,.0f} — protecting profits."
                )
        elif below_floor and current_stage > 0:
            gate.trailLocked = False
            gate.newEntriesAllowed = True
            gate.status = "STAGE_CAUTION"
            gate.message = (
                f"Stage {current_stage} caution: session ₹{session_pnl:,.0f} dipped below "
                f"₹{locked_floor:,.0f} floor — still building toward ₹{min_target:,.0f} (18%)"
            )
        else:
            gate.newEntriesAllowed = True
            gate.status = "ACTIVE"
            if current_stage >= 4:
                gate.message = (
                    f"Peak mode · floor ₹{locked_floor:,.0f} · min ₹{min_target:,.0f} ✓ · "
                    f"no upside cap"
                )
            elif current_stage >= 1:
                next_idx = current_stage
                if current_stage < 3:
                    nxt = thresholds[current_stage] if current_stage < len(thresholds) else thresholds[-1]
                    gate.message = (
                        f"Stage {current_stage} active · floor ₹{locked_floor:,.0f} · "
                        f"next lock ₹{nxt:,.0f} · target ₹{min_target:,.0f} (18%)"
                        + (" ✓" if min_hit else f" · {session_pnl / min_target * 100:.0f}%")
                    )
                else:
                    gate.message = (
                        f"Stage 3 · floor ₹{locked_floor:,.0f} · "
                        f"above → peak lock · target ₹{min_target:,.0f}" + (" ✓" if min_hit else "")
                    )
            else:
                gate.message = (
                    f"Daily target ₹{min_target:,.0f} (18% of ₹{capital_base:,.0f})"
                    + (f" · {session_pnl / min_target * 100:.0f}%" if min_target else "")
                    + (" ✓" if min_hit else "")
                    + f" · 1st lock at ₹{thresholds[0]:,.0f}"
                )
    else:
        # Legacy fallback
        if session_pnl >= min_target:
            gate.minTargetHit = True
            gate.targetHit = True
        trail_floor = max(0.0, _best_pnl - settings.daily_profit_trail_inr)
        gate.trailFloorInr = trail_floor
        gate.lockedFloorInr = trail_floor
        if _best_pnl >= settings.daily_profit_trail_inr and session_pnl <= trail_floor:
            gate.trailLocked = True
            gate.newEntriesAllowed = False
            gate.status = "TRAIL_LOCK"
            gate.message = f"Trail lock: fell ₹{settings.daily_profit_trail_inr:,.0f} from peak ₹{_best_pnl:,.0f}"
        else:
            gate.newEntriesAllowed = True
            gate.status = "ACTIVE"
            gate.message = f"Peak ₹{_best_pnl:,.0f} · trail floor ₹{trail_floor:,.0f}"

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
    Max lots on 85% of sizing capital: floor(budget / (premium × lot_multiplier)).
    Optional hard caps apply only when max_lots_per_trade / strategy caps are > 0.
    """
    settings = get_settings()

    if premium <= 0:
        return 1

    if settings.aggressive_lot_sizing:
        lots = max_lots_for_capital(symbol, premium)
    else:
        cap = get_capital_snapshot()
        mult = lot_multiplier(symbol)
        trade_budget = cap.perTradeCapitalInr
        if trade_budget <= 0:
            trade_budget = _effective_capital_inr(cap.availableMarginInr) * settings.per_trade_capital_pct
        margin_per_lot = premium * mult
        if margin_per_lot <= 0:
            return 1
        lots = int(trade_budget / margin_per_lot)
        risk_per_lot = stop_points * mult
        lots_by_risk = int(cap.perTradeRiskInr / risk_per_lot) if risk_per_lot > 0 else lots
        lots = min(lots, lots_by_risk, max_lots_for_capital(symbol, premium))
        lots = clamp_lots(max(settings.simple_min_lots, lots), symbol, premium)

    if settings.max_lots_per_trade > 0:
        lots = min(lots, settings.max_lots_per_trade)
    if strategy_type == StrategyType.SCALP and settings.scalp_max_lots > 0:
        lots = min(lots, settings.scalp_max_lots)
    elif strategy_type == StrategyType.EXPLOSIVE and settings.explosion_max_lots > 0:
        lots = min(lots, settings.explosion_max_lots)

    min_l = max(1, settings.min_lots_per_trade or settings.simple_min_lots or 1)
    return max(min_l, lots)


def tune_exit_plan_for_position(
    plan_dict: dict[str, Any],
    lots: int,
    premium: float,
    symbol: str,
    trade_budget_inr: float | None = None,
    preserve_lots_over_sl_budget: bool = False,
) -> dict[str, Any]:
    """Tune TP/SL for position — INR risk caps on 85% trade capital.

    Never crush a calculated/natural SL to a toy stop when lots are oversized.
    Instead shrink lots so stop × units fits the SL INR budget (Aug11 63-lot
    NIFTY kept 9pt SL while claiming SL ≤₹15k with ~₹37k real risk).
    """
    settings = get_settings()
    cap = get_capital_snapshot()
    mult = lot_multiplier(symbol)
    trade_budget = float(trade_budget_inr or 0)
    if trade_budget <= 0:
        trade_budget = cap.perTradeCapitalInr or (
            cap.availableMarginInr * settings.per_trade_capital_pct
        )
    lots = max(1, int(lots or 1))
    units = lots * mult
    if units <= 0 or premium <= 0:
        return plan_dict

    position_inr = premium * units
    reasoning = list(plan_dict.get("reasoning") or [])

    if plan_dict.get("targetPct"):
        return plan_dict

    plan_stop = float(plan_dict.get("stopPoints", settings.scalp_stop_points))
    plan_target = float(plan_dict.get("targetPoints", 6.0))
    plan_micro = float(plan_dict.get("microTargetPoints", 2.5))
    natural_stop = float(plan_dict.get("naturalStopPoints") or 0)

    max_sl_inr = trade_budget * settings.position_sl_cap_pct
    sl_pts_cap = max_sl_inr / units if units > 0 else 0.0
    target_inr = trade_budget * settings.position_tp_target_pct
    tp_pts_floor = target_inr / units if units > 0 else 0.0

    # Oversized lots (Jul29 32× SENSEX) crushed a ₹279 ITM natural ~28pt SL to 6pt.
    # Prefer the pre-chart naturalStopPoints when present (Jul30 chart→8pt crush).
    preserve = float(getattr(settings, "position_sl_preserve_natural_frac", 0.45) or 0.0)
    reference_stop = natural_stop if natural_stop > 0 else plan_stop
    if natural_stop > 0:
        preserve = max(
            preserve,
            float(getattr(settings, "explosion_sl_preserve_natural_frac", 0.85) or 0.85),
        )
    natural_floor = max(
        settings.scalp_stop_min_points,
        reference_stop * max(0.0, min(1.0, preserve)),
    )
    stop = max(natural_floor, min(max(plan_stop, natural_floor), sl_pts_cap))
    # If budget cap is below the calculated natural floor, keep the natural SL
    # and shrink lots so ₹ risk actually fits (don't lie about SL ≤ budget).
    if natural_stop > 0 and sl_pts_cap + 1e-9 < natural_floor:
        stop = natural_floor
        reasoning.append(
            f"Keep calculated SL {natural_floor:.1f}pt over budget cap {sl_pts_cap:.1f}pt "
            f"(natural {natural_stop:.1f}pt)"
        )
    elif sl_pts_cap + 1e-9 < natural_floor:
        stop = natural_floor
        reasoning.append(
            f"Size-tune SL floor {natural_floor:.1f}pt (preserve {preserve:.0%} of natural "
            f"{reference_stop:.1f}pt; budget cap was {sl_pts_cap:.1f}pt)"
        )

    # Honor the comment above: when preserving SL over the pt-cap, reduce size.
    # The one exception is an explicitly approved rank-1 first-lift. Its lot count
    # has already been bounded by the cash sleeve and hard lot ceiling; preserving
    # it here lets a genuine top local-base moment use the full allocated capital
    # without disguising the resulting INR stop risk.
    sl_risk_budget_override = False
    if stop > 0 and mult > 0 and max_sl_inr > 0:
        risk_at_size = stop * units
        if risk_at_size > max_sl_inr + 1e-6:
            if preserve_lots_over_sl_budget:
                sl_risk_budget_override = True
                reasoning.append(
                    f"Rank-1 first-lift full-budget override: keep {lots} lots with "
                    f"{stop:.1f}pt calculated SL (₹{risk_at_size:,.0f} risk vs "
                    f"₹{max_sl_inr:,.0f} standard budget)"
                )
            else:
                lots_fit = max(1, int(max_sl_inr / (stop * mult)))
                if lots_fit < lots:
                    reasoning.append(
                        f"Shrink lots {lots}→{lots_fit} so {stop:.1f}pt SL fits "
                        f"₹{max_sl_inr:,.0f} risk budget (was ₹{risk_at_size:,.0f})"
                    )
                    lots = lots_fit
                    units = lots * mult
                    position_inr = premium * units
                    sl_pts_cap = max_sl_inr / units if units > 0 else sl_pts_cap
                    tp_pts_floor = target_inr / units if units > 0 else tp_pts_floor

    target = max(plan_target, tp_pts_floor, settings.scalp_stop_points * 2)
    # Guard inverted R:R — a budget-capped stop can exceed the target floor.
    min_rr = float(getattr(settings, "position_min_risk_reward", 1.2) or 1.2)
    target = max(target, round(stop * min_rr, 2))
    micro = min(plan_micro, max(1.5, stop * 0.65))
    trail_arm = max(float(plan_dict.get("trailArmPoints", 3.0)), target * 0.35)
    trail_step = float(plan_dict.get("trailStepPoints", settings.scalp_trail_step_points))

    actual_sl_inr = stop * units
    if actual_sl_inr <= max_sl_inr + 1e-6:
        sl_msg = f"SL ≤₹{max_sl_inr:,.0f} ({stop:.1f}pt · ₹{actual_sl_inr:,.0f})"
    else:
        # Even 1 lot can exceed a tiny budget — never claim a false ceiling.
        sl_msg = (
            f"SL risk ₹{actual_sl_inr:,.0f} > budget ₹{max_sl_inr:,.0f} "
            f"({stop:.1f}pt · {lots} lot min)"
        )
    reasoning.append(
        f"Size tune: {lots} lots × {mult} units · ₹{position_inr:,.0f} notional · {sl_msg}"
    )
    reasoning.append(f"TP target ~₹{target_inr:,.0f} ({target:.1f}pt) on {settings.per_trade_capital_pct:.0%} capital")

    return {
        **plan_dict,
        "stopPoints": round(stop, 2),
        "targetPoints": round(target, 2),
        "microTargetPoints": round(micro, 2),
        "trailArmPoints": round(trail_arm, 2),
        # Refresh entry trail baseline after size raise so live retunes don't
        # compound from a pre-size 1.5pt chart arm (Jul29 24100 CE scratch).
        "entryTrailArmPoints": round(trail_arm, 2),
        "entryTargetPoints": round(target, 2),
        "entryStopPoints": round(stop, 2),
        "naturalStopPoints": round(natural_stop, 2) if natural_stop > 0 else plan_dict.get("naturalStopPoints"),
        "trailStepPoints": round(trail_step, 2),
        "lots": lots,
        "lotMultiplier": mult,
        "positionInr": round(position_inr, 2),
        "tradeBudgetInr": round(trade_budget, 2),
        "maxSlBudgetInr": round(max_sl_inr, 2),
        "actualSlRiskInr": round(actual_sl_inr, 2),
        "slRiskBudgetOverride": sl_risk_budget_override,
        "reasoning": reasoning,
    }
