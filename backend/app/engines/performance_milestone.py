"""50-trade live-readiness milestone — rolling batches of 50 closed trades."""

from typing import Any

from app.config import get_settings
from app.services import trade_store

TARGET_TRADES = 50
TARGET_PROFIT_FACTOR = 3.0
TARGET_WIN_RATE = 50.0
MAX_DRAWDOWN_PCT = 5.0


def _parse_pnl(trade: dict[str, Any]) -> float:
    return float(trade.get("pnlInr") or 0)


def _stats_for_trades(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """PF, win rate, drawdown for a trade list (chronological)."""
    count = len(trades)
    wins = losses = scratches = 0
    gross_profit = gross_loss = 0.0

    cumulative = 0.0
    peak = 0.0
    max_dd_pct = 0.0
    settings = get_settings()
    base_capital = settings.fallback_capital_inr

    for t in trades:
        pnl = _parse_pnl(t)
        if pnl > 0:
            wins += 1
            gross_profit += pnl
        elif pnl < 0:
            losses += 1
            gross_loss += abs(pnl)
        else:
            scratches += 1

        cumulative += pnl
        peak = max(peak, cumulative)
        if peak > 0:
            dd_pct = ((peak - cumulative) / peak) * 100
        elif cumulative < 0:
            dd_pct = (abs(cumulative) / base_capital) * 100
        else:
            dd_pct = 0.0
        max_dd_pct = max(max_dd_pct, dd_pct)

    decided = wins + losses
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (gross_profit if gross_profit > 0 else 0.0)
    win_rate = (wins / decided * 100) if decided else 0.0
    net_pnl = gross_profit - gross_loss

    checks = {
        "tradeCountMet": count >= TARGET_TRADES,
        "profitFactorMet": profit_factor >= TARGET_PROFIT_FACTOR,
        "winRateMet": win_rate >= TARGET_WIN_RATE,
        "drawdownMet": max_dd_pct <= MAX_DRAWDOWN_PCT,
    }

    return {
        "tradeCount": count,
        "wins": wins,
        "losses": losses,
        "scratches": scratches,
        "profitFactor": round(profit_factor, 2),
        "winRate": round(win_rate, 1),
        "maxDrawdownPct": round(max_dd_pct, 2),
        "netPnlInr": round(net_pnl, 2),
        "checks": checks,
        "checksPassed": sum(1 for v in checks.values() if v),
        "checksTotal": len(checks),
        "readyForLiveMilestone": all(checks.values()),
    }


def _current_batch_trades(
    all_trades: list[dict[str, Any]],
    offset: int = 0,
) -> tuple[int, int, list[dict[str, Any]]]:
    """
    Rolling 50-trade windows after optional manual reset offset.
    Returns (batch_number, completed_batches, trades_in_current_batch).
    """
    trades = all_trades[offset:]
    total = len(trades)
    completed_batches = total // TARGET_TRADES
    batch_number = completed_batches + 1
    batch_start = completed_batches * TARGET_TRADES
    return batch_number, completed_batches, trades[batch_start:]


def compute_milestone_stats(limit: int = 500) -> dict[str, Any]:
    """Live-readiness stats for the current 50-trade batch (rolls after each 50 closes)."""
    all_trades = trade_store.get_all_closed_trades_chronological(limit=limit)
    offset = trade_store.get_milestone_batch_offset()
    batch_number, completed_batches, batch_trades = _current_batch_trades(all_trades, offset)
    core = _stats_for_trades(batch_trades)
    count = core["tradeCount"]
    checks = core["checks"]
    meta = trade_store.get_milestone_meta()

    return {
        **core,
        "targetTrades": TARGET_TRADES,
        "tradeProgressPct": round(min(100.0, count / TARGET_TRADES * 100), 1),
        "targetProfitFactor": TARGET_PROFIT_FACTOR,
        "targetWinRate": TARGET_WIN_RATE,
        "maxDrawdownLimitPct": MAX_DRAWDOWN_PCT,
        "batchNumber": batch_number,
        "completedBatches": completed_batches,
        "lifetimeTradeCount": len(all_trades),
        "batchOffset": offset,
        "lastResetAt": meta.get("resetAt"),
        "message": _milestone_message(
            batch_number,
            completed_batches,
            len(all_trades),
            count,
            checks,
            core["profitFactor"],
            core["winRate"],
            core["maxDrawdownPct"],
        ),
    }


def _milestone_message(
    batch_number: int,
    completed_batches: int,
    lifetime_count: int,
    batch_count: int,
    checks: dict[str, bool],
    pf: float,
    wr: float,
    dd: float,
) -> str:
    prefix = f"Batch {batch_number}"
    if batch_count >= TARGET_TRADES and all(checks.values()):
        return (
            f"{prefix} passed — PF {pf:.1f}, WR {wr:.0f}%, DD {dd:.1f}% "
            f"({lifetime_count} lifetime)"
        )
    remaining = TARGET_TRADES - batch_count
    if remaining > 0:
        lifetime_note = f" · {lifetime_count} lifetime" if lifetime_count > 0 else ""
        if completed_batches > 0:
            return f"{prefix} · {batch_count}/{TARGET_TRADES} toward review ({completed_batches} batch(es) done){lifetime_note}"
        return f"{remaining} more closed trades needed for batch 1 review"
    misses = []
    if not checks["profitFactorMet"]:
        misses.append(f"PF {pf:.1f} < {TARGET_PROFIT_FACTOR}")
    if not checks["winRateMet"]:
        misses.append(f"WR {wr:.0f}% < {TARGET_WIN_RATE}%")
    if not checks["drawdownMet"]:
        misses.append(f"DD {dd:.1f}% > {MAX_DRAWDOWN_PCT}%")
    return f"{prefix} · " + (" · ".join(misses) if misses else "Building track record")
