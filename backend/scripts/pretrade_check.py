#!/usr/bin/env python3
"""Run pre-trade backtest on today's session — index selection + gate simulation."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.engines.pretrade_validator import (  # noqa: E402
    TradeRecord,
    backtest_session_summary,
    compute_symbol_stats,
    index_rank_from_backtest,
)


def fetch(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.load(resp)


def rows_from_day(data: dict) -> list[TradeRecord]:
    out: list[TradeRecord] = []
    for row in data.get("trades", []):
        if row.get("status") != "CLOSED":
            continue
        out.append(TradeRecord(
            symbol=str(row.get("symbol", "")).upper(),
            side=str(row.get("side", "")).upper(),
            pnl_inr=float(row.get("pnlInr") or 0),
            exit_reason=str(row.get("exitReason") or ""),
            strike=float(row.get("strike") or 0),
            trade_id=str(row.get("id", "")),
        ))
    return out


def simulate_gates(trades: list[TradeRecord]) -> dict:
    """How many historical entries would be blocked by symbol PF gates."""
    from app.config import get_settings

    settings = get_settings()
    blocked = Counter()
    allowed = 0
    for i, _ in enumerate(trades):
        prefix = trades[:i]
        stats = compute_symbol_stats(prefix)
        sym = trades[i].symbol
        st = stats.get(sym)
        if st and st.trades >= settings.pretrade_min_symbol_trades_for_stats:
            if st.profit_factor < settings.pretrade_block_symbol_pf_below:
                blocked["symbol_pf"] += 1
                continue
            if st.net_pnl_inr <= settings.pretrade_block_symbol_net_inr_below:
                blocked["symbol_net"] += 1
                continue
        allowed += 1
    return {"wouldAllow": allowed, "wouldBlock": dict(blocked), "total": len(trades)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-trade session backtest")
    parser.add_argument(
        "--url",
        default="https://www.jashuvatrade.xyz/api/auto-trader/history/2026-06-30",
    )
    parser.add_argument("--date", default=None, help="YYYY-MM-DD overrides URL path")
    args = parser.parse_args()

    url = args.url
    if args.date:
        base = url.rsplit("/", 1)[0]
        url = f"{base}/{args.date}"

    data = fetch(url)
    trades = rows_from_day(data)
    summary = backtest_session_summary(trades)
    stats = compute_symbol_stats(trades)
    ranks = index_rank_from_backtest(stats)
    sim = simulate_gates(trades)

    print("=== Pre-trade session backtest ===")
    print(f"Closed trades: {len(trades)}")
    print(f"Recommended index: {summary.get('recommendedIndex')}")
    print(f"Index rank adjustments: {ranks}")
    print()
    for sym, st in sorted(stats.items()):
        print(
            f"  {sym}: {st.trades} trades WR={st.win_rate}% "
            f"PF={st.profit_factor} net=₹{st.net_pnl_inr:,.0f}"
        )
    print()
    print(f"Gate simulation: {sim}")
    reasons = Counter(t.exit_reason for t in trades)
    print(f"Exit reasons: {dict(reasons)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
