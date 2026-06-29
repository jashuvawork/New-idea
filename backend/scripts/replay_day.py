#!/usr/bin/env python3
"""
Replay a day's trades with the current (Jun 25) exit profile.

Uses OPEN/CLOSE archives only — reconstructs an approximate premium path:
  entry → bestPnlPoints (peak) → exit premium

Limitation: without tick-by-tick data, path shape is estimated; results are
directional, not exact live replay.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from unittest.mock import patch
from zoneinfo import ZoneInfo

# Run from repo root or backend/
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.engines.adaptive_exits import AdaptiveExitPlan, evaluate_adaptive_explosion_exit, evaluate_adaptive_scalp_exit
from app.engines.simple_profit import get_session_targets
from app.models.schemas import OptimizedProfile, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")

LOT_MULT = {
    "NIFTY": 65,
    "BANKNIFTY": 30,
    "SENSEX": 20,
}


@dataclass
class ReplayResult:
    trade_id: str
    symbol: str
    side: str
    strategy: str
    orig_lots: int
    replay_lots: int
    actual_pnl: float
    replay_pnl: float
    actual_exit: str
    replay_exit: str
    best_pts: float
    hold_seconds: float
    skipped: bool = False
    skip_reason: str = ""


def fetch_day(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.load(resp)


def lot_mult(symbol: str) -> int:
    s = get_settings()
    return {
        "NIFTY": s.lot_size_nifty,
        "BANKNIFTY": s.lot_size_banknifty,
        "SENSEX": s.lot_size_sensex,
    }.get(symbol.upper(), 25)


def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(IST)


def premium_path(
    entry: float,
    exit_prem: float,
    best_pts: float,
    steps: int = 24,
) -> list[float]:
    """Triangle path: entry → peak → exit."""
    if steps < 2:
        return [entry, exit_prem]
    peak_prem = entry + max(0.0, best_pts)
    out: list[float] = []
    peak_frac = 0.35 if best_pts > 0.05 else 0.0
    for i in range(steps):
        t = i / (steps - 1)
        if peak_frac > 0 and t <= peak_frac:
            out.append(entry + best_pts * (t / peak_frac))
        elif peak_frac > 0:
            frac = (t - peak_frac) / (1 - peak_frac)
            out.append(peak_prem + (exit_prem - peak_prem) * frac)
        else:
            out.append(entry + (exit_prem - entry) * t)
    return out


def build_trade(row: dict[str, Any], lots: int) -> PaperTrade:
    side = Side(row["side"])
    strat = row.get("strategyType", "SCALP")
    st = StrategyType.EXPLOSIVE if strat == "EXPLOSIVE" else (
        StrategyType.SWING if strat == "SWING" else StrategyType.SCALP
    )
    opened = parse_dt(row["openedAt"])
    ctx = dict(row.get("entryContext") or row.get("context") or {})
    return PaperTrade(
        id=row["id"],
        symbol=row["symbol"],
        side=side,
        strike=float(row.get("strike") or 0),
        entryPremium=float(row["entryPremium"]),
        lots=lots,
        openedAt=opened,
        strategyType=st,
        bestPnlPoints=float(row.get("bestPnlPoints") or 0),
        entryContext=ctx,
    )


def plan_from_open(open_ctx: dict[str, Any] | None, profile: OptimizedProfile, strategy: StrategyType) -> AdaptiveExitPlan:
    if open_ctx and open_ctx.get("exitPlan"):
        return AdaptiveExitPlan.from_dict(open_ctx["exitPlan"])
    settings = get_settings()
    if strategy == StrategyType.EXPLOSIVE:
        return AdaptiveExitPlan(
            stopPoints=settings.explosion_initial_stop_points,
            targetPoints=settings.explosion_target_standard,
            trailArmPoints=settings.explosion_trail_arm_points,
            trailKeepRatio=settings.explosion_trail_keep_ratio,
            microTargetPoints=settings.explosion_micro_target_points,
        )
    return AdaptiveExitPlan(
        stopPoints=profile.stopPoints,
        targetPoints=profile.targetPoints,
        trailArmPoints=3.0,
        trailKeepRatio=0.55,
        microTargetPoints=profile.microTargetPoints,
    )


def replay_trade(
    row: dict[str, Any],
    open_event: dict[str, Any] | None,
    max_lots: int,
) -> ReplayResult:
    actual_pnl = float(row.get("pnlInr") or 0)
    actual_exit = row.get("exitReason") or "?"
    orig_lots = int(row.get("lots") or 1)
    replay_lots = min(orig_lots, max_lots) if max_lots > 0 else orig_lots
    symbol = row["symbol"]
    lm = lot_mult(symbol)
    hold_seconds = float(row.get("holdSeconds") or 0)
    if not hold_seconds and row.get("closedAt") and row.get("openedAt"):
        hold_seconds = (parse_dt(row["closedAt"]) - parse_dt(row["openedAt"])).total_seconds()

    if actual_exit == "SESSION_RESET" or not row.get("closedAt"):
        return ReplayResult(
            trade_id=row["id"],
            symbol=symbol,
            side=row["side"],
            strategy=row.get("strategyType", "?"),
            orig_lots=orig_lots,
            replay_lots=replay_lots,
            actual_pnl=actual_pnl,
            replay_pnl=0.0,
            actual_exit=actual_exit,
            replay_exit="SESSION_RESET",
            best_pts=float(row.get("bestPnlPoints") or 0),
            hold_seconds=hold_seconds,
            skipped=True,
            skip_reason="session_reset",
        )

    entry = float(row["entryPremium"])
    exit_prem = float(row.get("currentPremium") or entry)
    best_pts = float(row.get("bestPnlPoints") or 0)
    if hold_seconds <= 0:
        hold_seconds = 60.0

    trade = build_trade(row, replay_lots)
    profile = get_session_targets()
    open_ctx = (open_event or {}).get("context") or {}
    plan = plan_from_open(open_ctx, profile, trade.strategyType)

    path = premium_path(entry, exit_prem, best_pts)
    opened = parse_dt(row["openedAt"])
    replay_exit: Optional[str] = None
    replay_pnl = 0.0

    for i, prem in enumerate(path):
        hold = hold_seconds * i / max(1, len(path) - 1)
        mock_utc = (opened + timedelta(seconds=hold)).replace(tzinfo=None)
        mock_ist = opened + timedelta(seconds=hold)

        trade.bestPnlPoints = max(trade.bestPnlPoints, prem - entry)

        with patch("app.engines.simple_profit.datetime") as m_utc, patch(
            "app.engines.explosion_profit.datetime"
        ) as m_exp:
            m_utc.utcnow.return_value = mock_utc
            m_exp.now.return_value = mock_ist

            if trade.strategyType == StrategyType.EXPLOSIVE:
                tier = "ELITE" if best_pts >= 10 else "EXPLODING"
                reason, pnl = evaluate_adaptive_explosion_exit(
                    trade, prem, plan, tier, lm,
                )
            else:
                reason, pnl = evaluate_adaptive_scalp_exit(
                    trade, prem, plan, profile, lm,
                )

        if reason:
            replay_exit = reason
            replay_pnl = pnl
            break
        replay_pnl = pnl

    if replay_exit is None:
        replay_exit = "replay_end_of_path"
        replay_pnl = (exit_prem - entry) * replay_lots * lm

    return ReplayResult(
        trade_id=row["id"],
        symbol=symbol,
        side=row["side"],
        strategy=row.get("strategyType", "?"),
        orig_lots=orig_lots,
        replay_lots=replay_lots,
        actual_pnl=actual_pnl,
        replay_pnl=replay_pnl,
        actual_exit=actual_exit,
        replay_exit=replay_exit or "?",
        best_pts=best_pts,
        hold_seconds=hold_seconds,
    )


def summarize(results: list[ReplayResult], label: str) -> None:
    traded = [r for r in results if not r.skipped]
    actual = sum(r.actual_pnl for r in traded)
    replay = sum(r.replay_pnl for r in traded)
    wins_a = sum(1 for r in traded if r.actual_pnl > 50)
    wins_r = sum(1 for r in traded if r.replay_pnl > 50)
    losses_a = sum(1 for r in traded if r.actual_pnl < -50)
    losses_r = sum(1 for r in traded if r.replay_pnl < -50)

    print(f"\n{'=' * 60}")
    print(label)
    print(f"{'=' * 60}")
    print(f"Trades replayed: {len(traded)} (skipped {len(results) - len(traded)} resets)")
    print(f"Actual P&L:   ₹{actual:,.0f}  |  Wins/Losses: {wins_a}/{losses_a}")
    print(f"Replay P&L:   ₹{replay:,.0f}  |  Wins/Losses: {wins_r}/{losses_r}")
    print(f"Delta:        ₹{replay - actual:+,.0f}")

    # by symbol
    by_sym: dict[str, tuple[float, float]] = {}
    for r in traded:
        a, b = by_sym.get(r.symbol, (0.0, 0.0))
        by_sym[r.symbol] = (a + r.actual_pnl, b + r.replay_pnl)
    print("\nBy symbol (actual → replay):")
    for sym, (a, b) in sorted(by_sym.items(), key=lambda x: x[1][0]):
        print(f"  {sym}: ₹{a:,.0f} → ₹{b:,.0f} ({b - a:+,.0f})")

    print("\nReplay exit reasons:")
    for reason, cnt in Counter(r.replay_exit for r in traded).most_common(12):
        pnl = sum(r.replay_pnl for r in traded if r.replay_exit == reason)
        print(f"  {reason}: {cnt} trades, ₹{pnl:,.0f}")

    print("\nBiggest improvements (actual → replay):")
    for r in sorted(traded, key=lambda x: x.replay_pnl - x.actual_pnl, reverse=True)[:8]:
        d = r.replay_pnl - r.actual_pnl
        print(
            f"  {r.symbol} {r.side} {r.orig_lots}→{r.replay_lots}L "
            f"{r.actual_exit}→{r.replay_exit} ₹{r.actual_pnl:,.0f}→₹{r.replay_pnl:,.0f} ({d:+,.0f})"
        )

    print("\nStill large losses under replay:")
    for r in sorted(traded, key=lambda x: x.replay_pnl)[:8]:
        if r.replay_pnl < -1000:
            print(
                f"  {r.symbol} {r.side} {r.replay_lots}L {r.replay_exit} "
                f"₹{r.replay_pnl:,.0f} (was ₹{r.actual_pnl:,.0f} via {r.actual_exit})"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay archived trades with current exit profile")
    parser.add_argument("--date", default="2026-06-29")
    parser.add_argument("--file", help="Local JSON archive (overrides --url)")
    parser.add_argument(
        "--url",
        default="https://www.jashuvatrade.xyz/api/auto-trader/history/2026-06-29",
    )
    parser.add_argument("--max-lots", type=int, default=0, help="0 = use config max_lots_per_trade")
    args = parser.parse_args()

    get_settings.cache_clear()
    settings = get_settings()
    max_lots = args.max_lots or settings.max_lots_per_trade or 40

    if args.file:
        data = json.loads(Path(args.file).read_text())
    else:
        url = args.url.replace("2026-06-29", args.date) if args.date not in args.url else args.url
        if args.date not in url:
            url = f"https://www.jashuvatrade.xyz/api/auto-trader/history/{args.date}"
        data = fetch_day(url)

    trades = data.get("trades", [])
    events = data.get("events", [])
    opens = {e["tradeId"]: e for e in events if e.get("type") == "TRADE_OPENED"}

    print(f"Date: {args.date} | Trades: {len(trades)}")
    print(
        f"Profile: max_lots={max_lots}, explosion_TP={settings.explosion_target_standard}, "
        f"sure_shot={settings.sure_shot_mode_enabled}, adaptive={settings.adaptive_exits_enabled}"
    )

    results = [replay_trade(t, opens.get(t["id"]), max_lots) for t in trades]
    summarize(results, f"Jun 25 profile replay — {args.date}")

    # NIFTY+SENSEX only (would not have taken BANKNIFTY)
    filtered = [r for r in results if r.symbol != "BANKNIFTY"]
    summarize(filtered, f"Same replay — NIFTY+SENSEX only (excl. BANKNIFTY)")


if __name__ == "__main__":
    main()
