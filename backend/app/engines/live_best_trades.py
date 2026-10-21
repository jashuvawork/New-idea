"""Live best-trades-only gate — strict quality bar for real-money entries."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import get_settings
from app.models.schemas import AutoTraderState, SymbolSnapshot


def _live_trade(trade: Any) -> bool:
    ctx = getattr(trade, "entryContext", None) or {}
    if ctx.get("executionMode") == "LIVE":
        return True
    if ctx.get("brokerAdopted"):
        return True
    return False


def _phantom_live_trade(trade: Any) -> bool:
    ctx = getattr(trade, "entryContext", None) or {}
    if not ctx.get("brokerAdopted"):
        return False
    entry = float(getattr(trade, "entryPremium", 0) or 0)
    strike = float(getattr(trade, "strike", 0) or 0)
    return entry <= 0 or strike > 100_000.0


def live_session_loss_count(state: AutoTraderState) -> int:
    """Count real closed live losses today — ignores phantom adopted rows."""
    losses = 0
    for trade in state.closedPaperTrades:
        if getattr(trade, "status", "CLOSED") != "CLOSED":
            continue
        if not _live_trade(trade) or _phantom_live_trade(trade):
            continue
        if float(getattr(trade, "pnlInr", 0) or 0) < 0:
            losses += 1
    return losses


def live_best_trade_entry_blocked(
    candidate: Any,
    snap: SymbolSnapshot,
    state: AutoTraderState,
    *,
    snapshots: dict[str, SymbolSnapshot] | None = None,
    ranking: Mapping[str, Any] | None = None,
    chart_meta: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """October 1 paper never applied this grade-S live bar. Live skips it too.

    ``LIVE_BEST_TRADES_ONLY_ENABLED`` is ignored. Grade, pad, chart, position
    count, and the post-loss pause stay on the shared paper gates.
    """
    del candidate, snap, state, snapshots, ranking, chart_meta
    return False, "ok", {"liveBestTradeGate": False}


def live_early_fail_exit_reason(
    trade: Any,
    *,
    hold_seconds: float,
    best_points: float,
    pnl_points: float,
    live_velocity_3s: float,
) -> Optional[str]:
    """Scratch live entries that never go green — even under structural hold."""
    settings = get_settings()
    if not getattr(settings, "live_early_fail_exit_enabled", True):
        return None
    ctx = getattr(trade, "entryContext", None) or {}
    if ctx.get("executionMode") != "LIVE" and not ctx.get("liveBestTradeGate"):
        return None

    min_hold = int(getattr(settings, "live_early_fail_min_hold_seconds", 45) or 45)
    max_hold = int(getattr(settings, "live_early_fail_max_hold_seconds", 240) or 240)
    max_best = float(getattr(settings, "live_early_fail_max_best_points", 1.0) or 1.0)
    min_loss = float(getattr(settings, "live_early_fail_min_loss_points", 2.5) or 2.5)
    max_v3 = float(getattr(settings, "live_early_fail_max_velocity_3s", 0.5) or 0.5)

    if not (min_hold <= hold_seconds <= max_hold):
        return None
    if best_points > max_best:
        return None
    if pnl_points > -min_loss:
        return None
    if live_velocity_3s >= max_v3:
        return None
    return "live_early_fail"
