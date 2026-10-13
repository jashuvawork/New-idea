#!/usr/bin/env python3
"""Replay every archived session through the live explosion book (current vs before Oct 13).

Usage (from backend/):
    PYTHONPATH=. .venv/bin/python scripts/replay_current_book_all_sessions.py \
        --archives /tmp/hist/zips --out /opt/cursor/artifacts/current_book_all_sessions

Archives are production radar ZIPs (``/api/ai/radar-archives/{date}``). Settings are
``Settings()`` + ``deploy/env.october-frozen.overlay`` + ``deploy/env.paper-150k.overlay``
with ``eod_replay_live_explosion_book_enabled`` on. The "before_oct13" profile reverts the
Oct 13 overlay flags. Each session is scored against the archive scorecard's real moves
(policy-eligible base→peak events).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OVERLAYS = [
    REPO / "deploy" / "env.october-frozen.overlay",
    REPO / "deploy" / "env.paper-150k.overlay",
]
OCT13_FLAGS_OFF = {
    "SELECTOR_BEST_ONLY_DUAL_SIDE_ENABLED": "false",
    "CAPITAL_COMMIT_AT_ENTRY_COST_ENABLED": "false",
    "OPEN_SIDE_CONFIRMATION_ENABLED": "false",
    "EXPLOSION_COOLDOWN_PER_SIDE_ENABLED": "false",
    "NEVER_GREEN_HARD_STOP_ENABLED": "false",
    "CATASTROPHIC_LOSS_STOP_PCT": "0",
    "BREAKEVEN_SHAKEOUT_HOLD_ENABLED": "false",
    "DEEP_ITM_RUNNER_PULLBACK_HOLD_ENABLED": "false",
    "SMART_ICHIMOKU_INDEX_RALLY_BYPASS_ENABLED": "false",
}
BIG_MOVE_PCT = 150.0


def _overlay_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for path in OVERLAYS:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _settings(profile: str, archives: Path, store: Path):
    env = _overlay_env()
    if profile == "before_oct13":
        env.update(OCT13_FLAGS_OFF)
    elif profile.startswith("current-"):
        flag = profile.removeprefix("current-")
        env[flag] = OCT13_FLAGS_OFF[flag]
    elif profile.startswith("current@"):
        for pair in profile.removeprefix("current@").split("+"):
            key, _, value = pair.partition("=")
            env[key] = value
    env["EOD_REPLAY_LIVE_EXPLOSION_BOOK_ENABLED"] = "true"
    env["RADAR_ARCHIVE_DIR"] = str(archives)
    env["TRADE_STORE_DIR"] = str(store / profile)
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        from app.config import Settings

        return Settings()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _truth_moves(zip_path: Path) -> list[dict[str, Any]]:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            card = json.loads(zf.read("scorecard.json"))
    except Exception:
        return []
    out = []
    for ev in card.get("events") or []:
        if not ev.get("policyEligible"):
            continue
        sym, side, strike = str(ev.get("key") or "::").split(":")[:3]
        out.append({
            "key": ev.get("key"),
            "symbol": sym,
            "side": side,
            "strike": float(strike or 0),
            "basePremium": ev.get("basePremium"),
            "peakPremium": ev.get("peakPremium"),
            "peakMovePct": float(ev.get("peakMovePct") or 0),
            "verticalAt": ev.get("verticalAt"),
            "baseStartAt": ev.get("baseStartAt"),
        })
    return out


def _hhmm(iso: Any) -> str:
    try:
        return datetime.fromisoformat(str(iso)).strftime("%H:%M:%S")
    except Exception:
        return ""


def _captured(move: dict[str, Any], trades: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A trade on the same index + side that was open during the move's vertical leg."""
    vt = _hhmm(move.get("verticalAt"))
    best = None
    for t in trades:
        if t.get("symbol") != move["symbol"] or t.get("side") != move["side"]:
            continue
        if not vt or not (str(t.get("entryAt")) <= vt <= str(t.get("exitAt")) or
                          abs(_secs(t.get("entryAt")) - _secs(vt)) <= 600):
            continue
        if best is None or float(t.get("pnlInr") or 0) > float(best.get("pnlInr") or 0):
            best = t
    return best


def _secs(hhmmss: Any) -> int:
    try:
        h, m, s = str(hhmmss).split(":")
        return int(h) * 3600 + int(m) * 60 + int(float(s))
    except Exception:
        return 0


