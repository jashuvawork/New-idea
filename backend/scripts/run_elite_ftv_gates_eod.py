#!/usr/bin/env python3
"""Before/after EOD P&L — win-rate gates vs win-rate + historical FTV gates."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings
from scripts.run_elite_pnl_comparison_eod import (
    ARCHIVE_DIR,
    CAPITAL_PCT,
    _apply_weekly_cap,
    _load_radars,
    _pnl_summary,
    _row_from_archive,
    dedupe_same_moment_top1,
)

IST = ZoneInfo("Asia/Kolkata")
OUT_PATH = Path("/opt/cursor/artifacts/elite_ftv_gates_eod.json")


def _win_rate_settings() -> Settings:
    return Settings(
        elite_trade_engine_enabled=True,
        elite_trade_v_rip_only_enabled=False,
        elite_trade_block_fvq_above=0.0,
        elite_trade_shallow_lift_block_enabled=False,
        elite_trade_min_milestone_depth=0,
        max_sizing_capital_inr=200_000.0,
        fallback_capital_inr=200_000.0,
        per_trade_capital_pct=CAPITAL_PCT,
        use_upstox_capital_for_sizing=False,
    )


def _ftv_gates_settings() -> Settings:
    return Settings(
        elite_trade_engine_enabled=True,
        elite_trade_v_rip_only_enabled=True,
        elite_trade_block_fvq_above=80.0,
        elite_trade_shallow_lift_block_enabled=True,
        elite_trade_shallow_lift_max_local_pct=10.0,
        elite_trade_shallow_lift_min_stage="TRIGGERED",
        elite_trade_min_milestone_depth=2,
        max_sizing_capital_inr=200_000.0,
        fallback_capital_inr=200_000.0,
        per_trade_capital_pct=CAPITAL_PCT,
        use_upstox_capital_for_sizing=False,
    )


def _rows_for_settings(settings: Settings) -> list[dict[str, Any]]:
    legacy = Settings(elite_trade_engine_enabled=False)
    rows: list[dict[str, Any]] = []
    for date in sorted(
        p.stem.replace("radar-", "")
        for p in ARCHIVE_DIR.glob("radar-*.zip")
        if p.stat().st_size > 5000
    ):
        for row in _load_radars(date):
            rec = _row_from_archive(date, row, settings, legacy_settings=legacy)
            if rec and rec.get("eliteEnginePass"):
                rows.append(rec)
    return dedupe_same_moment_top1(rows)


def main() -> int:
    from app.engines.capital_allocator import set_manual_capital_limit

    win_settings = _win_rate_settings()
    ftv_settings = _ftv_gates_settings()
    set_manual_capital_limit(float(win_settings.max_sizing_capital_inr))

    win_rows = _rows_for_settings(win_settings)
    ftv_rows = _rows_for_settings(ftv_settings)
    win_capped = _apply_weekly_cap([{**r, "userPass": True} for r in win_rows], 8)
    ftv_capped = _apply_weekly_cap([{**r, "userPass": True} for r in ftv_rows], 8)

    comparison = {
        "winRateGatesOnly": _pnl_summary(win_capped, win_settings, "win_rate_gates_only"),
        "winRatePlusFtvGates": _pnl_summary(ftv_capped, ftv_settings, "win_rate_plus_ftv_gates"),
        "winRateGatesOnlyUncapped": _pnl_summary(win_rows, win_settings, "win_rate_gates_only_uncapped"),
        "winRatePlusFtvGatesUncapped": _pnl_summary(ftv_rows, ftv_settings, "win_rate_plus_ftv_gates_uncapped"),
    }

    dates = sorted(
        p.stem.replace("radar-", "")
        for p in ARCHIVE_DIR.glob("radar-*.zip")
        if p.stat().st_size > 5000
    )

    out = {
        "runAt": datetime.now(IST).isoformat(),
        "dates": dates,
        "assumptions": {
            "capitalInr": win_settings.max_sizing_capital_inr,
            "capitalPctPerTrade": CAPITAL_PCT,
            "weeklyCap": 8,
            "method": "eliteEnginePass via _row_from_archive + 8/week cap",
        },
        "comparison": comparison,
        "deltaUncapped": {
            "trades": comparison["winRatePlusFtvGatesUncapped"]["trades"]
            - comparison["winRateGatesOnlyUncapped"]["trades"],
            "totalPnlInr": round(
                comparison["winRatePlusFtvGatesUncapped"]["totalPnlInr"]
                - comparison["winRateGatesOnlyUncapped"]["totalPnlInr"],
                0,
            ),
            "winRatePct": round(
                comparison["winRatePlusFtvGatesUncapped"]["winRatePct"]
                - comparison["winRateGatesOnlyUncapped"]["winRatePct"],
                1,
            ),
        },
        "deltaWeeklyCap8": {
            "trades": comparison["winRatePlusFtvGates"]["trades"] - comparison["winRateGatesOnly"]["trades"],
            "totalPnlInr": round(
                comparison["winRatePlusFtvGates"]["totalPnlInr"]
                - comparison["winRateGatesOnly"]["totalPnlInr"],
                0,
            ),
            "winRatePct": round(
                comparison["winRatePlusFtvGates"]["winRatePct"]
                - comparison["winRateGatesOnly"]["winRatePct"],
                1,
            ),
        },
        "historicalReference": {
            "baselineWinGates": {
                "trades": 26,
                "winRatePct": 76.9,
                "totalPnlInr": 513623,
                "source": "elite_win_rate_gates_eod.json",
            },
            "vOnlyPolicy": {
                "trades": 25,
                "winRatePct": 80.0,
                "totalPnlInr": 530984,
                "source": "historical_ftv_data_eod_improvements.json",
            },
        },
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, default=str))

    print("=== Win-rate gates vs + FTV gates (8/week cap) ===")
    for row in comparison.values():
        print(
            f"{row['label']}: {row['trades']} trades | "
            f"win {row['winRatePct']}% | P&L ₹{row['totalPnlInr']:,.0f}"
        )
    print(f"Delta P&L: ₹{out['delta']['totalPnlInr']:,.0f}")
    print(f"Full JSON: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
