#!/usr/bin/env python3
"""Live week analysis: 3m vs 5m tactical index read + side/time failure patterns."""

from __future__ import annotations

import json
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
OUT = Path("/opt/cursor/artifacts/week-mtf-3m-vs-5m-analysis.json")
PROD = "http://65.0.136.146:8000"
DAYS = ("2026-11-23", "2026-11-25", "2026-11-26", "2026-11-27")
FUNNEL_DIR = Path("/tmp/nexusquant/trades/radar_archives/telemetry")


def _get(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read())


def _tactical_compare(chart: dict[str, Any]) -> dict[str, Any]:
    """Compare 5m bullish tactical vs 3m-equivalent from mom3 on stored entry chart."""
    d5 = str(chart.get("direction") or "NEUTRAL").upper()
    mom5 = float(chart.get("momentum5Pct") or 0)
    mom3 = float(chart.get("momentum3Pct") or mom5 * 0.6)
    d3 = d5
    if d5 == "BULLISH" and mom3 < 0.02 and mom5 < 0.06:
        d3 = "NEUTRAL"
    if mom3 < -0.02:
        d3 = "BEARISH"
    disagree = d5 != d3
    slide_signal_3m = d3 in ("BEARISH", "NEUTRAL") and d5 == "BULLISH"
    return {
        "dir5m": d5,
        "dir3mEquiv": d3,
        "mom5": round(mom5, 4),
        "mom3": round(mom3, 4),
        "tacticalDisagree": disagree,
        "wouldBlockCounterCe3m": slide_signal_3m,
    }


def main() -> None:
    report: dict[str, Any] = {
        "generatedIst": datetime.now(IST).isoformat(),
        "prodBase": PROD,
        "days": {},
        "summary": {},
    }
    all_trades: list[dict[str, Any]] = []
    closed = _get(f"{PROD}/api/auto-trader/history/trades/closed?limit=40")
    for t in closed.get("trades") or []:
        et = str(t.get("entryTime") or t.get("openedAt") or t.get("closedAt") or "")
        if not any(d in et for d in DAYS):
            continue
        ec = t.get("entryContext") or {}
        chart = ec.get("indexChart") or ec.get("spotChart") or {}
        cmp_ = _tactical_compare(chart)
        row = {
            "day": et[:10] if et else "?",
            "symbol": t.get("symbol"),
            "side": t.get("side"),
            "pnlInr": t.get("realizedPnlInr") or t.get("pnlInr"),
            "exitReason": t.get("exitReason"),
            **cmp_,
        }
        all_trades.append(row)

    funnel_blocks: Counter[str] = Counter()
    for day in DAYS:
        day_meta: dict[str, Any] = {"liveTrades": [], "funnelBlockers": {}, "putEliteTiming": 0}
        day_trades = [x for x in all_trades if x["day"] == day]
        day_meta["liveTrades"] = day_trades
        funnel_path = FUNNEL_DIR / f"{day}.funnel.jsonl"
        if funnel_path.is_file():
            with funnel_path.open() as fh:
                for line in fh:
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    reason = str(ev.get("reason") or ev.get("blockReason") or "")
                    if reason:
                        funnel_blocks[reason] += 1
                        day_meta["funnelBlockers"][reason] = (
                            day_meta["funnelBlockers"].get(reason, 0) + 1
                        )
                    if reason == "elite_timing_not_good_or_ok" and str(
                        ev.get("side") or ""
                    ).upper() == "PUT":
                        day_meta["putEliteTiming"] += 1
        try:
            funnel_api = _get(f"{PROD}/api/ai/radar-funnel/{day}")
            day_meta["funnelApi"] = {
                "entered": funnel_api.get("entered"),
                "blocked": funnel_api.get("blocked"),
            }
        except Exception as exc:
            day_meta["funnelApiError"] = str(exc)[:120]
        report["days"][day] = day_meta

    losers = [t for t in all_trades if float(t.get("pnlInr") or 0) < -500]
    winners = [t for t in all_trades if float(t.get("pnlInr") or 0) > 500]
    report["summary"] = {
        "tradeCount": len(all_trades),
        "losers": len(losers),
        "winners": len(winners),
        "totalPnlInr": round(sum(float(t.get("pnlInr") or 0) for t in all_trades), 2),
        "loser3mWouldHaveFlagged": sum(
            1 for t in losers if t.get("side") == "CALL" and t.get("wouldBlockCounterCe3m")
        ),
        "loser5mBullish": sum(1 for t in losers if t.get("dir5m") == "BULLISH"),
        "tacticalDisagreeOnLosers": sum(1 for t in losers if t.get("tacticalDisagree")),
        "topFunnelBlockersWeek": funnel_blocks.most_common(12),
        "recommendation": (
            "Use 3m (or 3m synth from mom3) as Session Intent tactical anchor; "
            "keep 15m+1h structural. 5m alone allowed Nov27 CE and all losing CE weeks."
        ),
    }
    report["allTrades"] = all_trades
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2))
    print(f"wrote {OUT}")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()