def _day(date: str, profile: str, archives: Path, store: Path) -> dict[str, Any]:
    from app.engines.eod_local_base_replay import replay_local_base_day

    s = _settings(profile, archives, store)
    t0 = time.time()
    report = replay_local_base_day(date, settings=s)
    trades = list(report.get("trades") or [])
    for t in trades:
        t.pop("_entryDt", None)
        t.pop("_exitDt", None)
    return {
        "date": date,
        "profile": profile,
        "status": report.get("status"),
        "seconds": round(time.time() - t0, 1),
        "sampleBatches": report.get("sampleBatches"),
        "tradeCount": len(trades),
        "wins": sum(1 for t in trades if float(t.get("pnlInr") or 0) > 0),
        "netPnlInr": round(sum(float(t.get("pnlInr") or 0) for t in trades)),
        "concurrentLegs": sum(1 for t in trades if t.get("concurrentWith")),
        "exitReasons": dict(Counter(str(t.get("exitReason")) for t in trades)),
        "topGates": list(report.get("gateStats", {}).items())[:15],
        "trades": trades,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archives", default="/tmp/hist/zips")
    ap.add_argument("--out", default="/opt/cursor/artifacts/current_book_all_sessions")
    ap.add_argument("--dates", default="")
    ap.add_argument("--profiles", default="current,before_oct13")
    args = ap.parse_args()

    archives = Path(args.archives)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    store = Path("/tmp/nexusquant/replay_store")
    store.mkdir(parents=True, exist_ok=True)

    dates = [d for d in args.dates.split(",") if d] or sorted(
        p.stem.replace("radar-", "") for p in archives.glob("radar-*.zip")
    )
    profiles = [p for p in args.profiles.split(",") if p]
    rows: list[dict[str, Any]] = []
    for date in dates:
        zip_path = archives / f"radar-{date}.zip"
        truth = _truth_moves(zip_path)
        big = sorted(
            (m for m in truth if m["peakMovePct"] >= BIG_MOVE_PCT),
            key=lambda m: -m["peakMovePct"],
        )
        for profile in profiles:
            day = _day(date, profile, archives, store)
            caught = []
            for m in big:
                hit = _captured(m, day["trades"])
                caught.append({
                    "key": m["key"],
                    "peakMovePct": round(m["peakMovePct"], 1),
                    "verticalAt": _hhmm(m["verticalAt"]),
                    "capturedBy": (
                        f"{hit['symbol']}:{hit['side']}:{hit['strike']:g} "
                        f"{hit['entryAt']}→{hit['exitAt']} ₹{hit['pnlInr']:,.0f}"
                        if hit else None
                    ),
                })
            day["bigMoves"] = len(big)
            day["bigMovesBySideIndex"] = dict(Counter(f"{m['symbol']}:{m['side']}" for m in big))
            day["bigMovesCaptured"] = sum(1 for c in caught if c["capturedBy"])
            day["bigMoveDetail"] = caught[:25]
            rows.append(day)
            (out / f"{date}.{profile}.json").write_text(json.dumps(day, indent=2, default=str))
            print(
                f"{date} {profile:13s} {day['status']:8s} trades={day['tradeCount']:2d} "
                f"wins={day['wins']:2d} pnl=₹{day['netPnlInr']:>9,} concurrent={day['concurrentLegs']} "
                f"big={day['bigMoves']} caught={day['bigMovesCaptured']} ({day['seconds']}s)",
                flush=True,
            )

    summary: dict[str, Any] = {"runAt": datetime.now().isoformat(), "profiles": {}}
    for profile in profiles:
        days = [r for r in rows if r["profile"] == profile and r["status"] == "ok"]
        trades = [t for r in days for t in r["trades"]]
        wins = [float(t["pnlInr"]) for t in trades if float(t.get("pnlInr") or 0) > 0]
        losses = [float(t["pnlInr"]) for t in trades if float(t.get("pnlInr") or 0) <= 0]
        by_side = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "wins": 0})
        for t in trades:
            k = f"{t['symbol']}:{t['side']}"
            by_side[k]["trades"] += 1
            by_side[k]["pnl"] += float(t.get("pnlInr") or 0)
            by_side[k]["wins"] += 1 if float(t.get("pnlInr") or 0) > 0 else 0
        equity = peak = max_dd = 0.0
        for r in days:
            equity += r["netPnlInr"]
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
        summary["profiles"][profile] = {
            "sessions": len(days),
            "trades": len(trades),
            "winRatePct": round(100 * len(wins) / len(trades), 1) if trades else 0.0,
            "netPnlInr": round(sum(wins) + sum(losses)),
            "profitFactor": round(sum(wins) / abs(sum(losses)), 2) if losses and sum(losses) else None,
            "avgWinInr": round(sum(wins) / len(wins)) if wins else 0,
            "avgLossInr": round(sum(losses) / len(losses)) if losses else 0,
            "maxDrawdownInr": round(max_dd),
            "greenSessions": sum(1 for r in days if r["netPnlInr"] > 0),
            "redSessions": sum(1 for r in days if r["netPnlInr"] < 0),
            "flatSessions": sum(1 for r in days if r["netPnlInr"] == 0),
            "concurrentLegs": sum(r["concurrentLegs"] for r in days),
            "bigMoves": sum(r["bigMoves"] for r in days),
            "bigMovesCaptured": sum(r["bigMovesCaptured"] for r in days),
            "bySideIndex": {k: {**v, "pnl": round(v["pnl"])} for k, v in sorted(by_side.items())},
            "exitReasons": dict(Counter(str(t.get("exitReason")) for t in trades).most_common()),
        }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
