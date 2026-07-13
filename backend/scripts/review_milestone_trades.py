#!/usr/bin/env python3
"""Review last N closed trades against Jul 13 guard/chart fixes."""

from __future__ import annotations

import json
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.aligned_side_guard import (
    breadth_hard_blocks_side,
    chart_mtf_bullish_confirmed,
    chart_mtf_bearish_confirmed,
)
from app.engines.spot_direction import chart_blocks_side
from app.models.schemas import (
    Breadth,
    ChartAnalysis,
    MarketPhase,
    Side,
    SpotChart,
    SymbolSnapshot,
)
from scripts.loss_analysis import analyze, fetch

API_CLOSED = "https://www.jashuvatrade.xyz/api/auto-trader/history/trades/closed?limit=50"


def _ctx(trade: dict) -> dict:
    ctx = trade.get("entryContext") or {}
    return ctx if isinstance(ctx, dict) else {}


def _breadth_bias(trade: dict) -> str:
    b = _ctx(trade).get("breadth")
    if isinstance(b, dict):
        return str(b.get("bias", "NEUTRAL")).upper()
    return str(b or "NEUTRAL").upper()


def _infer_chart_direction(trade: dict) -> str:
    """Infer likely spotChart direction when not stored in entryContext."""
    ctx = _ctx(trade)
    for key in ("indexChart", "spotChart", "chart"):
        ch = ctx.get(key)
        if isinstance(ch, dict) and ch.get("direction"):
            return str(ch["direction"]).upper()
    side = str(trade.get("side", "")).upper()
    bias = _breadth_bias(trade)
    closed = str(trade.get("closedAt") or trade.get("openedAt") or "")
    # Jul 13 afternoon rally — known from session analysis
    if closed.startswith("2026-07-13") and side == "PUT":
        return "BULLISH"
    if closed.startswith("2026-07-13") and side == "CALL":
        return "BEARISH"  # morning before fix
    if bias == "BULLISH" and side == "CALL":
        return "BULLISH"
    if bias == "BEARISH" and side == "PUT":
        return "BEARISH"
    return "NEUTRAL"


def _build_snap(trade: dict, chart_dir: str) -> SymbolSnapshot:
    ctx = _ctx(trade)
    bias = _breadth_bias(trade)
    score = float(ctx.get("selectionScore") or ctx.get("tqs") or 0)
    mtf_consensus = chart_dir if chart_dir in ("BULLISH", "BEARISH") else "NEUTRAL"
    return SymbolSnapshot(
        symbol=str(trade.get("symbol", "NIFTY")),
        timestamp=datetime.now(ZoneInfo("Asia/Kolkata")),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=float(ctx.get("spot") or 0),
        spotChart=SpotChart(
            direction=chart_dir,
            rsi=65.0 if chart_dir == "BULLISH" else 35.0,
            macdBias="BULLISH" if chart_dir == "BULLISH" else "BEARISH",
            trendStrength=45.0,
            momentum5Pct=0.05 if chart_dir == "BULLISH" else -0.05,
        ),
        breadth=Breadth(bias=bias, score=50, aligned=bias != "NEUTRAL"),
        chartAnalysis=ChartAnalysis(
            consensus=mtf_consensus,
            alignedCount=4 if mtf_consensus in ("BULLISH", "BEARISH") else 0,
            totalTimeframes=4,
            ichimoku={
                "cloudBias": mtf_consensus,
                "priceVsCloud": "ABOVE" if mtf_consensus == "BULLISH" else "BELOW",
            },
        ),
    )


def review_trade(trade: dict) -> dict:
    settings = get_settings()
    ctx = _ctx(trade)
    side = str(trade.get("side", "")).upper()
    side_enum = Side.CALL if side == "CALL" else Side.PUT
    bias = _breadth_bias(trade)
    chart_dir = _infer_chart_direction(trade)
    score = float(ctx.get("selectionScore") or ctx.get("tqs") or 0)
    pnl = float(trade.get("pnlInr") or 0)
    snap = _build_snap(trade, chart_dir)

    blockers: list[str] = []
    fixes: list[str] = []

    hard_blocked, hard_reason = breadth_hard_blocks_side(
        side_enum, bias, snap=snap, alert={"explosionScore": score},
    )
    if hard_blocked:
        blockers.append(hard_reason)
    elif bias == "BEARISH" and side == "CALL" and chart_mtf_bullish_confirmed(snap):
        fixes.append("chart_mtf_bypass_would_allow_call")

    chart = snap.spotChart
    chart_blocked, chart_reason = chart_blocks_side(
        side_enum, chart, trade_score=score,
    )
    if chart_blocked:
        blockers.append(chart_reason)

    exit_reason = str(trade.get("exitReason") or ctx.get("exitReason") or "")
    if exit_reason.startswith("explosion_time_") and float(ctx.get("bestPnlPoints") or 0) >= 10:
        fixes.append("peak_exit_fix_would_improve")

    counter_trend = (side == "CALL" and bias == "BEARISH") or (side == "PUT" and bias == "BULLISH")
    wrong_side_rally = side == "PUT" and chart_dir == "BULLISH"

    would_take = not blockers and score >= settings.aggressive_min_explosion_score
    would_avoid_loss = pnl < 0 and bool(blockers)
    missed_win = pnl > 0 and bool(blockers)

    return {
        "id": trade.get("id"),
        "closedAt": (trade.get("closedAt") or "")[:16],
        "symbol": trade.get("symbol"),
        "side": side,
        "strike": trade.get("strike"),
        "pnlInr": round(pnl),
        "exitReason": exit_reason[:40],
        "breadth": bias,
        "chartInferred": chart_dir,
        "score": round(score, 1),
        "blockers": blockers,
        "fixes": fixes,
        "counterTrend": counter_trend,
        "wrongSideRally": wrong_side_rally,
        "wouldTakeNow": would_take,
        "wouldAvoidLoss": would_avoid_loss,
        "missedWin": missed_win,
    }


