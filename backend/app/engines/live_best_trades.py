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
    """Live explosion orders require grade S.

    Score, chart alignment, pad maturity, position count, and the one-loss
    pause stay on the shared gates. This bar is only the grade.
    """
    del state, snapshots, chart_meta
    settings = get_settings()
    if not bool(getattr(settings, "live_best_trades_only_enabled", False)):
        return False, "ok", {"liveBestTradeGate": False}
    if not bool(getattr(settings, "enable_live_trading", False)):
        return False, "ok", {"liveBestTradeGate": False}
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False, "ok", {"liveBestTradeGate": False}

    meta: dict[str, Any] = {"liveBestTradeGate": True}
    resolved = dict(ranking or {})
    if not resolved.get("grade") and getattr(candidate, "explosion_event", None) is not None:
        from app.engines.trade_ranking import rank_entry_candidate

        resolved = rank_entry_candidate(candidate, snapshot=snap) or {}
    grade = str(resolved.get("grade") or "").upper()
    min_grade = str(getattr(settings, "live_best_trades_min_grade", "S") or "S").upper()
    meta["grade"] = grade
    meta["minGrade"] = min_grade
    if min_grade == "S" and grade != "S":
        return True, "live_best_trades_requires_grade_s", meta
    if min_grade == "A" and grade not in {"S", "A"}:
        return True, "live_best_trades_requires_grade_a_or_s", meta
    return False, "ok", meta


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
