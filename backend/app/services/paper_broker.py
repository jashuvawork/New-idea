"""Paper broker — mirrors live MARKET order flow without placing real orders."""

import logging
import uuid
from typing import Any, Optional

from app.engines.paper_slippage import apply_entry_fill, apply_exit_mark
from app.models.schemas import PaperTrade, Side, StrategyType, SymbolSnapshot
from app.services.order_executor import resolve_instrument_key
from app.services.upstox import UpstoxClient, UpstoxError

logger = logging.getLogger(__name__)


def _paper_order_id(prefix: str = "PAPER") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


async def simulate_entry_order(
    client: UpstoxClient,
    snap: SymbolSnapshot,
    strike: float,
    side: Side,
    lots: int,
    signal_premium: float,
    strategy_type: StrategyType,
    tier: Optional[str] = None,
    tag: str = "nq_paper_entry",
) -> dict[str, Any]:
    """
    Mirror place_entry_order() — resolve instrument, apply MARKET-entry slippage, return same shape.
    Fails the same way live would when instrument key cannot be resolved.
    """
    instrument_key, expiry, lot_size = await resolve_instrument_key(client, snap, strike, side)
    quantity = lots * lot_size
    if quantity <= 0:
        raise UpstoxError("Invalid order quantity")

    fill_premium, slip_meta = apply_entry_fill(signal_premium, strategy_type, tier=tier)
    order_id = _paper_order_id("PAPER-IN")

    logger.info(
        "PAPER ENTRY (live-parity) %s %s %s signal=%.2f fill=%.2f ×%d lots qty=%d key=%s order=%s tag=%s",
        snap.symbol, side.value, strike, signal_premium, fill_premium, lots, quantity,
        instrument_key, order_id, tag,
    )
    return {
        "order_id": order_id,
        "instrument_key": instrument_key,
        "expiry": expiry,
        "quantity": quantity,
        "lot_size": lot_size,
        "fill_premium": fill_premium,
        "signal_premium": signal_premium,
        "slippage": slip_meta,
        "simulated": True,
        "order_type": "MARKET",
        "transaction_type": "BUY",
        "product": "I",
        "validity": "DAY",
        "tag": tag,
    }


async def simulate_exit_order(
    client: UpstoxClient,
    trade: PaperTrade,
    market_premium: float,
    tag: str = "nq_paper_exit",
) -> dict[str, Any]:
    """
    Mirror place_exit_order() — SELL MARKET with exit slippage on the fill price.
    Requires instrumentKey in trade context (same as live).
    """
    ctx = trade.entryContext or {}
    instrument_key = ctx.get("instrumentKey")
    if not instrument_key:
        raise UpstoxError(f"Trade {trade.id} missing instrument key for exit")

    lot_size = int(ctx.get("lotSize") or 1)
    quantity = ctx.get("brokerQuantity") or (trade.lots * lot_size)
    if quantity <= 0:
        raise UpstoxError("Invalid exit quantity")

    tier = ctx.get("explosionTier") or (ctx.get("slippage") or {}).get("tier")
    fill_premium = apply_exit_mark(market_premium, trade.strategyType, tier)
    order_id = _paper_order_id("PAPER-OUT")

    logger.info(
        "PAPER EXIT (live-parity) %s %s %s market=%.2f fill=%.2f qty=%d order=%s reason=%s tag=%s",
        trade.symbol, trade.side.value, trade.strike, market_premium, fill_premium,
        quantity, order_id, trade.exitReason, tag,
    )
    return {
        "order_id": order_id,
        "quantity": quantity,
        "fill_premium": fill_premium,
        "market_premium": market_premium,
        "simulated": True,
        "order_type": "MARKET",
        "transaction_type": "SELL",
        "product": "I",
        "validity": "DAY",
        "tag": tag,
    }
