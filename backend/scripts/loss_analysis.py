#!/usr/bin/env python3
"""Diagnose session losses — what failed and which new gates would have blocked entries."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.engines.pretrade_validator import TradeRecord, compute_symbol_stats


@dataclass
class LossRow:
    trade_id: str
    symbol: str
    side: str
    strike: float
    pnl_inr: float
    exit_reason: str
    breadth: str
    mode: str
    score: float
    has_execution_chart: bool
    blockers: list[str]


def fetch(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.load(resp)


def rows_from_day(data: dict) -> list[dict]:
    return [t for t in data.get("trades", []) if t.get("status") == "CLOSED"]


def _ctx(trade: dict) -> dict:
    ctx = trade.get("entryContext") or {}
    return ctx if isinstance(ctx, dict) else {}


def _breadth_bias(trade: dict) -> str:
    ctx = _ctx(trade)
    b = ctx.get("breadth")
    if isinstance(b, dict):
        return str(b.get("bias", "NEUTRAL")).upper()
    return str(b or "NEUTRAL").upper()


def _counter_trend(trade: dict) -> bool:
    side = str(trade.get("side", "")).upper()
    bias = _breadth_bias(trade)
    if side == "CALL" and bias == "BEARISH":
        return True
    if side == "PUT" and bias == "BULLISH":
        return True
    return False


def _would_block_counter_breadth(trade: dict, settings) -> bool:
    if not _counter_trend(trade):
        return False
    ctx = _ctx(trade)
    score = float(ctx.get("selectionScore") or ctx.get("tqs") or ctx.get("confidence") or 0)
    return score < settings.counter_breadth_min_score


def _would_block_pretrade_symbol(trade: dict, prior: list[TradeRecord], settings) -> bool:
    stats = compute_symbol_stats(prior)
    st = stats.get(str(trade.get("symbol", "")).upper())
    if not st or st.trades < settings.pretrade_min_symbol_trades_for_stats:
        return False
    if st.profit_factor < settings.pretrade_block_symbol_pf_below:
        return True
    if st.net_pnl_inr <= settings.pretrade_block_symbol_net_inr_below:
        return True
    return False


def _instrument_key(trade: dict) -> str:
    sym = str(trade.get("symbol", "")).upper()
    side = str(trade.get("side", "")).upper()
    strike = int(float(trade.get("strike") or 0))
    return f"{sym}:{side}:{strike}"


def _would_block_instrument_churn(trade: dict, prior_losses: list[dict], settings) -> bool:
    """Same strike had a loss recently — instrument cooldown."""
    key = _instrument_key(trade)
    for p in reversed(prior_losses):
        if _instrument_key(p) != key:
            continue
        if (p.get("pnlInr") or 0) < 0:
            return True
        if (p.get("pnlInr") or 0) > 0 and str(_ctx(p).get("exitReason", "")).find("micro") >= 0:
            return True
    return False


def analyze(trades: list[dict]) -> dict:
    settings = get_settings()
    losses = [t for t in trades if (t.get("pnlInr") or 0) < 0]
    wins = [t for t in trades if (t.get("pnlInr") or 0) > 0]

    net = sum(t.get("pnlInr", 0) for t in trades)
    gross_win = sum(t.get("pnlInr", 0) for t in wins)
    gross_loss = sum(t.get("pnlInr", 0) for t in losses)

    by_instrument: dict[str, dict] = defaultdict(lambda: {"n": 0, "net": 0.0, "losses": 0})
    loss_rows: list[LossRow] = []
    gate_blocks = Counter()
    loss_blockers = Counter()

    prior_records: list[TradeRecord] = []
    prior_losses: list[dict] = []

    for t in trades:
        ctx = _ctx(t)
        pnl = float(t.get("pnlInr") or 0)
        sym = str(t.get("symbol", "")).upper()
        side = str(t.get("side", "")).upper()
        strike = float(t.get("strike") or 0)
        ik = f"{sym} {side} {int(strike)}"
        by_instrument[ik]["n"] += 1
        by_instrument[ik]["net"] += pnl
        if pnl < 0:
            by_instrument[ik]["losses"] += 1

        blockers: list[str] = []
        if _would_block_counter_breadth(t, settings):
            blockers.append("counter_breadth")
            gate_blocks["counter_breadth"] += 1
        if _would_block_pretrade_symbol(t, prior_records, settings):
            blockers.append("pretrade_symbol_pf")
            gate_blocks["pretrade_symbol_pf"] += 1
        if _would_block_instrument_churn(t, prior_losses, settings):
            blockers.append("instrument_cooldown")
            gate_blocks["instrument_cooldown"] += 1
        if _counter_trend(t) and not ctx.get("executionChart"):
            blockers.append("chart_mtf_not_deployed")
        if pnl < 0:
            for b in blockers:
                loss_blockers[b] += 1
            loss_rows.append(LossRow(
                trade_id=str(t.get("id", "")),
                symbol=sym,
                side=side,
                strike=strike,
                pnl_inr=pnl,
                exit_reason=str(t.get("exitReason") or ctx.get("exitReason") or ""),
                breadth=_breadth_bias(t),
                mode=str(ctx.get("selectionMode") or "unknown"),
                score=float(ctx.get("selectionScore") or ctx.get("tqs") or 0),
                has_execution_chart=bool(ctx.get("executionChart")),
                blockers=blockers,
            ))

        if pnl < 0:
            prior_losses.append(t)
        prior_records.append(TradeRecord(
            symbol=sym,
            side=side,
            pnl_inr=pnl,
            exit_reason=str(t.get("exitReason") or ""),
            strike=strike,
            trade_id=str(t.get("id", "")),
        ))

    counter_losses = [r for r in loss_rows if _counter_trend({"side": r.side, "entryContext": {"breadth": r.breadth}})]
    call_bearish = [r for r in counter_losses if r.side == "CALL"]
    put_bullish = [r for r in counter_losses if r.side == "PUT"]

    avg_win = gross_win / len(wins) if wins else 0
    avg_loss = gross_loss / len(losses) if losses else 0
    pf = abs(gross_win / gross_loss) if gross_loss else 0

    last5 = trades[-5:] if len(trades) >= 5 else trades
    l5_losses = sum(1 for t in last5 if (t.get("pnlInr") or 0) < 0)
    l5_net = sum(t.get("pnlInr", 0) for t in last5)

    return {
        "total": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "net_inr": round(net, 2),
        "profit_factor": round(pf, 2),
        "avg_win_inr": round(avg_win, 2),
        "avg_loss_inr": round(avg_loss, 2),
        "exit_reasons": dict(Counter(t.get("exitReason") or _ctx(t).get("exitReason") for t in trades)),
        "loss_exit_reasons": dict(Counter(r.exit_reason for r in loss_rows)),
        "worst_instruments": sorted(
            [{"instrument": k, **v} for k, v in by_instrument.items()],
            key=lambda x: x["net"],
        )[:15],
        "counter_trend_losses": len(counter_losses),
        "counter_trend_loss_inr": round(sum(r.pnl_inr for r in counter_losses), 2),
        "call_in_bearish_losses": len(call_bearish),
        "call_in_bearish_inr": round(sum(r.pnl_inr for r in call_bearish), 2),
        "put_in_bullish_losses": len(put_bullish),
        "gate_would_block_entries": dict(gate_blocks),
        "losses_with_blockers": dict(loss_blockers),
        "losses_without_execution_chart": sum(1 for r in loss_rows if not r.has_execution_chart),
        "top_loss_trades": sorted(loss_rows, key=lambda r: r.pnl_inr)[:10],
    }


def print_report(report: dict, date: str) -> None:
    print(f"=== Loss analysis — {date} ===\n")
    print(f"Closed: {report['total']} | Wins: {report['wins']} | Losses: {report['losses']}")
    print(f"Net: ₹{report['net_inr']:,.0f} | PF: {report['profit_factor']}")
    print(f"Avg win: ₹{report['avg_win_inr']:,.0f} | Avg loss: ₹{report['avg_loss_inr']:,.0f}")
    print(f"\nExit reasons: {report['exit_reasons']}")
    print(f"Loss exits: {report['loss_exit_reasons']}")

    print("\n--- Root causes (loss drivers) ---")
    print(f"1. Stop-loss exits: {report['loss_exit_reasons'].get('simple_stop_loss', 0)}/{report['losses']} losses")
    print(f"   → Avg loss ₹{abs(report['avg_loss_inr']):,.0f} vs avg win ₹{report['avg_win_inr']:,.0f} — need fewer bad entries, not just tighter stops")
    print(f"2. Counter-trend entries: {report['counter_trend_losses']} losses = ₹{report['counter_trend_loss_inr']:,.0f}")
    print(f"   → CALL in BEARISH breadth: {report['call_in_bearish_losses']} losses = ₹{report['call_in_bearish_inr']:,.0f}")
    print(f"3. No execution chart on losses: {report['losses_without_execution_chart']}/{report['losses']} (MTF pre-test not deployed yet)")

    print("\n--- Worst instruments ---")
    for row in report["worst_instruments"]:
        print(f"  {row['instrument']}: {row['n']} trades net=₹{row['net']:,.0f} ({row['losses']} losses)")

    print("\n--- New gates would have blocked (simulation) ---")
    for gate, n in sorted(report["gate_would_block_entries"].items(), key=lambda x: -x[1]):
        loss_n = report["losses_with_blockers"].get(gate, 0)
        print(f"  {gate}: {n} entries ({loss_n} were losses)")

    print("\n--- Last 5 trades gate (new) ---")
    if len(trades) >= 5:
        last5 = trades[-5:]
        l5_losses = sum(1 for t in last5 if t.pnl_inr < 0)
        l5_net = sum(t.pnl_inr for t in last5)
        print(f"  Last 5: {l5_losses} losses, net ₹{l5_net:,.0f}")
        if l5_losses >= 4:
            print("  → SESSION PAUSED (4+ losses in last 5)")
        elif l5_losses >= 3:
            print("  → Elevated rank floor 72, explosion-only scalps blocked")
    print("  Blocks CALL when index 1m/5m/15m/1h/4h declining + premium fading")
    print("  Blocks PUT when index rallying on multiple timeframes")
    print("  Requires ≥3/5 TF alignment + no 15m+1h conflict")

    print("\n--- Largest single losses ---")
    for r in report["top_loss_trades"]:
        blk = ",".join(r.blockers) if r.blockers else "none"
        print(
            f"  {r.symbol} {r.side} {int(r.strike)} ₹{r.pnl_inr:,.0f} "
            f"[{r.exit_reason}] breadth={r.breadth} blockers={blk}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Session loss diagnosis")
    parser.add_argument("--date", default="2026-06-30")
    parser.add_argument(
        "--url",
        default="https://www.jashuvatrade.xyz/api/auto-trader/history/{date}",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    url = args.url.format(date=args.date)
    data = fetch(url)
    trades = rows_from_day(data)
    report = analyze(trades)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_report(report, args.date)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
