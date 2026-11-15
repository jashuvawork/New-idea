#!/usr/bin/env python3
"""During the session: poll EC2 (live) vs local (paper) and append compare JSONL."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
ART = Path("/opt/cursor/artifacts/paper-lab-compare")
ART.mkdir(parents=True, exist_ok=True)


def _get(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=25) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        return {"error": str(exc), "url": url}


def _trade_fingerprint(status: dict) -> list[dict]:
    out = []
    for key in ("openPaperTrades", "openTrades"):
        for t in status.get(key) or []:
            out.append(
                {
                    "key": f"{t.get('symbol')}:{t.get('side')}:{t.get('strike')}",
                    "lots": t.get("lots"),
                    "entryPremium": t.get("entryPremium"),
                    "openedAt": t.get("openedAt"),
                }
            )
    closed = status.get("closedPaperTrades") or status.get("closedTrades") or []
    for t in closed[-5:]:
        out.append(
            {
                "closed": True,
                "key": f"{t.get('symbol')}:{t.get('side')}:{t.get('strike')}",
                "pnlInr": t.get("pnlInr"),
                "exitReason": t.get("exitReason"),
            }
        )
    return out


def snapshot_side(base: str, label: str) -> dict:
    base = base.rstrip("/")
    exec_st = _get(f"{base}/api/execution/status")
    at = _get(f"{base}/api/auto-trader/status")
    deploy = _get(f"{base}/api/deployment/status")
    flags = deploy.get("flags") if isinstance(deploy, dict) else {}
    return {
        "label": label,
        "base": base,
        "executionMode": exec_st.get("executionMode"),
        "live": exec_st.get("liveTradingEnabled"),
        "paper": exec_st.get("paperTrading"),
        "commit": deploy.get("commit"),
        "capital": (flags or {}).get("fallbackCapitalInr"),
        "skippedN": len(at.get("skipped") or []),
        "skippedTop": (at.get("skipped") or [])[:8],
        "dailyPnl": (at.get("dailyReport") or {}).get("netPnlInr"),
        "trades": _trade_fingerprint(at),
        "error": exec_st.get("error") or at.get("error"),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--prod", default="https://api.jashuvatrade.xyz")
    p.add_argument("--local", default="http://127.0.0.1:8001")
    p.add_argument("--interval", type=float, default=60.0)
    p.add_argument("--once", action="store_true")
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    day = datetime.now(IST).strftime("%Y-%m-%d")
    out = args.out or ART / f"compare-{day}.jsonl"

    while True:
        row = {
            "ts": datetime.now(IST).isoformat(),
            "prod": snapshot_side(args.prod, "ec2-live"),
            "local": snapshot_side(args.local, "local-paper"),
        }
        with out.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(row, default=str) + "\n")
        print(
            row["ts"][11:19],
            "prod",
            row["prod"].get("executionMode"),
            "pnl",
            row["prod"].get("dailyPnl"),
            "| local",
            row["local"].get("executionMode"),
            "pnl",
            row["local"].get("dailyPnl"),
            "skipped",
            row["local"].get("skippedN"),
        )
        if args.once:
            break
        time.sleep(max(5.0, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())