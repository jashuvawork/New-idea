"""Session outcome → mode weights — promote what paid, demote what bled."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import AutoTraderState


@dataclass
class ModeSessionStats:
    mode: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    net_pnl_inr: float = 0.0
    profit_factor: float = 0.0
    win_rate: float = 0.0
    best_points_max: float = 0.0


def _mode_of(trade: Any) -> str:
    mode = str(getattr(trade, "mode", "") or "").strip().lower()
    if mode:
        return mode
    ctx = getattr(trade, "entryContext", None) or {}
    if isinstance(ctx, dict):
        return str(ctx.get("selectionMode") or "").strip().lower()
    return ""


def compute_mode_stats(trades: list[Any]) -> dict[str, ModeSessionStats]:
    buckets: dict[str, list[Any]] = {}
    for t in trades:
        mode = _mode_of(t)
        if not mode:
            mode = "unknown"
        buckets.setdefault(mode, []).append(t)

    out: dict[str, ModeSessionStats] = {}
    for mode, rows in buckets.items():
        wins = sum(1 for t in rows if float(getattr(t, "pnl_inr", 0) or 0) > 0)
        losses = sum(1 for t in rows if float(getattr(t, "pnl_inr", 0) or 0) < 0)
        net = sum(float(getattr(t, "pnl_inr", 0) or 0) for t in rows)
        gross_win = sum(float(getattr(t, "pnl_inr", 0) or 0) for t in rows if float(getattr(t, "pnl_inr", 0) or 0) > 0)
        gross_loss = abs(sum(float(getattr(t, "pnl_inr", 0) or 0) for t in rows if float(getattr(t, "pnl_inr", 0) or 0) < 0))
        pf = gross_win if gross_loss <= 0 else (gross_win / gross_loss if gross_loss else 0.0)
        best_max = max((float(getattr(t, "best_pnl_points", 0) or 0) for t in rows), default=0.0)
        n = len(rows)
        out[mode] = ModeSessionStats(
            mode=mode,
            trades=n,
            wins=wins,
            losses=losses,
            net_pnl_inr=round(net, 2),
            profit_factor=round(pf, 2),
            win_rate=round((wins / n * 100) if n else 0.0, 1),
            best_points_max=best_max,
        )
    return out


def mode_session_rank_bonus(mode: str, mode_stats: dict[str, ModeSessionStats]) -> float:
    """
    Outcome-driven mode tilt for today's book.
    Positive PF modes get promoted; bleeding modes get demoted.
    """
    settings = get_settings()
    if not getattr(settings, "session_mode_feedback_enabled", True):
        return 0.0
    key = (mode or "").strip().lower()
    stats = mode_stats.get(key)
    if stats is None or stats.trades < int(getattr(settings, "session_mode_feedback_min_trades", 2) or 2):
        return 0.0

    target = float(getattr(settings, "edge_session_pf_target", 2.5) or 2.5)
    pf = stats.profit_factor
    bonus = 0.0
    if pf >= target and stats.wins >= 1:
        bonus = min(18.0, 6.0 + (pf - target) * 4.0)
    elif pf >= 1.2 and stats.net_pnl_inr > 0:
        bonus = 4.0
    elif stats.losses >= 2 and stats.net_pnl_inr < 0:
        bonus = -min(22.0, 8.0 + abs(stats.net_pnl_inr) / 5000.0)
    elif pf < 0.6 and stats.trades >= 2:
        bonus = -12.0
    return round(bonus, 2)


def session_has_green_explosion(state: AutoTraderState, trades: Optional[list[Any]] = None) -> bool:
    """True once any explosion trade went green (pnl>0 or best≥1pt)."""
    if trades is None:
        from app.engines.pretrade_validator import collect_session_trades

        trades = collect_session_trades(state)
    for t in trades:
        mode = _mode_of(t)
        if mode != "explosion":
            continue
        pnl = float(getattr(t, "pnl_inr", 0) or 0)
        best = float(getattr(t, "best_pnl_points", 0) or 0)
        if pnl > 0 or best >= 1.0:
            return True
    # Also check in-memory paper trades (bestPnlPoints may not be on TradeRecord yet)
    for t in getattr(state, "closedPaperTrades", []) or []:
        ctx = getattr(t, "entryContext", None) or {}
        if str(ctx.get("selectionMode") or "").lower() != "explosion":
            continue
        if float(getattr(t, "pnlInr", 0) or 0) > 0:
            return True
        if float(getattr(t, "bestPnlPoints", 0) or 0) >= 1.0:
            return True
    return False


def cap_lots_until_first_green(lots: int, state: AutoTraderState, *, mode: str = "") -> int:
    """Keep explosion size tiny until session proves a green explosion."""
    settings = get_settings()
    if not getattr(settings, "size_until_first_green_enabled", True):
        return lots
    if (mode or "").lower() != "explosion":
        return lots
    if session_has_green_explosion(state):
        return lots
    cap = int(getattr(settings, "size_until_first_green_lot_cap", 6) or 6)
    return min(max(0, lots), cap)
