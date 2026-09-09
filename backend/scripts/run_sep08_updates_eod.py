#!/usr/bin/env python3
"""EOD replay — Sep 07/08 with pre-updates vs structural vs full (velocity exit)."""

from __future__ import annotations

import json
import sys
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.engines.eod_local_base_replay import replay_local_base_day
from app.engines.eod_trade_report import generate_eod_trade_report
from scripts.run_full_eod_audit import PATCH_TARGETS

IST = ZoneInfo("Asia/Kolkata")
ARCHIVE_DIR = Path("/tmp/eod_audit_archives")
OUT = Path("/opt/cursor/artifacts/sep07-08_updates_eod.json")
DATES = ["2026-09-07", "2026-09-08"]

PROFILES: dict[str, dict[str, Any]] = {
    "pre_updates": {
        "eod_replay_structural_gates_enabled": True,
        "peak_velocity_reversal_keep_enabled": False,
        "session_same_strike_loss_reentry_enabled": False,
        "chop_live_block_armed_base_launch": False,
        "fake_explosion_trap_block_chop_elite_armed_base": False,
        "explosion_deep_itm_block_atm_radar_advantage_enabled": False,
    },
    "structural_only": {
        "eod_replay_structural_gates_enabled": True,
        "peak_velocity_reversal_keep_enabled": False,
        "session_same_strike_loss_reentry_enabled": True,
        "chop_live_block_armed_base_launch": True,
        "fake_explosion_trap_block_chop_elite_armed_base": True,
        "explosion_deep_itm_block_atm_radar_advantage_enabled": True,
    },
    "full_new": {
        "eod_replay_structural_gates_enabled": True,
    },
}


def _cfg(profile: str) -> Settings:
    c = Settings()
    c.radar_archive_dir = str(ARCHIVE_DIR)
    c.trade_store_dir = str(ARCHIVE_DIR.parent / "trades")
    c.eod_replay_live_session_gates_enabled = True
    for k, v in PROFILES[profile].items():
        setattr(c, k, v)
    return c


def _with_cfg(cfg: Settings):
    stack = ExitStack()
    for target in PATCH_TARGETS:
        stack.enter_context(patch(target, return_value=cfg))
    return stack


def _summarize(report: dict[str, Any]) -> dict[str, Any]:
    trades = report.get("trades") or []
    wins = sum(1 for t in trades if float(t.get("pnlInr") or 0) > 0)
    losses = sum(1 for t in trades if float(t.get("pnlInr") or 0) < 0)
    net = sum(float(t.get("pnlInr") or 0) for t in trades)
    return {
        "status": report.get("status"),
        "tradeCount": len(trades),
        "wins": wins,
        "losses": losses,
        "netPnlInr": round(net),
        "trades": [
            {
                "strike": t.get("strike"),
                "side": t.get("side"),
                "entryAt": t.get("entryAt"),
                "entryPremium": t.get("entryPremium"),
                "exitAt": t.get("exitAt"),
                "exitPremium": t.get("exitPremium"),
                "pnlInr": round(float(t.get("pnlInr") or 0)),
                "exitReason": t.get("exitReason"),
                "peakPct": t.get("peakPct"),
            }
            for t in trades
        ],
    }


def _live_trades(date: str) -> list[dict[str, Any]]:
    import urllib.request

    url = "https://api.jashuvatrade.xyz/api/auto-trader/history/trades/closed?limit=20"
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.loads(resp.read())
    out = []
    for t in data.get("trades") or []:
        if t.get("sessionDate") != date:
            continue
        out.append(
            {
                "strike": t.get("strike"),
                "side": t.get("side"),
                "lots": t.get("lots"),
                "entryPremium": t.get("entryPremium"),
                "exitPremium": t.get("currentPremium"),
                "pnlInr": round(float(t.get("pnlInr") or 0)),
                "openedAt": (t.get("openedAt") or "")[11:19],
                "closedAt": (t.get("closedAt") or "")[11:19],
                "exitReason": t.get("exitReason"),
            }
        )
    return out


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {
        "runAt": datetime.now(IST).isoformat(),
        "branch": "cursor/peak-velocity-reversal-keep-f5cb",
        "profiles": list(PROFILES.keys()),
        "dates": {},
    }

    for date in DATES:
        print(f"\n=== {date} ===", flush=True)
        day: dict[str, Any] = {"live": _live_trades(date)}
        live_net = sum(t["pnlInr"] for t in day["live"])
        day["liveNetPnlInr"] = live_net
        print(f"  LIVE: {len(day['live'])} trades net ₹{live_net:,.0f}", flush=True)

        try:
            with _with_cfg(_cfg("full_new")):
                legacy = generate_eod_trade_report(date)
            day["legacyEodReport"] = {
                "tradeCount": legacy.get("tradeCount"),
                "netPnlInr": legacy.get("netPnlInr"),
            }
        except Exception as exc:
            day["legacyEodReport"] = {"error": str(exc)}

        for profile in PROFILES:
            cfg = _cfg(profile)
            with _with_cfg(cfg):
                report = replay_local_base_day(date, settings=cfg)
            summary = _summarize(report)
            day[profile] = summary
            print(
                f"  {profile:16} {summary['tradeCount']}t "
                f"{summary['wins']}W/{summary['losses']}L "
                f"₹{summary['netPnlInr']:,.0f}",
                flush=True,
            )
            for t in summary["trades"]:
                print(
                    f"    {t['entryAt']} {int(t['strike'])} {t['side']} "
                    f"₹{t['entryPremium']}→₹{t['exitPremium']} "
                    f"₹{t['pnlInr']:,.0f} {t['exitReason']}",
                    flush=True,
                )

        pre = day["pre_updates"]["netPnlInr"]
        full = day["full_new"]["netPnlInr"]
        day["deltaFullVsPre"] = full - pre
        day["deltaFullVsLive"] = full - live_net
        results["dates"][date] = day

    results["rollup"] = {
        profile: {
            "netPnlInr": sum(
                results["dates"][d][profile]["netPnlInr"] for d in DATES
            ),
            "trades": sum(
                results["dates"][d][profile]["tradeCount"] for d in DATES
            ),
        }
        for profile in PROFILES
    }
    results["rollup"]["liveNetPnlInr"] = sum(
        results["dates"][d]["liveNetPnlInr"] for d in DATES
    )

    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
