"""Realistic paper fill simulation — entry/exit slippage + brokerage."""

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import PaperTrade, StrategyType


def _tier_from_context(ctx: Optional[dict]) -> Optional[str]:
    if not ctx:
        return None
    return ctx.get("explosionTier") or (ctx.get("slippage") or {}).get("tier")


def _strategy_multiplier(strategy_type: StrategyType) -> float:
    settings = get_settings()
    if strategy_type == StrategyType.EXPLOSIVE:
        return settings.paper_slippage_explosion_mult
    if strategy_type == StrategyType.SWING:
        return settings.paper_slippage_swing_mult
    return 1.0


def entry_slip_points(strategy_type: StrategyType, tier: Optional[str] = None) -> float:
    settings = get_settings()
    if not settings.paper_slippage_enabled:
        return 0.0
    base = settings.paper_slippage_entry_points
    mult = _strategy_multiplier(strategy_type)
    if tier == "ELITE":
        mult *= 1.15
    return round(base * mult, 3)


def exit_slip_points(strategy_type: StrategyType, tier: Optional[str] = None) -> float:
    settings = get_settings()
    if not settings.paper_slippage_enabled:
        return 0.0
    base = settings.paper_slippage_exit_points
    mult = _strategy_multiplier(strategy_type)
    if tier == "ELITE":
        mult *= 1.15
    return round(base * mult, 3)


def should_simulate_slippage(trade: PaperTrade) -> bool:
    settings = get_settings()
    if not settings.paper_slippage_enabled:
        return False
    ctx = trade.entryContext or {}
    if ctx.get("executionMode") == "LIVE" and ctx.get("brokerOrderId"):
        return False
    return True


def apply_entry_fill(
    signal_premium: float,
    strategy_type: StrategyType,
    tier: Optional[str] = None,
) -> tuple[float, dict[str, Any]]:
    """Buyer pays above signal LTP."""
    slip = entry_slip_points(strategy_type, tier)
    fill = round(signal_premium + slip, 2)
    return fill, {
        "enabled": slip > 0 or get_settings().paper_brokerage_round_trip_inr > 0,
        "signalPremium": round(signal_premium, 2),
        "entrySlipPoints": slip,
        "exitSlipPoints": exit_slip_points(strategy_type, tier),
        "brokerageRoundTripInr": get_settings().paper_brokerage_round_trip_inr,
        "fillPremium": fill,
        "tier": tier,
        "strategyType": strategy_type.value,
    }


def apply_exit_mark(
    market_premium: float,
    strategy_type: StrategyType,
    tier: Optional[str] = None,
) -> float:
    """Seller receives below market LTP."""
    slip = exit_slip_points(strategy_type, tier)
    if slip <= 0:
        return market_premium
    return max(0.05, round(market_premium - slip, 2))


def mark_to_market(
    entry_fill: float,
    exit_mark: float,
    lots: int,
    lot_mult: int,
) -> tuple[float, float]:
    pts = round(exit_mark - entry_fill, 2)
    inr = round(pts * lots * lot_mult, 2)
    return pts, inr


def finalize_closed_pnl_inr(gross_inr: float) -> float:
    settings = get_settings()
    if not settings.paper_slippage_enabled:
        return round(gross_inr, 2)
    return round(gross_inr - settings.paper_brokerage_round_trip_inr, 2)


def exit_premium_for_trade(trade: PaperTrade, market_premium: float) -> float:
    if not should_simulate_slippage(trade):
        return market_premium
    tier = _tier_from_context(trade.entryContext)
    return apply_exit_mark(market_premium, trade.strategyType, tier)


def config_summary() -> dict[str, Any]:
    s = get_settings()
    return {
        "enabled": s.paper_slippage_enabled,
        "entryPoints": s.paper_slippage_entry_points,
        "exitPoints": s.paper_slippage_exit_points,
        "explosionMult": s.paper_slippage_explosion_mult,
        "swingMult": s.paper_slippage_swing_mult,
        "brokerageRoundTripInr": s.paper_brokerage_round_trip_inr,
        "description": (
            f"+{s.paper_slippage_entry_points}pt entry / "
            f"−{s.paper_slippage_exit_points}pt exit · "
            f"₹{s.paper_brokerage_round_trip_inr} fees"
        ),
    }
