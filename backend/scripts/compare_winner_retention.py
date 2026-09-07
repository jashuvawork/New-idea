#!/usr/bin/env python3
"""Compare EOD replay profiles (PR571, quality gates, Profile A/B, ExitOnly)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.engines.eod_local_base_replay import replay_local_base_day
from app.models.schemas import AutoTraderState

ARCHIVE = "/tmp/eod_audit_archives"
DATES = [
    "2026-08-19", "2026-08-20", "2026-08-21", "2026-08-24", "2026-08-25",
    "2026-08-26", "2026-08-27", "2026-08-28", "2026-08-31", "2026-09-01",
    "2026-09-02", "2026-09-03", "2026-09-04",
]
PROFILES = {
    "PR571": {
        "eod_replay_persist_weekly_elite_budget": False,
        "eod_replay_daily_max_trades": 0,
        "eod_replay_block_legacy_bypass_below_min_score": False,
        "eod_replay_min_elite_score_for_pad": 0,
        "eod_replay_pad_max_off_base_pct": 999,
    },
    "QualityGates572": {
        "eod_replay_persist_weekly_elite_budget": True,
        "eod_replay_daily_max_trades": 2,
        "eod_replay_block_legacy_bypass_below_min_score": True,
        "eod_replay_min_elite_score_for_pad": 90,
        "eod_replay_pad_max_off_base_pct": 22,
    },
    "ExitOnlyDefaults": {
        "eod_replay_persist_weekly_elite_budget": False,
        "eod_replay_daily_max_trades": 0,
        "eod_replay_block_legacy_bypass_below_min_score": False,
        "eod_replay_min_elite_score_for_pad": 0,
        "eod_replay_pad_max_off_base_pct": 999,
    },
    "ProfileA": {
        "eod_replay_persist_weekly_elite_budget": True,
        "eod_replay_daily_max_trades": 0,
        "eod_replay_block_legacy_bypass_below_min_score": False,
        "eod_replay_min_elite_score_for_pad": 0,
        "eod_replay_pad_max_off_base_pct": 25.0,
    },
    "ProfileB": {
        "eod_replay_persist_weekly_elite_budget": True,
        "eod_replay_daily_max_trades": 3,
        "eod_replay_block_legacy_bypass_below_min_score": False,
        "eod_replay_min_elite_score_for_pad": 85,
        "eod_replay_pad_max_off_base_pct": 25.0,
    },
}


def base_settings() -> Settings:
    s = Settings()
    s.radar_archive_dir = ARCHIVE
    s.trade_store_dir = f"{ARCHIVE}/trades"
    s.eod_replay_live_session_gates_enabled = True
    s.session_loss_pause_enabled = True
    s.chop_day_guards_enabled = True
    s.building_ltp_monitor_enabled = True
    return s


def run_profile(name: str, overrides: dict) -> dict:
    s = base_settings()
    for k, v in overrides.items():
        setattr(s, k, v)
    state = (
        AutoTraderState()
        if overrides.get("eod_replay_persist_weekly_elite_budget")
        else None
    )
    trades: list[dict] = []
    daily: list[dict] = []
    for date in DATES:
        report = replay_local_base_day(date, settings=s, replay_state=state)
        day_trades = list(report.get("trades") or [])
        daily.append({
            "date": date,
            "tradeCount": len(day_trades),
            "netPnlInr": round(float(report.get("netPnlInr") or 0)),
        })
        for row in day_trades:
            t = dict(row)
            t["_date"] = date
            trades.append(t)
    wins = [t for t in trades if float(t.get("pnlInr") or 0) > 0]
    return {
        "name": name,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(trades) - len(wins),
        "netPnlInr": round(sum(float(t.get("pnlInr") or 0) for t in trades)),
        "winRatePct": round(100 * len(wins) / len(trades), 1) if trades else 0,
        "daily": daily,
    }


def main() -> int:
    args = sys.argv[1:]
    if not args:
        profiles = {"ExitOnlyDefaults": PROFILES["ExitOnlyDefaults"]}
    else:
        profiles = {name: PROFILES[name] for name in args if name in PROFILES}
        if not profiles:
            print(f"Unknown profiles: {args}. Available: {', '.join(PROFILES)}", file=sys.stderr)
            return 1

    out = {name: run_profile(name, cfg) for name, cfg in profiles.items()}
    path = Path("/opt/cursor/artifacts/profile_a_b_eod.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    print(f"\nSaved: {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
