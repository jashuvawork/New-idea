"""Broker order execution for auto-trading."""

import asyncio
import logging
import time
from typing import Any, Optional

from app.engines.capital_allocator import lot_multiplier, set_lot_size
from app.models.schemas import PaperTrade, Side, SymbolSnapshot
from app.services.upstox import INDEX_KEYS, UpstoxClient, UpstoxError

logger = logging.getLogger(__name__)


def exit_order_tag(trade_id: str) -> str:
    """Stable broker tag used to reconcile an exit across process restarts."""
    return f"nqx_{str(trade_id)[:12]}"


def _average_price_from_order_row(order: dict[str, Any]) -> Optional[float]:
    for key in ("average_price", "averagePrice"):
        raw = order.get(key)
        if raw is None or raw == "":
            continue
        try:
            price = float(raw)
        except (TypeError, ValueError):
            continue
        if price > 0:
            return price
    return None


async def fetch_order_average_price(
    client: UpstoxClient,
    order_id: str,
    *,
    max_wait_seconds: float = 12.0,
    poll_interval: float = 0.35,
) -> Optional[float]:
    """Poll order book until fill average_price is available (live MARKET orders)."""
    if not order_id:
        return None
    deadline = time.monotonic() + max(0.5, float(max_wait_seconds))
    while time.monotonic() < deadline:
        for order in await client.get_order_book():
            if not isinstance(order, dict):
                continue
            if str(order.get("order_id") or "") != str(order_id):
                continue
            status = str(order.get("status") or "").lower()
            if status in {"rejected", "cancelled", "canceled"}:
                return None
            price = _average_price_from_order_row(order)
            filled = int(float(order.get("filled_quantity") or 0))
            if price and price > 0 and filled > 0:
                return price
            if status in {"complete", "completed"} and price and price > 0:
                return price
        await asyncio.sleep(poll_interval)
    return None


async def find_existing_exit_order(
    client: UpstoxClient,
    trade: PaperTrade,
) -> Optional[str]:
    """Return an accepted matching SELL order, if one already exists."""
    tag = exit_order_tag(trade.id)
    instrument_key = str((trade.entryContext or {}).get("instrumentKey") or "")
    for order in await client.get_order_book():
        if not isinstance(order, dict):
            continue
        status = str(order.get("status") or "").lower()
        if status in {"rejected", "cancelled", "canceled"}:
            continue
        if str(order.get("tag") or "") != tag:
            continue
        if str(order.get("transaction_type") or "").upper() != "SELL":
            continue
        order_instrument = str(
            order.get("instrument_token") or order.get("instrument_key") or ""
        )
        if instrument_key and order_instrument and order_instrument != instrument_key:
            continue
        order_id = order.get("order_id")
        if order_id:
            return str(order_id)
    return None


def _instrument_from_heatmap(snap: SymbolSnapshot, strike: float, side: Side) -> Optional[str]:
    for row in snap.heatmap:
        if abs(row.strike - strike) < 1:
            key = row.callInstrumentKey if side == Side.CALL else row.putInstrumentKey
            if key:
                return key
    return None


def _lot_from_contract(contract: dict[str, Any], symbol: str) -> int:
    raw = contract.get("lot_size") or contract.get("minimum_lot")
    lot = int(raw) if raw is not None else lot_multiplier(symbol)
    if lot > 0:
        set_lot_size(symbol, lot)
    return lot


async def resolve_instrument_key(
    client: UpstoxClient,
    snap: SymbolSnapshot,
    strike: float,
    side: Side,
) -> tuple[str, str, int]:
    """Resolve Upstox instrument key, expiry, and lot_size for an option leg."""
    expiry = snap.optionExpiry
    if not expiry:
        raise UpstoxError(f"No option expiry on snapshot for {snap.symbol}")

    from_heatmap = _instrument_from_heatmap(snap, strike, side)
    if from_heatmap:
        return from_heatmap, expiry, lot_multiplier(snap.symbol)

    return await _resolve_from_contracts(client, snap.symbol, strike, side, expiry)


