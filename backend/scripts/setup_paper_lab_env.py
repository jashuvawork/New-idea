#!/usr/bin/env python3
"""Create backend/.env for local paper lab aligned with EC2 live (read-only prod pull)."""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
TRADE_DIR = Path("/tmp/nexusquant/paper-lab/trades")

PAPER_CORE = """
# --- Paper lab (local) — do not enable live here ---
ENABLE_LIVE_TRADING=false
PAPER_TRADING=true
AUTO_TRADING_ENABLED=true
SHADOW_TRADE_ALL_SIGNALS=true
PAPER_SIMULATE_BROKER_ORDERS=true
LIVE_MATCH_PAPER_BOOK=true
PAPER_LIVE_PARITY_ENABLED=true
PAPER_SLIPPAGE_ENABLED=true

FALLBACK_CAPITAL_INR=30000
MAX_SIZING_CAPITAL_INR=30000
CAPITAL_TIER_ENTRY_SYMBOLS_ENABLED=false
CAPITAL_TIER_NIFTY_OOB_FALLBACK_ENABLED=false
USE_UPSTOX_CAPITAL_FOR_SIZING=false

TRADE_STORE_DIR={trade_dir}
LAB_SESSION_TAG=local-paper-lab

# Same indices as prod
SYMBOLS=NIFTY,SENSEX
""".strip()


def fetch_prod_flags(api_base: str) -> dict:
    url = api_base.rstrip("/") + "/api/deployment/status"
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    return (data.get("flags") or {}), data.get("commit")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--api-base", default="https://api.jashuvatrade.xyz")
    p.add_argument("--capital-inr", type=float, default=30000)
    p.add_argument("--write", action="store_true", help="Write backend/.env")
    args = p.parse_args()

    flags, commit = fetch_prod_flags(args.api_base)
    TRADE_DIR.mkdir(parents=True, exist_ok=True)

    lines = [
        f"# Generated paper lab — prod commit {commit}",
        PAPER_CORE.format(trade_dir=str(TRADE_DIR)),
        f"FALLBACK_CAPITAL_INR={int(args.capital_inr)}",
        f"MAX_SIZING_CAPITAL_INR={int(args.capital_inr)}",
        f"PAPER_LAB_PROD_API_BASE={args.api_base}",
        "PAPER_LAB_USE_PROD_SNAPSHOTS=true",
        "PAPER_LAB_BASE_RIP_ENABLED=true",
        "UNIFIED_PROFIT_LADDER_ENABLED=true",
        "LAB_EXPERIMENT_NOTES=base-to-max-rip-v1",
    ]
    # Mirror a few clock gates from prod HUD (optional)
    ee = flags.get("entryEarliestIst")
    if ee:
        hh, mm = str(ee).split(":")[:2]
        lines.append(f"ENTRY_EARLIEST_HOUR={int(hh)}")
        lines.append(f"ENTRY_EARLIEST_MINUTE={int(mm)}")

    text = "\n".join(lines) + "\n\n# Add Upstox keys below (or OAuth at /api/upstox/login-url)\n"
    text += "UPSTOX_API_KEY=\nUPSTOX_API_SECRET=\nUPSTOX_REDIRECT_URI=http://127.0.0.1:8001/api/upstox/callback\n"

    if args.write:
        ENV_PATH.write_text(text, encoding="utf-8")
        print(f"Wrote {ENV_PATH}")
    else:
        print(text)
    print(f"Trade logs: {TRADE_DIR}")
    print("Next: cd backend && .venv/bin/uvicorn app.main:app --reload --port 8001")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())