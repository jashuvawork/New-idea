#!/usr/bin/env python3
"""Replay historical explosion winners against current entry gates.

Uses radar archive alerts when available (accurate). Falls back to trade
entryContext when no archive exists (approximate — missing live ICT stamps).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings, get_settings
from app.engines.missed_trade_explainer import _candidate_from_alert, _gate_checks
from app.engines.pretrade_validator import validate_candidate
from app.engines.trade_ranking import (
    ftv_authorization_policy,
    ftv_policy_settings,
    rank_entry_candidate,
)
from app.models.schemas import AutoTraderState, Breadth, MarketPhase, SpotChart, SymbolSnapshot
from scripts.run_full_eod_audit import _download, _snap

IST = ZoneInfo("Asia/Kolkata")
DEFAULT_API = "https://jashuvatrade.xyz/api/auto-trader/history/trades/closed?limit=200"
ARTIFACT = Path("/opt/cursor/artifacts/winner_gates_check.json")


def fetch_closed_trades(api_url: str) -> list[dict[str, Any]]:
    with urllib.request.urlopen(api_url, timeout=60) as resp:
        data = json.load(resp)
    return data.get("trades") or []


def alert_from_trade(trade: dict[str, Any]) -> dict[str, Any]:
    ctx = trade.get("entryContext") or {}
    pre = ctx.get("pretrade") or {}
    hci = pre.get("highConfidenceExplosion") or {}
    flat = bool(ctx.get("ictFlatThenVertical") or hci.get("ictFlat"))
    active = bool(ctx.get("ictBreakout") or hci.get("ictDisplacement") or flat)
    return {
        "symbol": trade.get("symbol"),
        "side": trade.get("side"),
        "strike": trade.get("strike"),
        "premium": trade.get("entryPremium"),
        "tier": ctx.get("explosionTier") or ctx.get("extremeTier") or "ELITE",
        "explosionScore": ctx.get("explosionScore") or ctx.get("selectionScore"),
        "tradeable": True,
        "velocity3s": ctx.get("velocity3s") or ctx.get("entryVelocity3s") or pre.get("velocity3s"),
        "velocity9s": ctx.get("velocity9s") or 0,
        "dailyMovePct": ctx.get("sessionMovePct") or ctx.get("dailyMovePct") or pre.get("sessionMovePct"),
        "peakMovePct": ctx.get("peakMovePct") or ctx.get("sessionMovePct"),
        "localBaseMovePct": ctx.get("localBaseMovePct") or pre.get("localBaseMovePct"),
        "ictBaseRelativeMovePct": ctx.get("localBaseMovePct") or pre.get("localBaseMovePct"),
        "ictFirstLift": (
            ctx.get("ictFirstLift")
            if ctx.get("ictFirstLift") is not None
            else bool(ctx.get("firstLiftCapture"))
        ),
        "ictFlatThenVertical": flat,
        "ictBreakout": active,
        "ictArmedBaseLaunch": ctx.get("ictArmedBaseLaunch") or ctx.get("armedBaseCapture"),
        "ictBaseArmed": ctx.get("ictBaseArmed"),
        "ictVRipReady": ctx.get("ictVRipReady"),
        "flatVerticalGrade": ctx.get("ictFlatVerticalGrade") or ctx.get("rankGrade"),
        "flatVerticalQuality": ctx.get("ictFlatVerticalQuality"),
        "bullishLocalBaseActive": ctx.get("bullishLocalBaseActive"),
        "volumeAwaken": bool(hci.get("volumeAwakening") or ctx.get("volumeAwaken")),
        "ictVolumeAwakening": bool(hci.get("volumeAwakening")),
        "ictDisplacement": bool(hci.get("ictDisplacement")),
        "indexHelpersConfirm": bool(pre.get("breadthAligned") or ctx.get("indexHelpersConfirm")),
        "indexMomAlign": bool(pre.get("breadthAligned")),
        "optionCvdBuying": ctx.get("optionCvdBuying"),
        "timingAssessment": (
            (ctx.get("timingAssessment") or {}).get("assessment")
            if isinstance(ctx.get("timingAssessment"), dict)
            else ctx.get("timingAssessment")
        ),
    }


def snap_from_trade(trade: dict[str, Any]) -> SymbolSnapshot:
    ctx = trade.get("entryContext") or {}
    pre = ctx.get("pretrade") or {}
    sc_raw = ctx.get("spotChart") or ctx.get("spotChartFull") or {}
    if not isinstance(sc_raw, dict):
        sc_raw = {}
    breadth_raw = ctx.get("breadth") or pre.get("breadth") or {}
    opened = datetime.fromisoformat(str(trade.get("openedAt"))).astimezone(IST)
    side = str(trade.get("side") or "CALL").upper()
    if isinstance(breadth_raw, str):
        bias = breadth_raw
    else:
        bias = str(breadth_raw.get("bias") or ("BULLISH" if side == "CALL" else "BEARISH"))
    chart_dir = str(sc_raw.get("direction") or ("BULLISH" if side == "CALL" else "BEARISH"))
    return SymbolSnapshot(
        symbol=str(trade.get("symbol") or "NIFTY"),
        timestamp=opened,
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=float(ctx.get("spot") or ctx.get("spotAtEntry") or pre.get("atmStrike") or 0),
        atmStrike=float(pre.get("atmStrike") or ctx.get("atmStrike") or trade.get("strike") or 0),
        tradeQualityScore=float(ctx.get("tqs") or 55),
        breadth=Breadth(bias=bias),
        spotChart=SpotChart(
            direction=chart_dir,
            spot=float(sc_raw.get("spot") or ctx.get("spot") or 0),
            momentum5Pct=float(sc_raw.get("momentum5Pct") or 0),
            momentum10Pct=float(sc_raw.get("momentum10Pct") or 0),
            recommendedSide=side,
        ),
    )


def _load_radar_rows(date: str, cache: dict[str, list[dict[str, Any]]]) -> Optional[list[dict[str, Any]]]:
    if date in cache:
        return cache[date]
    try:
        path = _download(date)
        with zipfile.ZipFile(path) as zf:
            rows = json.loads(zf.read("all_radars.json"))
        cache[date] = rows
        return rows
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, zipfile.BadZipFile, KeyError) as exc:
        cache[date] = []
        print(f"  [radar] {date}: unavailable ({exc})", flush=True)
        return None


def _best_radar_row(rows: list[dict[str, Any]], radar_key: str) -> Optional[dict[str, Any]]:
    matches = [r for r in rows if radar_key in str(r.get("key") or "")]
    if not matches:
        return None
    return max(matches, key=lambda r: float((r.get("alert") or {}).get("explosionScore") or 0))


def evaluate_alert(
    *,
    sym: str,
    alert: dict[str, Any],
    snap: SymbolSnapshot,
    trade: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    ctx = trade.get("entryContext") or {}
    pre = ctx.get("pretrade") or {}
    state = AutoTraderState()
    candidate = _candidate_from_alert(sym, snap, alert)
    gate = _gate_checks(sym, snap, alert, state, {sym: snap})
    ok_pre, pre_reason, _ = validate_candidate(candidate, state, snapshots={sym: snap})
    ranking = rank_entry_candidate(candidate)
    ftv = ftv_authorization_policy(
        ranking.get("evidence") or {},
        ranking,
        snapshot_available=True,
        atm_itm_allowed=True,
        **ftv_policy_settings(get_settings()),
    )
    bypasses = [
        k
        for k, v in (
            ("worstDayBypass", pre.get("worstDayBypass")),
            ("eliteNeverBlock", pre.get("eliteNeverBlock")),
            ("highMoverEliteBypass", pre.get("highMoverEliteBypass")),
            ("extremeMoveBypass", pre.get("extremeMoveBypass")),
            ("expiryAlignedBypass", pre.get("expiryAlignedBypass")),
        )
        if v
    ]
    full_pass = bool(ftv.allowed and ok_pre and gate.get("wouldPass"))
    return {
        "date": trade.get("sessionDate"),
        "key": ctx.get("radarKey") or f"{sym}:{trade.get('side')}:{trade.get('strike')}",
        "pnlInr": round(float(trade.get("pnlInr") or 0)),
        "source": source,
        "tier": alert.get("tier"),
        "score": alert.get("explosionScore"),
        "v3": alert.get("velocity3s"),
        "grade": alert.get("flatVerticalGrade"),
        "bypassesThen": bypasses,
        "ftvPass": ftv.allowed,
        "ftvMode": ftv.mode if ftv.allowed else ftv.reason,
        "pretradePass": ok_pre,
        "pretradeBlocker": pre_reason if not ok_pre else None,
        "gatePass": bool(gate.get("wouldPass")),
        "gateBlocker": gate.get("primaryBlocker"),
        "fullPass": full_pass,
        "blocker": (
            None
            if full_pass
            else (
                ftv.reason
                if not ftv.allowed
                else (pre_reason if not ok_pre else gate.get("primaryBlocker"))
            )
        ),
    }


def analyze_winner(
    trade: dict[str, Any],
    radar_cache: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    ctx = trade.get("entryContext") or {}
    sym = str(trade.get("symbol") or "NIFTY")
    radar_key = ctx.get("radarKey") or f"{sym}:{trade.get('side')}:{trade.get('strike')}"
    date = str(trade.get("sessionDate") or "")

    rows = _load_radar_rows(date, radar_cache) if date else None
    if rows:
        row = _best_radar_row(rows, radar_key)
        if row:
            alert = dict(row.get("alert") or {})
            alert.setdefault("symbol", sym)
            snap = _snap(row)
            return evaluate_alert(sym=sym, alert=alert, snap=snap, trade=trade, source="radar")

    return evaluate_alert(
        sym=sym,
        alert=alert_from_trade(trade),
        snap=snap_from_trade(trade),
        trade=trade,
        source="entryContext",
    )


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    radar_rows = [r for r in rows if r["source"] == "radar"]
    ctx_rows = [r for r in rows if r["source"] == "entryContext"]

    def stats(group: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(group)
        if not n:
            return {"count": 0}
        return {
            "count": n,
            "ftvPass": sum(1 for r in group if r["ftvPass"]),
            "pretradePass": sum(1 for r in group if r["pretradePass"]),
            "fullPass": sum(1 for r in group if r["fullPass"]),
        }

    blockers = Counter(r["blocker"] for r in rows if r.get("blocker"))
    return {
        "total": len(rows),
        "radarBacked": stats(radar_rows),
        "entryContextOnly": stats(ctx_rows),
        "topBlockers": blockers.most_common(10),
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Check historical winners vs current gates")
    parser.add_argument("--min-pnl", type=float, default=500.0, help="Minimum winner P&L in INR")
    parser.add_argument("--api", default=DEFAULT_API, help="Closed trades API URL")
    parser.add_argument("--out", default=str(ARTIFACT), help="JSON report path")
    args = parser.parse_args()

    trades = fetch_closed_trades(args.api)
    winners = [
        t
        for t in trades
        if float(t.get("pnlInr") or 0) >= args.min_pnl
        and (t.get("entryContext") or {}).get("selectionMode") == "explosion"
    ]
    winners.sort(key=lambda t: -float(t.get("pnlInr") or 0))

    print(f"Checking {len(winners)} explosion winners (≥₹{args.min_pnl:,.0f})…", flush=True)
    radar_cache: dict[str, list[dict[str, Any]]] = {}
    rows = [analyze_winner(t, radar_cache) for t in winners]
    summary = summarize(rows)
    summary["runAt"] = datetime.now(IST).isoformat()
    summary["deployCommit"] = None
    try:
        with urllib.request.urlopen(
            "https://jashuvatrade.xyz/api/deployment/status", timeout=15,
        ) as resp:
            summary["deployCommit"] = json.load(resp).get("commit")
    except Exception:
        pass

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    rb = summary["radarBacked"]
    ec = summary["entryContextOnly"]
    print()
    print("Radar-backed (accurate):")
    if rb.get("count"):
        print(
            f"  {rb['fullPass']}/{rb['count']} full pass | "
            f"FTV {rb['ftvPass']}/{rb['count']} | pretrade {rb['pretradePass']}/{rb['count']}"
        )
    else:
        print("  no archives matched")

    print("EntryContext-only (approximate):")
    if ec.get("count"):
        print(
            f"  {ec['fullPass']}/{ec['count']} full pass | "
            f"FTV {ec['ftvPass']}/{ec['count']} | pretrade {ec['pretradePass']}/{ec['count']}"
        )

    print("\nResults:")
    for r in rows:
        mark = "PASS" if r["fullPass"] else "BLOCK"
        print(
            f"  [{mark}] {r['date']} {r['key']} ₹{r['pnlInr']:,} "
            f"({r['source']}) ftv={r['ftvMode']} → {r['blocker'] or 'ok'}"
        )

    print(f"\nReport: {out_path}")


if __name__ == "__main__":
    main()
