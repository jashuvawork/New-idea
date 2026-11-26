#!/usr/bin/env python3
"""Production read-only session monitor — exits, entry quality, gates, bases, newSessionBase.

Writes JSON lines under /opt/cursor/artifacts/session-monitor/YYYY-MM-DD.jsonl
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
ARTIFACT_DIR = Path(
    os.environ.get("SESSION_MONITOR_ARTIFACT_DIR", "/opt/cursor/artifacts/session-monitor")
)
DEFAULT_PROD_BASES = (
    os.environ.get("PROD_API_BASE", "").strip(),
    "http://65.0.136.146:8000",
    "https://api.jashuvatrade.xyz",
)

# Recent gate PRs we expect on main (HUD / funnel reason keywords)
RECENT_GATE_MARKERS = {
    "disable_session_trough": "newSessionBaseSessionTroughStampEnabled",
    "index_extreme_launch": "indexExtremeLaunch",
    "rip_fall_block": "explosionSessionRipFallBlockEnabled",
    "exec_premium_fade": "exec_premium_fading",
    "fake_trap": "fake_explosion_trap",
    "post_win_fresh": "post_win_fresh",
    "local_pullback_stale": "stale_trough",
}


def _today_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


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


def _exit_capture_review(trade: dict[str, Any]) -> dict[str, Any]:
    ec = trade.get("entryContext") if isinstance(trade.get("entryContext"), dict) else {}
    entry = float(trade.get("entryPremium") or ec.get("entryPremium") or 0)
    exit_p = float(trade.get("exitPremium") or trade.get("closePremium") or 0)
    peak = float(
        trade.get("peakPremium")
        or ec.get("peakPremium")
        or ec.get("sessionPeakPremium")
        or 0
    )
    pnl = float(trade.get("realizedPnlInr") or trade.get("pnlInr") or 0)
    reason = str(trade.get("exitReason") or "")
    mfe_inr = None
    lots = float(trade.get("lots") or trade.get("quantity") or 1)
    unit = float(trade.get("lotSize") or trade.get("unitsPerLot") or 0)
    if peak > entry > 0 and unit > 0:
        mfe_inr = (peak - entry) * lots * unit
    capture_pct = None
    if peak > entry > 0 and exit_p > 0:
        capture_pct = round((exit_p - entry) / (peak - entry) * 100, 1)
    post_exit = trade.get("postExitMonitor") or ec.get("postExitMonitor") or {}
    post_peak = float(post_exit.get("postExitPeakLtp") or post_exit.get("peakLtp") or 0)
    left_on_table_pct = None
    if post_peak > exit_p > 0:
        left_on_table_pct = round((post_peak - exit_p) / post_peak * 100, 1)
    grade = "ok"
    if pnl > 0 and capture_pct is not None and capture_pct < 35:
        grade = "early_exit_review"
    if pnl > 0 and left_on_table_pct is not None and left_on_table_pct > 25:
        grade = "left_runner_on_table"
    if pnl < -3000 and "session_rip_fall" in reason.lower():
        grade = "rip_fall_loss_expected_block"
    return {
        "leg": f"{trade.get('symbol')} {trade.get('side')} {trade.get('strike')}",
        "pnlInr": pnl,
        "exitReason": reason,
        "capturePctOfPeakMove": capture_pct,
        "mfeInrEst": mfe_inr,
        "postExitPeakLtp": post_peak or None,
        "leftOnTablePct": left_on_table_pct,
        "grade": grade,
        "momentType": ec.get("momentType"),
    }


def _entry_quality(trade: dict[str, Any], *, is_open: bool = False) -> dict[str, Any]:
    ec = trade.get("entryContext") if isinstance(trade.get("entryContext"), dict) else {}
    local = float(
        ec.get("localBaseMovePct")
        or ec.get("ictBaseRelativeMovePct")
        or ec.get("offBasePct")
        or 0
    )
    fall_peak = ec.get("fallFromPeakPct")
    if fall_peak is None and isinstance(ec.get("sessionRipFall"), dict):
        fall_peak = ec["sessionRipFall"].get("fallFromPeakPct")
    nsb = bool(ec.get("newSessionBase"))
    kind = ec.get("newBaseKind")
    fake = bool(ec.get("fakeExplosionTrap"))
    flags: list[str] = []
    verdict = "acceptable"
    if nsb and kind == "session_trough" and fall_peak is not None and float(fall_peak) < 8:
        verdict = "bad_fake_trough"
        flags.append("nsb_trough_near_peak")
    if local > 28:
        verdict = "chase_elevated"
        flags.append("pad_chase")
    if fake and not ec.get("ictArmedBaseLaunch"):
        flags.append("fake_trap_latched")
    if local <= 18 and ec.get("ictBaseArmed"):
        flags.append("armed_near_base")
    if is_open and local > 22:
        verdict = "open_monitor_chase"
    return {
        "verdict": verdict,
        "flags": flags,
        "localBaseMovePct": round(local, 2) if local else None,
        "newSessionBase": nsb,
        "newBaseKind": kind,
        "fallFromPeakPct": fall_peak,
        "freshNearBaseReason": ec.get("freshNearBaseReason"),
        "rankScore": ec.get("rankScore") or ec.get("causalRankScore"),
    }


def _pillar_gates(deploy: dict[str, Any], funnel: Any, flags: dict[str, Any]) -> dict[str, Any]:
    session_base = flags.get("sessionBaseGuards") or deploy.get("sessionBaseGuards") or {}
    checks: dict[str, Any] = {"sessionBaseGuards": session_base, "markersFound": {}}
    blob = json.dumps({**deploy, **flags, "funnel": funnel}, default=str).lower()
    for name, needle in RECENT_GATE_MARKERS.items():
        checks["markersFound"][name] = needle.lower() in blob
    trough = session_base.get("newSessionBaseSessionTroughStampEnabled")
    checks["expectTroughOff"] = trough is False
    checks["troughStampEnabled"] = trough
    checks["ripFallBlockEnabled"] = session_base.get("explosionSessionRipFallBlockEnabled")
    blocker_sample: list[str] = []
    if isinstance(funnel, dict):
        for key in ("topBlockers", "blockerCounts", "recentGated"):
            chunk = funnel.get(key)
            if isinstance(chunk, list):
                for row in chunk[:12]:
                    if isinstance(row, dict):
                        blocker_sample.append(str(row.get("reason") or row.get("name") or row))
                    else:
                        blocker_sample.append(str(row))
    checks["funnelBlockerSample"] = blocker_sample[:10]
    return checks


def _pillar_bases(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    stamped = [a for a in alerts if a.get("newSessionBase") or a.get("newBaseKind")]
    near = [a for a in alerts if float(a.get("localBaseMovePct") or 99) <= 18]
    return {
        "stampedCount": len(stamped),
        "stampedLegs": [
            {
                "key": f"{a.get('symbol')}:{a.get('side')}:{a.get('strike')}",
                "kind": a.get("newBaseKind"),
                "padPct": a.get("localBaseMovePct"),
                "effectiveBasePremium": a.get("effectiveBasePremium"),
            }
            for a in stamped[:8]
        ],
        "nearBaseCandidates": len(near),
        "tradeableNearBase": sum(1 for a in near if a.get("tradeable")),
    }


def _pillar_nsb_policy(session_base: dict[str, Any]) -> dict[str, Any]:
    enabled = bool(session_base.get("newSessionBaseIdentifyEnabled"))
    trough = bool(session_base.get("newSessionBaseSessionTroughStampEnabled"))
    recommendation = (
        "keep_identify_off_until_post_rip_window_fixed"
        if trough or not session_base
        else "trough_off_ok_post_rip_only_do_not_waive_until_window_base_confirms"
    )
    if not enabled:
        recommendation = "identify_disabled_safe"
    return {
        "identifyEnabled": enabled,
        "troughStampEnabled": trough,
        "minFallFromPeakPct": session_base.get("newSessionBaseTroughMinFallFromPeakPct"),
        "recommendation": recommendation,
        "replayNote": "Tape replay Nov26: post_rip failed afternoon floor; trough caused lunch chase stamps.",
    }


async def build_report(*, prod_base: str) -> dict[str, Any]:
    today = _today_ist()
    report: dict[str, Any] = {"tsIst": _now_ist(), "dateIst": today, "prodApiBase": prod_base}
    verify = False
    async with httpx.AsyncClient(timeout=30.0, verify=verify) as client:
        client.base_url = prod_base.rstrip("/")
        _, health = await _fetch_json(client, "/health")
        _, deploy = await _fetch_json(client, "/api/deployment/status")
        _, status = await _fetch_json(client, "/api/auto-trader/status")
        _, hist = await _fetch_json(client, f"/api/auto-trader/history/{today}")
        _, funnel = await _fetch_json(client, f"/api/ai/radar-funnel/{today}")
        _, missed = await _fetch_json(client, "/api/ai/missed-trades")
        _, snaps = await _fetch_json(client, "/api/market/snapshots")

        report["healthOk"] = isinstance(health, dict) and health.get("status") == "ok"
        flags: dict[str, Any] = {}
        session_base: dict[str, Any] = {}
        if isinstance(deploy, dict):
            flags = deploy.get("flags") or {}
            session_base = flags.get("sessionBaseGuards") or {}
            report["deploy"] = {
                "commit": deploy.get("commit"),
                "executionMode": deploy.get("executionMode") or flags.get("executionMode"),
                "liveTradingEnabled": flags.get("enableLiveTrading"),
            }
        report["pillar1_exits"] = {"closedToday": [], "openToday": []}
        trades = []
        if isinstance(hist, dict):
            trades = hist.get("trades") or hist.get("closedTrades") or []
        for t in trades if isinstance(trades, list) else []:
            if not isinstance(t, dict):
                continue
            opened = str(t.get("openedAt") or t.get("entryTime") or "")
            if today not in opened and not opened:
                continue
            row_exit = _exit_capture_review(t)
            row_entry = _entry_quality(t, is_open=t.get("status") != "CLOSED")
            bundle = {**row_exit, "entryQuality": row_entry}
            if str(t.get("status", "CLOSED")).upper() == "CLOSED":
                report["pillar1_exits"]["closedToday"].append(bundle)
            else:
                report["pillar1_exits"]["openToday"].append(bundle)
        report["pillar2_entryQuality"] = {
            "losses": [x for x in report["pillar1_exits"]["closedToday"] if float(x.get("pnlInr") or 0) < -500],
            "opensUnderWatch": report["pillar1_exits"]["openToday"],
        }
        report["pillar3_gates"] = _pillar_gates(
            deploy if isinstance(deploy, dict) else {},
            funnel,
            flags,
        )
        alerts: list[dict[str, Any]] = []
        if isinstance(snaps, dict):
            for sym, snap in (snaps.get("snapshots") or {}).items():
                if not isinstance(snap, dict):
                    continue
                for alert in snap.get("explosionAlerts") or []:
                    if isinstance(alert, dict):
                        alerts.append({**alert, "symbol": sym})
        report["pillar4_bases"] = _pillar_bases(alerts)
        report["pillar5_newSessionBase"] = _pillar_nsb_policy(session_base)
        if isinstance(missed, dict):
            report["missedTradesTop"] = (missed.get("top") or missed.get("missed") or [])[:5]
        if isinstance(status, dict):
            report["autoTrader"] = {
                "running": status.get("running"),
                "openCount": len(status.get("openPaperTrades") or status.get("openTrades") or []),
                "dailyReportPnl": (status.get("dailyReport") or {}).get("netPnlInr"),
            }
    return report


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prod-base", default="")
    parser.add_argument("--print", action="store_true")
    args = parser.parse_args()
    prod_base = (args.prod_base or "").strip()
    if not prod_base:
        for candidate in DEFAULT_PROD_BASES:
            if candidate:
                prod_base = candidate
                break
    report = await build_report(prod_base=prod_base)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    day = report.get("dateIst") or _today_ist()
    out = ARTIFACT_DIR / f"{day}.jsonl"
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, default=str) + "\n")
    summary_path = ARTIFACT_DIR / f"{day}-latest.json"
    summary_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    if args.print:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"session monitor → {out} | exits={len(report.get('pillar1_exits',{}).get('closedToday',[]))} open={len(report.get('pillar1_exits',{}).get('openToday',[]))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))