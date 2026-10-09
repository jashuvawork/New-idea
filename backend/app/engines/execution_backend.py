"""Single order boundary: live Upstox vs paper broker simulation."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.models.schemas import Side, StrategyType, SymbolSnapshot


def is_live_execution(settings: Any) -> bool:
    return bool(
        getattr(settings, "enable_live_trading", False)
        and getattr(settings, "auto_trading_enabled", False)
    )


def uses_paper_broker_simulation(settings: Any) -> bool:
    """Dev harness: simulate broker orders while not on live execution."""
    if is_live_execution(settings):
        return False
    return bool(
        getattr(settings, "paper_live_parity_enabled", False)
        and getattr(settings, "paper_simulate_broker_orders", False)
    )


def needs_broker_order_path(settings: Any) -> bool:
    return is_live_execution(settings) or uses_paper_broker_simulation(settings)


async def submit_entry_order(
    *,
    settings: Any,
    client: Any,
    snap: SymbolSnapshot,
    strike: float,
    side: Side,
    lots: int,
    signal_premium: float,
    strategy_type: StrategyType,
    tier: str = "",
) -> tuple[dict[str, Any], dict[str, Any], float]:
    """
    Place entry via Upstox (live) or paper broker sim (parity harness).

    Returns (order_payload, ctx_extra_fragment, fill_premium).
    """
    from app.services.order_executor import place_entry_order
    from app.services.paper_broker import simulate_entry_order

    ctx: dict[str, Any] = {}
    if is_live_execution(settings):
        order = await place_entry_order(client, snap, strike, side, lots)
        fill_premium = float(signal_premium)
        broker_entry_fill = order.get("fill_premium")
        if broker_entry_fill and float(broker_entry_fill) > 0:
            fill_premium = float(broker_entry_fill)
        lot_size = order.get("lot_size")
        ctx.update({
            "instrumentKey": order["instrument_key"],
            "brokerOrderId": order["order_id"],
            "brokerQuantity": order["quantity"],
            "lotSize": lot_size,
            "brokerSimulated": False,
            "brokerEntryFillPremium": fill_premium,
        })
        if broker_entry_fill and float(broker_entry_fill) > 0:
            ctx["brokerFill"] = True
        return order, ctx, fill_premium

    order = await simulate_entry_order(
        client,
        snap,
        strike,
        side,
        lots,
        signal_premium,
        strategy_type,
        tier=tier,
    )
    fill_premium = float(order["fill_premium"])
    ctx.update({
        "instrumentKey": order["instrument_key"],
        "brokerOrderId": order["order_id"],
        "brokerQuantity": order["quantity"],
        "lotSize": order.get("lot_size"),
        "brokerSimulated": True,
        "orderType": order.get("order_type"),
        "product": order.get("product"),
    })
    slip = order.get("slippage")
    if isinstance(slip, dict):
        ctx["slippage"] = slip
    return order, ctx, fill_premium


async def submit_exit_order(
    *,
    settings: Any,
    client: Any,
    trade: Any,
    mark_premium: float,
) -> tuple[dict[str, Any], Optional[float], bool]:
    """
    Exit via Upstox or paper sim.

    Returns (exit_result, fill_premium_or_none, is_live_execution).
    """
    from app.services.order_executor import (
        fetch_order_average_price,
        find_existing_exit_order,
        place_exit_order,
    )
    from app.services.paper_broker import simulate_exit_order

    live = is_live_execution(settings)
    if live:
        existing_exit_id = await find_existing_exit_order(client, trade)
        exit_result = (
            {"order_id": existing_exit_id, "reconciled": True}
            if existing_exit_id
            else await place_exit_order(client, trade)
        )
        exit_fill = exit_result.get("fill_premium")
        exit_oid = exit_result.get("order_id")
        if (not exit_fill or float(exit_fill) <= 0) and exit_oid:
            exit_fill = await fetch_order_average_price(client, str(exit_oid))
        fill = float(exit_fill) if exit_fill and float(exit_fill) > 0 else None
        return exit_result, fill, True

    exit_result = await simulate_exit_order(client, trade, mark_premium)
    sim_fill = exit_result.get("fill_premium", mark_premium)
    fill = float(sim_fill) if sim_fill is not None else None
    return exit_result, fill, False