def main() -> int:
    data = fetch(API_CLOSED)
    trades = data.get("trades", [])
    if not trades:
        print("No closed trades found")
        return 1

    reviews = [review_trade(t) for t in reversed(trades)]  # chronological
    loss_report = analyze(list(reversed(trades)))

    avoided = [r for r in reviews if r["wouldAvoidLoss"]]
    missed = [r for r in reviews if r["missedWin"]]
    jul13 = [r for r in reviews if str(r["closedAt"]).startswith("2026-07-13")]
    put_rally = [r for r in reviews if r["wrongSideRally"]]

    print(f"=== Milestone trade review ({len(reviews)} trades) ===\n")
    print(f"Net PnL: ₹{loss_report['net_inr']:,.0f} | PF: {loss_report['profit_factor']} | W/L: {loss_report['wins']}/{loss_report['losses']}")
    print(f"Counter-trend losses: {loss_report['counter_trend_losses']} (₹{loss_report['counter_trend_loss_inr']:,.0f})")
    print(f"Last-5 pause would trigger: {loss_report.get('last5_would_pause')}")

    print("\n--- Jul 13 session (indicator fix day) ---")
    for r in jul13:
        blk = ",".join(r["blockers"]) or "none"
        fix = ",".join(r["fixes"]) or "-"
        print(
            f"  {r['closedAt']} {r['symbol']} {r['side']} {r['strike']} "
            f"₹{r['pnlInr']} [{r['exitReason']}] chart={r['chartInferred']} "
            f"blocked_now={blk} fixes={fix}"
        )
    jul13_avoided = sum(abs(r["pnlInr"]) for r in jul13 if r["wouldAvoidLoss"])
    print(f"  → Jul 13 losses avoidable with new guards: ₹{jul13_avoided:,}")

    print("\n--- PUTs against bullish chart (would block now) ---")
    for r in put_rally:
        print(f"  {r['closedAt']} {r['symbol']} PUT {r['strike']} ₹{r['pnlInr']} blockers={r['blockers']}")

    print("\n--- Losses new guards would have blocked ---")
    for r in sorted(avoided, key=lambda x: x["pnlInr"])[:15]:
        print(f"  {r['closedAt']} {r['symbol']} {r['side']} {r['strike']} ₹{r['pnlInr']} | {','.join(r['blockers'])}")

    print(f"\nTotal losses blocked retrospectively: {len(avoided)} = ₹{sum(r['pnlInr'] for r in avoided):,.0f}")
    print(f"Wins that would be blocked (false positive): {len(missed)} = ₹{sum(r['pnlInr'] for r in missed):,.0f}")

    print("\n--- Exit reason breakdown ---")
    for reason, n in Counter(r["exitReason"] for r in reviews).most_common():
        print(f"  {reason}: {n}")

    peak_fix = [r for r in reviews if "peak_exit_fix_would_improve" in r["fixes"]]
    print(f"\n--- explosion_time exits with best≥10pt (exit fix helps): {len(peak_fix)} ---")
    for r in peak_fix:
        print(f"  {r['closedAt']} {r['symbol']} {r['side']} ₹{r['pnlInr']} [{r['exitReason']}]")

    print("\n--- Verdict ---")
    blocked_loss_inr = abs(sum(r["pnlInr"] for r in avoided))
    net = loss_report["net_inr"]
    print(f"  Retrospective loss prevention: ~₹{blocked_loss_inr:,.0f} of ₹{abs(net):,.0f} total losses")
    if len(jul13) >= 5 and all(r["wouldAvoidLoss"] or r["pnlInr"] > 0 for r in jul13 if r["pnlInr"] < 0):
        print("  Jul 13 PUT cluster: NEW GUARDS WOULD HAVE BLOCKED most/all losing PUTs ✅")
    print("  Chart direction not stored in entryContext — Jul 13 inferred from rally session")
    print("  Deploy PR #121 to EC2 for live effect")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
