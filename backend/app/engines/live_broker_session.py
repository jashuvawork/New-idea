"""Broker session helpers — not entry/exit gates (paper book is authoritative)."""

from __future__ import annotations

from typing import Any

from app.models.schemas import AutoTraderState


def _live_trade(trade: Any) -> bool:
    ctx = getattr(trade, "entryContext", None) or {}
    if ctx.get("executionMode") == "LIVE":
        return True
    return bool(ctx.get("brokerAdopted"))


def _phantom_live_trade(trade: Any) -> bool:
    ctx = getattr(trade, "entryContext", None) or {}
    if not ctx.get("brokerAdopted"):
        return False
    entry = float(getattr(trade, "entryPremium", 0) or 0)
    strike = float(getattr(trade, "strike", 0) or 0)
    return entry <= 0 or strike > 100_000.0


def live_session_loss_count(state: AutoTraderState) -> int:
    """Closed broker losses today (ignores phantom adopted rows). HUD / analytics only."""
    losses = 0
    for trade in state.closedPaperTrades:
        if getattr(trade, "status", "CLOSED") != "CLOSED":
            continue
        if not _live_trade(trade) or _phantom_live_trade(trade):
            continue
        if float(getattr(trade, "pnlInr", 0) or 0) < 0:
            losses += 1
    return losses
