"""Reconciled broker, strategy-capital, trade, and P&L view for the UI."""

import asyncio
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.engines.auto_trader import get_state
from app.engines.capital_allocator import (
    _parse_upstox_funds,
    capital_book_summary,
    get_capital_snapshot,
    get_lot_sizes_meta,
)
from app.services.upstox import UpstoxClient

IST = ZoneInfo("Asia/Kolkata")
_cache: dict[str, Any] | None = None
_cache_mono = 0.0
_cache_lock = asyncio.Lock()


def _number(row: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = row.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _position(row: dict[str, Any]) -> dict[str, Any]:
    realized = _number(row, "realised", "realized", "realised_pnl", "realized_pnl")
    total_pnl = _number(row, "pnl")
    unrealized = _number(row, "unrealised", "unrealized", "unrealised_pnl", "unrealized_pnl")
    if unrealized == 0 and total_pnl != 0:
        unrealized = total_pnl - realized
    return {
        "instrumentKey": row.get("instrument_token") or row.get("instrument_key"),
        "tradingSymbol": row.get("trading_symbol") or row.get("tradingsymbol"),
        "exchange": row.get("exchange"),
        "product": row.get("product"),
        "quantity": int(_number(row, "quantity")),
        "overnightQuantity": int(_number(row, "overnight_quantity")),
        "buyQuantity": int(_number(row, "buy_quantity")),
        "sellQuantity": int(_number(row, "sell_quantity")),
        "averagePrice": round(_number(row, "average_price"), 2),
        "lastPrice": round(_number(row, "last_price", "ltp"), 2),
        "realizedPnlInr": round(realized, 2),
        "unrealizedPnlInr": round(unrealized, 2),
        "pnlInr": round(total_pnl if total_pnl != 0 else realized + unrealized, 2),
    }


def _order(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "orderId": row.get("order_id"),
        "exchangeOrderId": row.get("exchange_order_id"),
        "tradingSymbol": row.get("trading_symbol") or row.get("tradingsymbol"),
        "transactionType": row.get("transaction_type"),
        "status": row.get("status"),
        "statusMessage": row.get("status_message"),
        "quantity": int(_number(row, "quantity")),
        "filledQuantity": int(_number(row, "filled_quantity")),
        "pendingQuantity": int(_number(row, "pending_quantity")),
        "averagePrice": round(_number(row, "average_price"), 2),
        "price": round(_number(row, "price"), 2),
        "orderType": row.get("order_type"),
        "product": row.get("product"),
        "timestamp": (
            row.get("order_timestamp")
            or row.get("exchange_timestamp")
            or row.get("order_date")
        ),
        "tag": row.get("tag"),
    }


def _paper_trade(trade: Any) -> dict[str, Any]:
    context = getattr(trade, "entryContext", None) or {}
    return {
        "id": getattr(trade, "id", ""),
        "symbol": getattr(trade, "symbol", ""),
        "side": getattr(getattr(trade, "side", ""), "value", getattr(trade, "side", "")),
        "strike": float(getattr(trade, "strike", 0) or 0),
        "lots": int(getattr(trade, "lots", 0) or 0),
        "entryPremium": round(float(getattr(trade, "entryPremium", 0) or 0), 2),
        "currentPremium": round(float(getattr(trade, "currentPremium", 0) or 0), 2),
        "pnlPoints": round(float(getattr(trade, "pnlPoints", 0) or 0), 2),
        "pnlInr": round(float(getattr(trade, "pnlInr", 0) or 0), 2),
        "status": getattr(trade, "status", ""),
        "openedAt": (
            getattr(trade, "openedAt", None).isoformat()
            if getattr(trade, "openedAt", None)
            else None
        ),
        "closedAt": (
            getattr(trade, "closedAt", None).isoformat()
            if getattr(trade, "closedAt", None)
            else None
        ),
        "exitReason": getattr(trade, "exitReason", None),
        "executionMode": context.get("executionMode"),
        "brokerOrderId": context.get("brokerOrderId"),
        "allocationRank": context.get("allocationRank"),
        "allocationBudgetInr": context.get("allocationBudgetInr"),
        "allocatedCostInr": context.get("allocatedCostInr"),
        "tier": context.get("explosionTier"),
        "score": context.get("selectionScore"),
    }


async def _fetch(client: UpstoxClient, method: str) -> tuple[Any, str | None]:
    try:
        return await getattr(client, method)(), None
    except Exception as exc:
        return None, str(exc)


async def build_upstox_trade_overview(
    client: UpstoxClient | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    global _cache, _cache_mono
    if not force and _cache is not None and time.monotonic() - _cache_mono < 2.0:
        return _cache

    async with _cache_lock:
        if not force and _cache is not None and time.monotonic() - _cache_mono < 2.0:
            return _cache

        state = get_state()
        broker = client or UpstoxClient()
        funds_result, positions_result, orders_result = await asyncio.gather(
            _fetch(broker, "get_funds"),
            _fetch(broker, "get_positions"),
            _fetch(broker, "get_order_book"),
        )
        funds, funds_error = funds_result
        positions_raw, positions_error = positions_result
        orders_raw, orders_error = orders_result

        positions = [
            _position(row)
            for row in (positions_raw or [])
            if isinstance(row, dict)
        ]
        orders = [
            _order(row)
            for row in (orders_raw or [])
            if isinstance(row, dict)
        ]
        orders.sort(key=lambda row: str(row.get("timestamp") or ""), reverse=True)

        cap = get_capital_snapshot()
        capital = {**cap.to_dict(), **get_lot_sizes_meta()}
        if isinstance(funds, dict):
            available, used, total = _parse_upstox_funds(funds)
            capital.update(
                {
                    "brokerAvailableMarginInr": round(available, 2),
                    "brokerUsedMarginInr": round(used, 2),
                    "brokerTotalEquityInr": round(total, 2),
                }
            )

        today = datetime.now(IST).strftime("%Y-%m-%d")
        closed_today = [
            trade
            for trade in state.closedPaperTrades
            if (getattr(trade, "sessionDate", None) or today) == today
        ]
        paper_realized = sum(float(trade.pnlInr or 0) for trade in closed_today)
        paper_unrealized = sum(float(trade.pnlInr or 0) for trade in state.openPaperTrades)
        broker_realized = sum(float(row["realizedPnlInr"]) for row in positions)
        broker_unrealized = sum(float(row["unrealizedPnlInr"]) for row in positions)
        active_broker_keys = {
            str(row.get("instrumentKey"))
            for row in positions
            if int(row.get("quantity") or 0) != 0 and row.get("instrumentKey")
        }
        strategy_live_keys = {
            str((getattr(trade, "entryContext", None) or {}).get("instrumentKey"))
            for trade in state.openPaperTrades
            if (getattr(trade, "entryContext", None) or {}).get("executionMode") == "LIVE"
            and (getattr(trade, "entryContext", None) or {}).get("instrumentKey")
        }
        untracked_broker = sorted(active_broker_keys - strategy_live_keys)
        missing_at_broker = sorted(strategy_live_keys - active_broker_keys)
        report = state.dailyReport
        errors = {
            key: value
            for key, value in {
                "funds": funds_error,
                "positions": positions_error,
                "orders": orders_error,
            }.items()
            if value
        }

        payload = {
            "generatedAt": datetime.now(IST).isoformat(),
            "executionMode": "LIVE" if state.liveTradingEnabled else "PAPER",
            "autoTradingEnabled": state.autoTradingEnabled,
            "running": state.running,
            "broker": {
                # Funds are the capital authority. Positions-only success must not
                # advertise a safe broker connection when margin is unavailable.
                "connected": funds_error is None,
                "complete": not bool(errors),
                "errors": errors,
            },
            "capital": capital,
            "allocation": capital_book_summary(
                state,
                planned=(state.capitalAllocation or {}).get("plannedAllocations") or [],
            ),
            "pnl": {
                "brokerRealizedInr": round(broker_realized, 2),
                "brokerUnrealizedInr": round(broker_unrealized, 2),
                "brokerNetInr": round(broker_realized + broker_unrealized, 2),
                "strategyRealizedInr": round(paper_realized, 2),
                "strategyUnrealizedInr": round(paper_unrealized, 2),
                "strategyNetInr": round(paper_realized + paper_unrealized, 2),
                "wins": int(report.wins),
                "losses": int(report.losses),
                "scratches": int(report.scratches),
                "winRate": round(float(report.winRate or 0), 1),
                "profitFactor": round(float(report.profitFactor or 0), 2),
            },
            "brokerPositions": positions,
            "brokerOrders": orders[:50],
            "reconciliation": {
                "safe": positions_error is None
                and not untracked_broker
                and not missing_at_broker,
                "checked": positions_error is None,
                "untrackedBrokerInstrumentKeys": untracked_broker,
                "missingBrokerInstrumentKeys": missing_at_broker,
                "message": (
                    "Broker and strategy live positions match"
                    if positions_error is None
                    and not untracked_broker
                    and not missing_at_broker
                    else "Broker and strategy live positions require reconciliation"
                ),
            },
            "strategyTrades": {
                "open": [_paper_trade(trade) for trade in state.openPaperTrades],
                "closed": [
                    _paper_trade(trade)
                    for trade in reversed(closed_today[-50:])
                ],
            },
        }
        _cache = payload
        _cache_mono = time.monotonic()
        return payload


def reset_upstox_trade_manager_cache_for_tests() -> None:
    global _cache, _cache_mono
    _cache = None
    _cache_mono = 0.0
