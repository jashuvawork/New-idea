#!/usr/bin/env python3
"""Run full-day EOD local-base replay for every available radar archive."""

from __future__ import annotations

import json
import sys
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.engines.eod_local_base_replay import generate_eod_local_base_replay

IST = ZoneInfo("Asia/Kolkata")
ARCHIVE_DIR = Path("/tmp/eod_audit_archives")
OUT_PATH = Path("/opt/cursor/artifacts/all_available_eods.json")
BASE_URL = "https://www.jashuvatrade.xyz"

# Weekday sessions Aug 19 – Sep 2 (7-day retention window per AGENTS.md)
CANDIDATE_DATES = [
    "2026-08-19",
    "2026-08-20",
    "2026-08-21",
    "2026-08-24",
    "2026-08-25",
    "2026-08-26",
    "2026-08-27",
    "2026-08-28",
    "2026-08-31",
    "2026-09-01",
    "2026-09-02",
    "2026-09-03",
    "2026-09-04",
]


def _has_premium_tape(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            return "premium_tape.jsonl" in zf.namelist()
    except Exception:
        return False


def _download(date: str) -> Path | None:
    dest = ARCHIVE_DIR / f"radar-{date}.zip"
    if dest.exists() and dest.stat().st_size > 10_000 and _has_premium_tape(dest):
        return dest
    try:
        urllib.request.urlretrieve(f"{BASE_URL}/api/ai/radar-archives/{date}", dest)
        if dest.stat().st_size > 1000 and _has_premium_tape(dest):
            return dest
    except Exception:
        pass
    if dest.exists() and dest.stat().st_size < 1000:
        dest.unlink(missing_ok=True)
    return None


def _discover_local() -> list[str]:
    dates: list[str] = []
    for path in sorted(ARCHIVE_DIR.glob("radar-*.zip")):
        date = path.stem.replace("radar-", "")
        if _has_premium_tape(path):
            dates.append(date)
    return dates


def _current_settings() -> Settings:
    s = Settings()
    s.radar_archive_dir = str(ARCHIVE_DIR)
    s.trade_store_dir = str(ARCHIVE_DIR / "trades")
    s.eod_replay_live_session_gates_enabled = True
    s.session_loss_pause_enabled = True
    s.session_large_loss_pause_bypass_enabled = True
    s.chop_day_guards_enabled = True
    s.top_moments_day_type_grade_policy_enabled = True
    s.top_moments_fast_day_grade_c_enabled = True
    s.top_moments_exploding_elite_grade_b_enabled = True
    s.top_moments_momentum_rally_grade_b_enabled = True
    s.index_rally_side_flip_neutral_macd_mom5_waiver_enabled = True
    s.slow_grind_ftv_enabled = True
    s.slow_grind_sudden_lift_enabled = True
    s.slow_grind_armed_trough_enabled = True
    s.slow_grind_consolidation_base_enabled = True
    s.building_ltp_monitor_enabled = True
    return s


def main() -> int:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    local = set(_discover_local())
    downloaded: list[str] = []
    download_failed: list[str] = []

    print("Ensuring archives...", flush=True)
    for date in CANDIDATE_DATES:
        if date in local:
            continue
        path = _download(date)
        if path is not None:
            downloaded.append(date)
            local.add(date)
        else:
            download_failed.append(date)

    available = sorted(local)
    print(f"Available with premium tape: {available}", flush=True)
    if download_failed:
        print(f"Download failed (prod 502 or missing): {download_failed}", flush=True)

    settings = _current_settings()
    days: list[dict] = []
    for date in available:
        print(f"\n[{date}] full-day EOD replay...", flush=True)
        from app.engines.eod_local_base_replay import replay_local_base_day

        report = replay_local_base_day(date, settings=settings)
        trades = list(report.get("trades") or [])
        gates = dict(report.get("gateStats") or {})
        top_gates = sorted(gates.items(), key=lambda row: -int(row[1]))[:12]
        row = {
            "date": date,
            "status": report.get("status"),
            "tradeCount": int(report.get("tradeCount") or len(trades)),
            "wins": int(report.get("wins") or 0),
            "losses": int(report.get("losses") or 0),
            "netPnlInr": float(report.get("netPnlInr") or 0),
            "winRatePct": round(
                100 * sum(1 for t in trades if float(t.get("pnlInr") or 0) > 0) / len(trades),
                1,
            )
            if trades
            else 0.0,
            "topGates": top_gates,
            "trades": trades,
        }
        days.append(row)
        print(
            f"  {row['status']} | {row['tradeCount']} trades | "
            f"₹{row['netPnlInr']:,.0f} | win {row['winRatePct']}%",
            flush=True,
        )

    ok_days = [d for d in days if d.get("status") == "ok"]
    rollup = {
        "sessions": len(days),
        "okSessions": len(ok_days),
        "trades": sum(int(d.get("tradeCount") or 0) for d in ok_days),
        "wins": sum(int(d.get("wins") or 0) for d in ok_days),
        "netPnlInr": round(sum(float(d.get("netPnlInr") or 0) for d in ok_days)),
    }
    if rollup["trades"]:
        rollup["winRatePct"] = round(100 * rollup["wins"] / rollup["trades"], 1)

    out = {
        "runAt": datetime.now(IST).isoformat(),
        "archiveDir": str(ARCHIVE_DIR),
        "availableDates": available,
        "newlyDownloaded": downloaded,
        "downloadFailed": download_failed,
        "config": "current_production_gates",
        "rollup": rollup,
        "days": days,
    }
    OUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nReport: {OUT_PATH}", flush=True)
    print(json.dumps({"rollup": rollup, "availableDates": available}, indent=2), flush=True)
    return 0 if ok_days else 1


if __name__ == "__main__":
    raise SystemExit(main())
