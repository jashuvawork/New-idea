"""Weekly review dashboard — trades, skips, expectancy, policy violations, goals."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.performance_milestone import _stats_for_trades
from app.models.schemas import AutoTraderState, SymbolSnapshot
from app.services import trade_store

IST = ZoneInfo("Asia/Kolkata")


def _parse_date(value: str | datetime | None) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    iso = str(value)
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    except ValueError:
        return None


def _trade_context(trade: dict[str, Any]) -> dict[str, Any]:
    return trade.get("entryContext") or trade.get("context") or {}


def detect_policy_violations(trade: dict[str, Any]) -> list[str]:
    """Retroactive checks against Jul-7-style failure patterns."""
    settings = get_settings()
    ctx = _trade_context(trade)
    mode = str(ctx.get("selectionMode") or trade.get("strategyType") or "").lower()
    side = str(trade.get("side") or "").upper()
    breadth = str(ctx.get("breadth") or "NEUTRAL").upper()
    prem = float(trade.get("entryPremium") or 0)
    lots = int(trade.get("lots") or 0)
    tqs = float(ctx.get("tqs") or 0)
    psych = str(ctx.get("psychology") or ctx.get("psychologyLabel") or "").upper()

    violations: list[str] = []
    cheap_thresh = settings.expiry_cheap_premium_threshold_inr
    cheap_cap = settings.expiry_cheap_premium_lot_cap
    if prem > 0 and prem <= cheap_thresh and lots > cheap_cap:
        violations.append(f"cheap_premium_lots_{lots}_gt_{cheap_cap}")

    low_tqs_thresh = settings.expiry_low_tqs_lot_cap_tqs
    low_tqs_cap = settings.expiry_low_tqs_lot_cap
    if tqs < low_tqs_thresh and lots > low_tqs_cap:
        violations.append(f"low_tqs_lots_{lots}_gt_{low_tqs_cap}")

    if side == "CALL" and breadth == "BEARISH":
        violations.append("counter_breadth_call")
    if side == "PUT" and breadth == "BULLISH":
        violations.append("counter_breadth_put")

    if psych in ("CAUTION", "FEAR") and mode in ("scalp", "quick_sideways"):
        violations.append(f"psychology_{psych.lower()}_scalp")

    if mode == "scalp" and tqs < settings.expiry_scalp_min_symbol_tqs:
        violations.append(f"scalp_tqs_below_{settings.expiry_scalp_min_symbol_tqs:.0f}")

    if mode == "scalp" and prem > settings.quick_sideways_high_premium_threshold_inr:
        violations.append("expensive_scalp_premium")

    return violations


def _breadth_aligned(trade: dict[str, Any]) -> bool:
    ctx = _trade_context(trade)
    side = str(trade.get("side") or "").upper()
    breadth = str(ctx.get("breadth") or "NEUTRAL").upper()
    if breadth == "NEUTRAL":
        return True
    expected = "BULLISH" if side == "CALL" else "BEARISH"
    return breadth == expected


def _expectancy(trades: list[dict[str, Any]]) -> dict[str, float]:
    wins = [float(t.get("pnlInr") or 0) for t in trades if float(t.get("pnlInr") or 0) > 0]
    losses = [abs(float(t.get("pnlInr") or 0)) for t in trades if float(t.get("pnlInr") or 0) < 0]
    n = len(trades)
    if not n:
        return {"perTradeInr": 0.0, "winPct": 0.0, "avgWinInr": 0.0, "avgLossInr": 0.0}

    win_pct = len(wins) / n
    loss_pct = len(losses) / n
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    per_trade = (win_pct * avg_win) - (loss_pct * avg_loss)
    return {
        "perTradeInr": round(per_trade, 2),
        "winPct": round(win_pct * 100, 1),
        "avgWinInr": round(avg_win, 2),
        "avgLossInr": round(avg_loss, 2),
    }


def _trading_week_bounds(now: datetime) -> tuple[str, str, str]:
    """
    Current IST trading week Mon–Fri.
    On Sat/Sun returns the previous completed week; on weekdays Mon through today (or Fri).
    """
    weekday = now.weekday()  # Mon=0 … Sun=6
    if weekday >= 5:
        friday = (now - timedelta(days=weekday - 4)).date()
        monday = friday - timedelta(days=4)
        trade_end = friday
    else:
        monday = (now - timedelta(days=weekday)).date()
        friday = monday + timedelta(days=4)
        trade_end = now.date()
    return monday.strftime("%Y-%m-%d"), friday.strftime("%Y-%m-%d"), trade_end.strftime("%Y-%m-%d")


def _weekday_dates(start: str, end: str) -> list[str]:
    """All Mon–Fri dates from start through end (inclusive)."""
    start_dt = datetime.strptime(start, "%Y-%m-%d").date()
    end_dt = datetime.strptime(end, "%Y-%m-%d").date()
    days: list[str] = []
    cur = start_dt
    while cur <= end_dt:
        if cur.weekday() < 5:
            days.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    return days


def _trades_in_window(days: int = 5) -> tuple[list[dict[str, Any]], str, str, str]:
    """Trades in current Mon–Fri trading week (IST). `days` kept for API compat."""
    now = datetime.now(IST)
    period_start, period_end, trade_through = _trading_week_bounds(now)
    all_closed = trade_store.get_all_closed_trades_chronological(limit=10_000)
    reset_at = trade_store.get_session_reset_at()
    reset_dt = _parse_date(reset_at)

    filtered: list[dict[str, Any]] = []
    for t in all_closed:
        opened = _parse_date(str(t.get("openedAt") or ""))
        if not opened:
            continue
        day = opened.strftime("%Y-%m-%d")
        if day < period_start or day > trade_through:
            continue
        if reset_dt and opened < reset_dt:
            continue
        filtered.append(t)
    return filtered, period_start, period_end, trade_through


def _aggregate_skips(skipped: list[dict[str, Any]]) -> dict[str, Any]:
    by_reason: Counter[str] = Counter()
    by_symbol: Counter[str] = Counter()
    session_blocks: list[dict[str, Any]] = []
    candidate_blocks: list[dict[str, Any]] = []
    near_misses: list[dict[str, Any]] = []

    for s in skipped:
        reason = str(s.get("reason") or "unknown")
        sym = str(s.get("symbol") or "SESSION")
        by_reason[reason] += 1
        by_symbol[sym] += 1
        entry = {
            "symbol": sym,
            "reason": reason,
            "message": s.get("message"),
            "mode": s.get("mode"),
            "score": s.get("score"),
        }
        if sym == "SESSION" or reason.startswith(("worst_day", "expiry_", "loss_streak", "whipsaw", "daily_trade")):
            session_blocks.append(entry)
        elif s.get("reason") in ("explosion_near_miss", "scalp_near_miss") or str(s.get("reason", "")).endswith("near_miss"):
            near_misses.append(entry)
        else:
            candidate_blocks.append(entry)

    return {
        "total": len(skipped),
        "byReason": dict(by_reason.most_common(20)),
        "bySymbol": dict(by_symbol.most_common(10)),
        "sessionBlocks": session_blocks[:12],
        "candidateBlocks": candidate_blocks[:12],
        "nearMisses": near_misses[:8],
    }


def _daily_breakdown(trades: list[dict[str, Any]], period_start: str, trade_through: str) -> list[dict[str, Any]]:
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        opened = _parse_date(str(t.get("openedAt") or ""))
        if not opened:
            continue
        by_day[opened.strftime("%Y-%m-%d")].append(t)

    rows: list[dict[str, Any]] = []
    for day in _weekday_dates(period_start, trade_through):
        day_trades = by_day.get(day, [])
        stats = _stats_for_trades(day_trades)
        violations = sum(len(detect_policy_violations(t)) for t in day_trades)
        rows.append({
            "date": day,
            "weekday": datetime.strptime(day, "%Y-%m-%d").strftime("%a"),
            "trades": stats["tradeCount"],
            "wins": stats["wins"],
            "losses": stats["losses"],
            "netPnlInr": stats["netPnlInr"],
            "profitFactor": stats["profitFactor"],
            "policyViolations": violations,
        })
    return rows


def _assess_goals(
    trades: list[dict[str, Any]],
    daily_rows: list[dict[str, Any]],
    violation_count: int,
    settings,
) -> dict[str, Any]:
    stats = _stats_for_trades(trades)
    exp = _expectancy(trades)
    emergency = settings.emergency_stop_inr
    daily_target = settings.daily_profit_target_inr

    max_daily_loss = min((r["netPnlInr"] for r in daily_rows), default=0.0)
    max_trades_day = max((r["trades"] for r in daily_rows), default=0)
    aligned = sum(1 for t in trades if _breadth_aligned(t))
    aligned_pct = (aligned / len(trades) * 100) if trades else 0.0

    cheap_ok = sum(
        1 for t in trades
        if not any(v.startswith("cheap_premium") for v in detect_policy_violations(t))
    )
    cheap_compliance = (cheap_ok / len(trades) * 100) if trades else 100.0

    safety_pass = (
        violation_count == 0
        and max_daily_loss >= -emergency
        and max_trades_day <= max(6, settings.expiry_max_trades_per_day + 2)
    )
    process_pass = (
        (len(trades) == 0 or max_trades_day <= 5)
        and aligned_pct >= 60
        and cheap_compliance >= 90
    )
    outcome_pass = (
        stats["profitFactor"] >= 1.2
        and exp["perTradeInr"] > 0
        and any(r["netPnlInr"] >= daily_target * 0.5 for r in daily_rows)
    ) if trades else False

    return {
        "safety": {
            "passed": safety_pass,
            "policyViolations": violation_count,
            "maxDailyLossInr": round(max_daily_loss, 2),
            "emergencyStopInr": emergency,
            "maxTradesInDay": max_trades_day,
            "message": (
                "No policy violations and daily loss within emergency stop"
                if safety_pass
                else "Review policy violations or daily loss breach"
            ),
        },
        "process": {
            "passed": process_pass,
            "avgTradesPerDay": round(len(trades) / max(1, len(daily_rows)), 1),
            "breadthAlignedPct": round(aligned_pct, 1),
            "cheapPremiumCompliancePct": round(cheap_compliance, 1),
            "message": (
                "Few trades, aligned sides, lot caps respected"
                if process_pass
                else "Too many trades and/or misaligned entries"
            ),
        },
        "outcome": {
            "passed": outcome_pass,
            "expectancyPerTradeInr": exp["perTradeInr"],
            "profitFactor": stats["profitFactor"],
            "winRate": stats["winRate"],
            "netPnlInr": stats["netPnlInr"],
            "dailyTargetInr": daily_target,
            "message": (
                "Positive expectancy and PF ≥ 1.2"
                if outcome_pass
                else "Focus on safety/process before PnL targets"
            ),
        },
        "overallReady": safety_pass and process_pass and outcome_pass,
    }


def build_weekly_dashboard(
    *,
    days: int = 7,
    state: Optional[AutoTraderState] = None,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
) -> dict[str, Any]:
    """Aggregate weekly review metrics for API / UI."""
    settings = get_settings()
    trades, period_start, period_end, trade_through = _trades_in_window(days)
    stats = _stats_for_trades(trades)
    expectancy = _expectancy(trades)

    violation_rows: list[dict[str, Any]] = []
    for t in trades:
        vlist = detect_policy_violations(t)
        if not vlist:
            continue
        ctx = _trade_context(t)
        violation_rows.append({
            "openedAt": t.get("openedAt"),
            "symbol": t.get("symbol"),
            "side": t.get("side"),
            "strike": t.get("strike"),
            "lots": t.get("lots"),
            "entryPremium": t.get("entryPremium"),
            "pnlInr": t.get("pnlInr"),
            "mode": ctx.get("selectionMode") or t.get("strategyType"),
            "violations": vlist,
        })

    daily = _daily_breakdown(trades, period_start, trade_through)
    skipped_agg = _aggregate_skips(list(state.skipped) if state and state.skipped else [])

    near_misses: list[dict[str, Any]] = []
    if snapshots and state:
        try:
            from app.engines.trade_selector import diagnose_missed_entries

            near_misses = diagnose_missed_entries(snapshots, state)
        except Exception:
            near_misses = []

    guards: dict[str, Any] = {}
    if state:
        guards = {
            "worstDayGuard": (state.chopGuards or {}).get("worstDayGuard"),
            "badDayRouting": (state.chopGuards or {}).get("badDayRouting"),
            "sessionLabel": (state.chopGuards or {}).get("sessionLabel"),
            "entryPolicy": ((state.chopGuards or {}).get("worstDayGuard") or {}).get("entryPolicy"),
        }

    goals = _assess_goals(trades, daily, len(violation_rows), settings)

    reset_raw = trade_store.get_session_reset_at()
    if isinstance(reset_raw, datetime):
        session_reset_at = reset_raw.isoformat()
    elif reset_raw:
        session_reset_at = str(reset_raw)
    else:
        session_reset_at = None

    return {
        "periodDays": 5,
        "periodMode": "trading_week",
        "periodStart": period_start,
        "periodEnd": period_end,
        "tradeThrough": trade_through,
        "generatedAt": datetime.now(IST).isoformat(),
        "sessionResetAt": session_reset_at,
        "summary": {
            **stats,
            "expectancy": expectancy,
        },
        "daily": daily,
        "policyViolations": {
            "count": len(violation_rows),
            "trades": violation_rows[:20],
        },
        "currentSession": {
            "skipped": skipped_agg,
            "nearMisses": near_misses[:8],
            "openTrades": len(state.openPaperTrades) if state else 0,
            "closedToday": len(state.closedPaperTrades) if state else 0,
            "guards": guards,
        },
        "goals": goals,
        "recommendation": _recommendation(goals, stats, violation_rows, skipped_agg),
    }


def _recommendation(
    goals: dict[str, Any],
    stats: dict[str, Any],
    violations: list[dict[str, Any]],
    skipped: dict[str, Any],
) -> str:
    if not stats.get("tradeCount"):
        if skipped.get("total", 0) > 0:
            return "No closed trades in window — guards are blocking entries. Review skipped reasons before loosening rules."
        return "No closed trades in window — wait for setups or check auto-trader is running."

    if violations:
        return (
            f"{len(violations)} trade(s) with policy violations — freeze rule changes; "
            "fix deployment or verify guards are active."
        )
    if not goals["safety"]["passed"]:
        return "Safety layer failing — reduce size or pause until daily loss and violations are under control."
    if not goals["process"]["passed"]:
        return "Process layer needs work — trade less, align with breadth, respect lot caps on cheap premium."
    if not goals["outcome"]["passed"]:
        return "Safety/process OK — continue paper batch; outcome improves with fewer, higher-quality entries."
    return "All three goal layers passing — consider extending freeze and reviewing live-readiness milestone."
