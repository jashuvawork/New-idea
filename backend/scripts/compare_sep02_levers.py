#!/usr/bin/env python3
"""Compare Sep 2 premium-tape replay with levers ON vs OFF (requires production tape)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Optional

from app.config import Settings


@dataclass
class ReplaySummary:
    label: str
    status: str
    trade_count: int
    net_pnl_inr: float
    wins: int
    losses: int
    top_gates: list[tuple[str, int]]
    trades: list[dict[str, Any]]


def _summarize(label: str, report: dict[str, Any]) -> ReplaySummary:
    trades = list(report.get("trades") or [])
    wins = sum(1 for t in trades if float(t.get("pnlInr") or 0) > 0)
    losses = sum(1 for t in trades if float(t.get("pnlInr") or 0) < 0)
    gates = sorted(
        (report.get("gateStats") or {}).items(),
        key=lambda row: -int(row[1]),
    )[:8]
    return ReplaySummary(
        label=label,
        status=str(report.get("status") or ""),
        trade_count=int(report.get("tradeCount") or len(trades)),
        net_pnl_inr=float(report.get("netPnlInr") or 0),
        wins=wins,
        losses=losses,
        top_gates=[(str(k), int(v)) for k, v in gates],
        trades=trades,
    )


def _run_replay(
    date: str,
    settings: Settings,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    side: Optional[str] = None,
) -> dict[str, Any]:
    from app.engines.eod_local_base_replay import replay_local_base_day

    return replay_local_base_day(
        date,
        settings=settings,
        window_start=start,
        window_end=end,
        side_filter=side,
    )


def _levers_off_settings(base: Settings) -> Settings:
    data = deepcopy(base.model_dump())
    data["top_moments_exploding_elite_grade_b_enabled"] = False
    data["top_moments_momentum_rally_grade_b_enabled"] = False
    data["index_rally_side_flip_neutral_macd_mom5_waiver_enabled"] = False
    return Settings(**data)


def _levers_on_settings(base: Settings) -> Settings:
    data = deepcopy(base.model_dump())
    data["top_moments_exploding_elite_grade_b_enabled"] = True
    data["top_moments_momentum_rally_grade_b_enabled"] = True
    data["index_rally_side_flip_neutral_macd_mom5_waiver_enabled"] = True
    return Settings(**data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="2026-09-02")
    parser.add_argument("--start", default="", help="Optional IST window start HH:MM[:SS]")
    parser.add_argument("--end", default="", help="Optional IST window end HH:MM[:SS]")
    parser.add_argument("--side", default="", choices=["", "CALL", "PUT"])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    base = Settings()
    start = args.start or None
    end = args.end or None
    side = args.side or None

    off = _run_replay(
        args.date,
        _levers_off_settings(base),
        start=start,
        end=end,
        side=side,
    )
    on = _run_replay(
        args.date,
        _levers_on_settings(base),
        start=start,
        end=end,
        side=side,
    )

    off_sum = _summarize("levers_off", off)
    on_sum = _summarize("levers_on", on)

    off_keys = {
        f"{t.get('entryAt')}|{t.get('symbol')}|{t.get('side')}|{t.get('strike')}"
        for t in off_sum.trades
    }
    new_with_levers = [
        t
        for t in on_sum.trades
        if f"{t.get('entryAt')}|{t.get('symbol')}|{t.get('side')}|{t.get('strike')}"
        not in off_keys
    ]

    out = {
        "date": args.date,
        "window": {"start": start, "end": end, "side": side},
        "liveActual": {"tradeCount": 2, "netPnlInr": -15042.05},
        "leversOff": off_sum.__dict__,
        "leversOn": on_sum.__dict__,
        "delta": {
            "tradeCount": on_sum.trade_count - off_sum.trade_count,
            "netPnlInr": round(on_sum.net_pnl_inr - off_sum.net_pnl_inr, 0),
        },
        "tradesUnlockedByLevers": new_with_levers,
    }

    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        win = out["window"]
        label = f"{win['start'] or '09:15'}–{win['end'] or '15:30'} IST"
        if win["side"]:
            label += f" {win['side']}"
        print(f"=== Sep 2 replay comparison ({label}) ===")
        print(f"Tape status OFF: {off_sum.status} | ON: {on_sum.status}")
        print(
            f"Levers OFF: {off_sum.trade_count} trades net ₹{off_sum.net_pnl_inr:,.0f} "
            f"({off_sum.wins}W/{off_sum.losses}L)"
        )
        print(
            f"Levers ON:  {on_sum.trade_count} trades net ₹{on_sum.net_pnl_inr:,.0f} "
            f"({on_sum.wins}W/{on_sum.losses}L)"
        )
        print(
            f"Delta: +{out['delta']['tradeCount']} trades, "
            f"₹{out['delta']['netPnlInr']:+,.0f} PnL vs OFF"
        )
        print(f"Live actual today: 2 trades net ₹-15,042")
        if new_with_levers:
            print("\nTrades unlocked by levers:")
            for t in new_with_levers:
                print(
                    f"  {t.get('entryAt')} {t.get('symbol')} {t.get('side')} "
                    f"{t.get('strike')} ₹{float(t.get('pnlInr') or 0):,.0f} "
                    f"exit={t.get('exitReason')}"
                )
        print("\nTop gates (OFF):", off_sum.top_gates[:5])
        print("Top gates (ON): ", on_sum.top_gates[:5])

    return 0 if off_sum.status == "ok" and on_sum.status == "ok" else 1


if __name__ == "__main__":
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    raise SystemExit(main())
