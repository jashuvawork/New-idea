#!/usr/bin/env python3
"""
Side-by-side paper parity monitor — local paper (prod snapshot feed) vs production.

Reads production deployment + market snapshots (read-only), optionally runs one
paper-lab auto_trader cycle locally on the same snapshot payload, and logs base /
funnel-relevant fields for session review.

Usage (from backend/):
  .venv/bin/python scripts/paper_prod_parity_monitor.py
  .venv/bin/python scripts/paper_prod_parity_monitor.py --run-local-cycle
  PROD_API_BASE=http://65.0.136.146:8000 .venv/bin/python scripts/paper_prod_parity_monitor.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

IST = ZoneInfo("Asia/Kolkata")
ARTIFACT_DIR = Path(os.environ.get("PAPER_PARITY_ARTIFACT_DIR", "/opt/cursor/artifacts/paper-parity"))
DEFAULT_PROD_BASES = (
    os.environ.get("PROD_API_BASE", "").strip(),
    "http://65.0.136.146:8000",
    "https://api.jashuvatrade.xyz",
)


def _now_ist() -> str:
    return datetime.now(IST).isoformat()


async def _fetch_json(client: httpx.AsyncClient, path: str) -> tuple[int, Any]:
    try:
        r = await client.get(path)
        if r.status_code != 200:
            return r.status_code, {"error": r.text[:500]}
        return r.status_code, r.json()
    except Exception as exc:
        return 0, {"error": str(exc)}


def _summarize_alerts(snapshots: dict[str, Any], *, max_rows: int = 12) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sym, snap in sorted(snapshots.items()):
        if not isinstance(snap, dict):
            continue
        for alert in snap.get("explosionAlerts") or []:
            if not isinstance(alert, dict):
                continue
            local = float(
                alert.get("localBaseMovePct")
                or alert.get("ictBaseRelativeMovePct")
                or alert.get("offLowMovePct")
                or 0
            )
            rows.append(
                {
                    "symbol": sym,
                    "side": alert.get("side"),
                    "strike": alert.get("strike"),
                    "tier": alert.get("tier"),
                    "score": alert.get("explosionScore") or alert.get("score"),
                    "premium": alert.get("premium"),
                    "localBaseMovePct": round(local, 2),
                    "tradeable": alert.get("tradeable"),
                    "momentType": alert.get("momentType") or alert.get("moment_type"),
                    "newBaseKind": alert.get("newBaseKind"),
                    "effectiveBasePremium": alert.get("effectiveBasePremium"),
                }
            )
    rows.sort(key=lambda r: (-float(r.get("score") or 0), float(r.get("localBaseMovePct") or 999)))
    return rows[:max_rows]


async def build_report(*, prod_base: str, run_local_cycle: bool) -> dict[str, Any]:
    report: dict[str, Any] = {
        "tsIst": _now_ist(),
        "prodApiBase": prod_base,
        "localCycleRan": False,
    }
    verify = False
    async with httpx.AsyncClient(timeout=25.0, verify=verify) as client:
        client.base_url = prod_base.rstrip("/")
        _, health = await _fetch_json(client, "/health")
        _, deploy = await _fetch_json(client, "/api/deployment/status")
        _, snaps = await _fetch_json(client, "/api/market/snapshots")
        _, milestone = await _fetch_json(client, "/api/auto-trader/milestone")

        report["prodHealth"] = {
            "status": health.get("status") if isinstance(health, dict) else None,
            "loopWatchdogAgeMs": health.get("loopWatchdog", {}).get("beatAgeMs")
            if isinstance(health, dict)
            else None,
        }
        if isinstance(deploy, dict):
            flags = deploy.get("flags") or {}
            report["prodDeploy"] = {
                "commit": deploy.get("commit"),
                "executionMode": deploy.get("executionMode") or flags.get("executionMode"),
                "sessionBaseGuards": flags.get("sessionBaseGuards"),
                "openSetupShadow": (flags.get("openSetupPolicy") or {}).get("openSetupShadow"),
            }
        if isinstance(snaps, dict):
            raw = snaps.get("snapshots") or {}
            report["prodSnapshots"] = {
                "dataReady": snaps.get("dataReady"),
                "wsTickAgeMs": snaps.get("wsTickAgeMs"),
                "symbolCount": len(raw),
                "waitingReason": snaps.get("waitingReason"),
            }
            report["topBaseCandidates"] = _summarize_alerts(raw)
        if isinstance(milestone, dict):
            report["prodMilestone"] = {
                "tradeCount": milestone.get("tradeCount"),
                "batchOffset": milestone.get("batchOffset"),
                "netPnlInr": milestone.get("netPnlInr"),
            }

    if run_local_cycle:
        os.environ.setdefault("TRADE_STORE_DIR", "/tmp/nexusquant/paper-parity-trades")
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from app.config import get_settings

        s = get_settings()
        object.__setattr__(s, "paper_trading", True) if hasattr(s, "__dict__") else None
        # Pydantic settings — patch via env for cycle
        os.environ["PAPER_TRADING"] = "true"
        os.environ["ENABLE_LIVE_TRADING"] = "false"
        os.environ["PAPER_LAB_USE_PROD_SNAPSHOTS"] = "true"
        os.environ["PAPER_LAB_PROD_API_BASE"] = prod_base
        os.environ["LAB_SESSION_TAG"] = f"parity-{datetime.now(IST).strftime('%Y%m%d')}"

        from app.config import get_settings as _gs

        if hasattr(_gs, "cache_clear"):
            _gs.cache_clear()
        elif hasattr(__import__("app.config", fromlist=["_cached_get_settings"]), "_cached_get_settings"):
            from app.config import _cached_get_settings

            _cached_get_settings.cache_clear()

        from app.engines.paper_lab_prod_feed import maybe_run_prod_snapshot_cycle

        try:
            ran = await maybe_run_prod_snapshot_cycle()
            report["localCycleRan"] = bool(ran)
        except Exception as exc:
            report["localCycleError"] = str(exc)

        from app.engines.auto_trader import get_state

        state = get_state()
        report["localState"] = {
            "openTrades": len(state.openPaperTrades or []),
            "lastCycleSkipped": (state.dailyReport or {}).get("lastCycleSkipped", [])[-3:]
            if isinstance(state.dailyReport, dict)
            else [],
        }

    return report


async def main() -> int:
    parser = argparse.ArgumentParser(description="Paper vs prod parity monitor")
    parser.add_argument(
        "--run-local-cycle",
        action="store_true",
        help="Run one paper-lab process() cycle on prod snapshots",
    )
    parser.add_argument("--prod-base", default="", help="Override production API base URL")
    parser.add_argument("--print", action="store_true", help="Print JSON to stdout")
    args = parser.parse_args()

    prod_base = (args.prod_base or "").strip()
    if not prod_base:
        for candidate in DEFAULT_PROD_BASES:
            if not candidate:
                continue
            prod_base = candidate
            break

    report = await build_report(prod_base=prod_base, run_local_cycle=args.run_local_cycle)

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.now(IST).strftime("%Y-%m-%d")
    out = ARTIFACT_DIR / f"parity-{day}.jsonl"
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, default=str) + "\n")

    if args.print:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(
            f"parity logged → {out} | prod={report.get('prodDeploy', {}).get('commit', '?')} "
            f"dataReady={report.get('prodSnapshots', {}).get('dataReady')} "
            f"localCycle={report.get('localCycleRan')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))