async def _resolve_from_contracts(
    client: UpstoxClient,
    symbol: str,
    strike: float,
    side: Side,
    expiry: str,
) -> tuple[str, str, int]:
    index_key = INDEX_KEYS.get(symbol)
    if not index_key:
        raise UpstoxError(f"Unknown symbol: {symbol}")

    contracts = await client._get(
        "/option/contract",
        params={"instrument_key": index_key, "expiry_date": expiry},
    )
    if not isinstance(contracts, list):
        raise UpstoxError(f"No option contracts for {symbol} expiry {expiry}")

    inst_type = "CE" if side == Side.CALL else "PE"
    for contract in contracts:
        if not isinstance(contract, dict):
            continue
        c_strike = contract.get("strike_price", 0)
        if abs(float(c_strike) - strike) >= 1:
            continue
        if contract.get("instrument_type") != inst_type:
            continue
        instrument_key = contract.get("instrument_key")
        if instrument_key:
            lot = _lot_from_contract(contract, symbol)
            return instrument_key, expiry, lot

    raise UpstoxError(f"No {inst_type} contract for {symbol} {strike} exp {expiry}")


def _extract_order_id(result: dict[str, Any]) -> Optional[str]:
    if not isinstance(result, dict):
        return None
    if result.get("order_id"):
        return str(result["order_id"])
    data = result.get("data")
    if isinstance(data, dict) and data.get("order_id"):
        return str(data["order_id"])
    return None


async def place_entry_order(
    client: UpstoxClient,
    snap: SymbolSnapshot,
    strike: float,
    side: Side,
    lots: int,
    tag: str = "nq_auto_entry",
) -> dict[str, Any]:
    """Place intraday BUY for an option leg."""
    instrument_key, expiry, lot_size = await resolve_instrument_key(client, snap, strike, side)
    quantity = lots * lot_size
    if quantity <= 0:
        raise UpstoxError("Invalid order quantity")

    result = await client.place_order({
        "quantity": quantity,
        "product": "I",
        "validity": "DAY",
        "price": 0,
        "tag": tag,
        "instrument_token": instrument_key,
        "order_type": "MARKET",
        "transaction_type": "BUY",
        "disclosed_quantity": 0,
        "trigger_price": 0,
        "is_amo": False,
    })
    order_id = _extract_order_id(result)
    logger.info(
        "LIVE ENTRY %s %s %s ×%d lots (size %d) qty=%d order=%s",
        snap.symbol, side.value, strike, lots, lot_size, quantity, order_id,
    )
    fill = await fetch_order_average_price(client, order_id) if order_id else None
    return {
        "order_id": order_id,
        "instrument_key": instrument_key,
        "expiry": expiry,
        "quantity": quantity,
        "lot_size": lot_size,
        "fill_premium": fill,
        "raw": result,
    }


async def place_exit_order(
    client: UpstoxClient,
    trade: PaperTrade,
    tag: Optional[str] = None,
) -> dict[str, Any]:
    """Place intraday SELL to close an open option position."""
    ctx = trade.entryContext or {}
    instrument_key = ctx.get("instrumentKey")
    if not instrument_key:
        raise UpstoxError(f"Trade {trade.id} missing instrument key for exit")

    lot_size = int(ctx.get("lotSize") or lot_multiplier(trade.symbol))
    quantity = ctx.get("brokerQuantity") or (trade.lots * lot_size)
    if quantity <= 0:
        raise UpstoxError("Invalid exit quantity")

    stable_tag = tag or exit_order_tag(trade.id)
    result = await client.place_order({
        "quantity": quantity,
        "product": "I",
        "validity": "DAY",
        "price": 0,
        "tag": stable_tag,
        "instrument_token": instrument_key,
        "order_type": "MARKET",
        "transaction_type": "SELL",
        "disclosed_quantity": 0,
        "trigger_price": 0,
        "is_amo": False,
    })
    order_id = _extract_order_id(result)
    logger.info(
        "LIVE EXIT %s %s %s ×%d lots (size %d) qty=%d order=%s reason=%s",
        trade.symbol, trade.side.value, trade.strike, trade.lots, lot_size, quantity, order_id,
        trade.exitReason,
    )
    fill = await fetch_order_average_price(client, order_id) if order_id else None
    return {
        "order_id": order_id,
        "quantity": quantity,
        "fill_premium": fill,
        "raw": result,
    }
