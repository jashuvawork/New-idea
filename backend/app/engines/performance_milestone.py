"""50-trade live-readiness milestone — PF, win rate, max drawdown."""

from typing import Any

from app.config import get_settings
from app.services import trade_store

TARGET_TRADES = 50
TARGET_PROFIT_FACTOR = 3.0
TARGET_WIN_RATE = 50.0
MAX_DRAWDOWN_PCT = 5.0


def _parse_pnl(trade: dict[str, Any]) -> float:
    return float(trade.get("pnlInr") or 0)


def compute_milestone_stats(limit: int = 500) -> dict[str, Any]:
    """Lifetime paper stats from archived trades for live-deployment gate."""
    trades = trade_store.get_all_closed_trades(limit=limit)
    trades = sorted(trades, key=lambda t: t.get("closedAt") or t.get("openedAt") or "")

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
    passed = sum(1 for v in checks.values() if v)

    return {
        "tradeCount": count,
        "targetTrades": TARGET_TRADES,
        "tradeProgressPct": round(min(100.0, count / TARGET_TRADES * 100), 1),
        "wins": wins,
        "losses": losses,
        "scratches": scratches,
        "profitFactor": round(profit_factor, 2),
        "targetProfitFactor": TARGET_PROFIT_FACTOR,
        "winRate": round(win_rate, 1),
        "targetWinRate": TARGET_WIN_RATE,
        "maxDrawdownPct": round(max_dd_pct, 2),
        "maxDrawdownLimitPct": MAX_DRAWDOWN_PCT,
        "netPnlInr": round(net_pnl, 2),
        "checks": checks,
        "checksPassed": passed,
        "checksTotal": len(checks),
        "readyForLiveMilestone": all(checks.values()),
        "message": _milestone_message(count, checks, profit_factor, win_rate, max_dd_pct),
    }


def _milestone_message(
    count: int,
    checks: dict[str, bool],
    pf: float,
    wr: float,
    dd: float,
) -> str:
    if all(checks.values()):
        return f"50-trade milestone passed — PF {pf:.1f}, WR {wr:.0f}%, DD {dd:.1f}%"
    remaining = TARGET_TRADES - count
    if remaining > 0:
        return f"{remaining} more closed trades needed for 50-trade review"
    misses = []
    if not checks["profitFactorMet"]:
        misses.append(f"PF {pf:.1f} < {TARGET_PROFIT_FACTOR}")
    if not checks["winRateMet"]:
        misses.append(f"WR {wr:.0f}% < {TARGET_WIN_RATE}%")
    if not checks["drawdownMet"]:
        misses.append(f"DD {dd:.1f}% > {MAX_DRAWDOWN_PCT}%")
    return " · ".join(misses) if misses else "Building track record"
