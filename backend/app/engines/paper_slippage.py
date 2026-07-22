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
    # Real live broker fills skip journal slippage; paper-live-parity keeps slippage on simulated fills
    if (
        ctx.get("executionMode") == "LIVE"
        and ctx.get("brokerOrderId")
        and not ctx.get("brokerSimulated")
    ):
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


def compute_charges_inr(
    entry_premium: float,
    exit_premium: float,
    lots: int,
    lot_mult: int,
) -> float:
    """Realistic Indian F&O options charges (buy leg) on a round-trip.

    brokerage + STT(sell) + exchange txn + SEBI + stamp(buy) + GST. Turnover-based
    so it scales with position size — matches live broker net, unlike the flat fee.
    """
    settings = get_settings()
    qty = max(0, int(lots)) * max(0, int(lot_mult))
    if qty <= 0:
        return 0.0
    buy_turnover = max(0.0, float(entry_premium)) * qty
    sell_turnover = max(0.0, float(exit_premium)) * qty
    total_turnover = buy_turnover + sell_turnover

    bkg_cap = float(getattr(settings, "charge_brokerage_per_order_inr", 20.0) or 20.0)
    bkg_pct = float(getattr(settings, "charge_brokerage_pct", 0.0003) or 0.0003)
    brokerage = min(bkg_cap, bkg_pct * buy_turnover) + min(bkg_cap, bkg_pct * sell_turnover)
    stt = float(getattr(settings, "charge_stt_pct_sell", 0.000625) or 0.000625) * sell_turnover
    exchange = float(getattr(settings, "charge_exchange_txn_pct", 0.00035) or 0.00035) * total_turnover
    sebi = float(getattr(settings, "charge_sebi_pct", 0.000001) or 0.000001) * total_turnover
    stamp = float(getattr(settings, "charge_stamp_pct_buy", 0.00003) or 0.00003) * buy_turnover
    gst = float(getattr(settings, "charge_gst_pct", 0.18) or 0.18) * (brokerage + exchange + sebi)
    return round(brokerage + stt + exchange + sebi + stamp + gst, 2)


def finalize_closed_pnl_inr(
    gross_inr: float,
    *,
    entry_premium: float | None = None,
    exit_premium: float | None = None,
    lots: int | None = None,
    lot_mult: int | None = None,
) -> float:
    settings = get_settings()
    if not settings.paper_slippage_enabled:
        return round(gross_inr, 2)
    # Realistic turnover-based charges when trade context is available; else flat fallback.
    if (
        getattr(settings, "realistic_charges_enabled", True)
        and entry_premium is not None
        and exit_premium is not None
        and lots is not None
        and lot_mult is not None
    ):
        return round(gross_inr - compute_charges_inr(entry_premium, exit_premium, lots, lot_mult), 2)
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
        "paperLiveParity": s.paper_live_parity_enabled,
        "entryPoints": s.paper_slippage_entry_points,
        "exitPoints": s.paper_slippage_exit_points,
        "explosionMult": s.paper_slippage_explosion_mult,
        "swingMult": s.paper_slippage_swing_mult,
        "brokerageRoundTripInr": s.paper_brokerage_round_trip_inr,
        "description": (
            f"+{s.paper_slippage_entry_points}pt entry / "
            f"−{s.paper_slippage_exit_points}pt exit · "
            f"₹{s.paper_brokerage_round_trip_inr} fees"
            + (" · live-parity broker sim" if s.paper_live_parity_enabled else "")
        ),
    }
