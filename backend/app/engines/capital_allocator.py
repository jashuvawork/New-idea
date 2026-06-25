"""Capital allocation from Upstox funds + static daily profit target/trail."""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
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
    targetInr: float = 44_000.0
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
_session_date: str = ""
_best_pnl: float = 0.0
_highest_stage: int = 0


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
    if cap > 0:
        return min(available, cap)
    return available


def max_lots_for_capital(symbol: str, premium: float) -> int:
    """Max lots affordably on 85% of sizing capital for this premium."""
    cap = get_capital_snapshot()
    settings = get_settings()
    mult = lot_multiplier(symbol)
    if premium <= 0 or mult <= 0:
        return 1
    budget = cap.perTradeCapitalInr
    if budget <= 0:
        budget = _effective_capital_inr(cap.availableMarginInr) * settings.per_trade_capital_pct
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


async def refresh_capital_from_upstox(client) -> CapitalSnapshot:
    """Pull live margin from Upstox and derive static risk/lot tiers."""
    settings = get_settings()
    now = datetime.now(IST).isoformat()
    min_l, tgt_l, max_l = _lot_tiers(settings.fallback_capital_inr)

    await refresh_lot_sizes(client)

    try:
        funds = await client.get_funds()
        available, used, total = _parse_upstox_funds(funds if isinstance(funds, dict) else {})
        if available <= 0 and total > 0:
            available = total - used
        if available <= 0:
            raise ValueError("zero margin from Upstox")
        available = _effective_capital_inr(available)
        total = min(total, available) if total > 0 else available
        source = "upstox"
    except Exception as e:
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


def _stage_pcts_from_settings(settings) -> list[float]:
    raw = getattr(settings, "daily_profit_stage_pcts", None)
    if callable(raw):
        return raw()
    if isinstance(raw, list):
        return raw
    csv = getattr(settings, "daily_profit_stage_pcts_csv", "0.55,0.88,1.12")
    return [float(x.strip()) for x in str(csv).split(",") if x.strip()]


def _build_profit_stages(capital_base: float, best_pnl: float, pcts: list[float]) -> list[ProfitStage]:
    labels = ["55% lock", "88% lock", "112% lock"]
    stages: list[ProfitStage] = []
    for i, pct in enumerate(pcts[:3]):
        threshold = capital_base * pct
        stages.append(
            ProfitStage(
                stage=i + 1,
                pct=pct,
                thresholdInr=threshold,
                reached=best_pnl >= threshold,
                label=labels[i] if i < len(labels) else f"{pct:.0%} lock",
            )
        )
    if len(pcts) >= 3 and best_pnl > capital_base * pcts[2]:
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
    capital_base: float,
    stage_pcts: list[float],
) -> tuple[int, float, int]:
    """
    Returns (highest_stage, locked_floor_inr, current_stage_display).
    Stage 1–3: floor = capital × pct when that stage is reached.
    Stage 4: floor trails session peak once above 112% of capital.
    """
    thresholds = [capital_base * p for p in stage_pcts[:3]]
    if len(thresholds) < 3:
        thresholds.extend([0.0] * (3 - len(thresholds)))

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
      Min ₹44K milestone (no stop) · Lock 1: 55% · Lock 2: 88% · Lock 3: 112% · Lock 4: peak of day
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
    min_target = settings.daily_profit_target_inr
    min_hit = _best_pnl >= min_target

    stage_pcts = _stage_pcts_from_settings(settings) or [0.55, 0.88, 1.12]
    stages = _build_profit_stages(capital_base, _best_pnl, stage_pcts)

    if settings.daily_profit_stage_locks_enabled:
        _highest_stage, locked_floor, current_stage = _compute_stage_lock(
            session_pnl, _best_pnl, _highest_stage, capital_base, stage_pcts,
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

    if settings.daily_profit_stage_locks_enabled:
        if locked_floor > 0 and session_pnl < locked_floor:
            gate.trailLocked = True
            gate.newEntriesAllowed = False
            gate.status = "STAGE_LOCK"
            if current_stage >= 4:
                gate.message = (
                    f"Peak lock: session ₹{session_pnl:,.0f} below day high floor "
                    f"₹{locked_floor:,.0f} — entries paused."
                )
            else:
                pct_label = stage_pcts[current_stage - 1] if 0 < current_stage <= len(stage_pcts) else 0
                gate.message = (
                    f"Stage {current_stage} lock ({pct_label:.0%} of ₹{capital_base:,.0f}): "
                    f"session ₹{session_pnl:,.0f} < floor ₹{locked_floor:,.0f} — protecting profits."
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
                    nxt = capital_base * stage_pcts[current_stage]
                    gate.message = (
                        f"Stage {current_stage} active · floor ₹{locked_floor:,.0f} · "
                        f"next lock ₹{nxt:,.0f} · min ₹{min_target:,.0f}"
                        + (" ✓" if min_hit else "")
                    )
                else:
                    gate.message = (
                        f"Stage 3 (112%) · floor ₹{locked_floor:,.0f} · "
                        f"above → peak lock · min ₹{min_target:,.0f}" + (" ✓" if min_hit else "")
                    )
            else:
                gate.message = (
                    f"Min target ₹{min_target:,.0f}"
                    + (" ✓" if min_hit else "")
                    + f" · 1st lock at ₹{capital_base * stage_pcts[0]:,.0f} (55%)"
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
    Lots from 85% of sizing capital: floor(budget / (premium × lot_multiplier)).
    No fixed 100-lot cap — max is whatever 85% margin affords.
    """
    cap = get_capital_snapshot()
    settings = get_settings()
    mult = lot_multiplier(symbol)

    if premium <= 0:
        return 1

    trade_budget = cap.perTradeCapitalInr
    if trade_budget <= 0:
        trade_budget = _effective_capital_inr(cap.availableMarginInr) * settings.per_trade_capital_pct

    margin_per_lot = premium * mult
    if margin_per_lot <= 0:
        return 1

    lots = int(trade_budget / margin_per_lot)

    if settings.aggressive_lot_sizing:
        return clamp_lots(max(1, lots), symbol, premium)

    risk_per_lot = stop_points * mult
    lots_by_risk = int(cap.perTradeRiskInr / risk_per_lot) if risk_per_lot > 0 else lots
    lots = min(lots, lots_by_risk, max_lots_for_capital(symbol, premium))
    return clamp_lots(max(settings.simple_min_lots, lots), symbol, premium)


def tune_exit_plan_for_position(
    plan_dict: dict[str, Any],
    lots: int,
    premium: float,
    symbol: str,
) -> dict[str, Any]:
    """Tune TP/SL for position — INR risk caps on 85% trade capital."""
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
