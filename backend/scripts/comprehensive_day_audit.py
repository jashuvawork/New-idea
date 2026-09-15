#!/usr/bin/env python3
"""Complete day picture audit — day types, gates, flips, trades, FTV, EOD."""

from __future__ import annotations

import json
import sys
import urllib.request
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.engines.chop_day_guards import _day_mode_label
from app.engines.missed_trade_explainer import _candidate_from_alert
from app.engines.top_moment_gate import (
    classify_top_moment_type,
    resolve_top_moment_min_grade,
    top_moment_entry_allowed,
)
from app.engines.trade_ranking import rank_entry_candidate
from app.models.schemas import Breadth, MarketPhase, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")
BASE_URL = "https://www.jashuvatrade.xyz"
ARCHIVE_DIR = Path("/tmp/eod_audit_archives")
OUT_PATH = Path("/opt/cursor/artifacts/comprehensive_day_audit.json")

DATES = [
    "2026-08-19",
    "2026-08-24",
    "2026-08-25",
    "2026-08-26",
    "2026-08-27",
    "2026-09-01",
    "2026-09-02",
]

TIER_RANK = {"WATCH": 1, "BUILDING": 2, "EXPLODING": 3, "ELITE": 4}

# Gate reason families we track across funnel + radar.
GRADE_KEYS = ("top_moment_requires_grade", "top_moment_grade_reject")
FLIP_KEYS = (
    "directional_lock",
    "aligned_side",
    "index_rally",
    "side_flip",
    "session_locked",
    "market_direction",
    "exec_chart_live_bullish_no_puts",
    "exec_chart_live_bearish_no_calls",
)
FUNNEL_DOWNSTREAM = (
    "explosion_near_miss",
    "exec_premium_fading",
    "allocation_rank",
    "per_trade_risk",
    "timing_blocked",
    "ftv_elite_top_only",
)


def _download(date: str) -> Path | None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dest = ARCHIVE_DIR / f"radar-{date}.zip"
    if dest.exists() and dest.stat().st_size > 10000:
        return dest
    try:
        urllib.request.urlretrieve(f"{BASE_URL}/api/ai/radar-archives/{date}", dest)
        return dest if dest.stat().st_size > 1000 else None
    except Exception:
        return None


def _load_json_from_zip(path: Path, name: str) -> Any:
    with zipfile.ZipFile(path) as zf:
        if name not in zf.namelist():
            return None
        return json.loads(zf.read(name))


def _load_funnel(path: Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(path) as zf:
        if "funnel_events.jsonl" not in zf.namelist():
            return []
        rows = []
        for line in zf.read("funnel_events.jsonl").decode("utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows


def _fetch_trades_by_date() -> dict[str, list[dict[str, Any]]]:
    url = f"{BASE_URL}/api/auto-trader/history/trades/closed?limit=300"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            payload = json.loads(resp.read())
    except Exception:
        return {}
    trades = payload.get("trades") if isinstance(payload, dict) else payload
    if not isinstance(trades, list):
        return {}
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in trades:
        d = str(t.get("sessionDate") or (t.get("openedAt") or "")[:10])
        if d:
            by_date[d].append(t)
    return dict(by_date)


def _parse_ts(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
        return ts.replace(tzinfo=IST) if ts.tzinfo is None else ts.astimezone(IST)
    except ValueError:
        return None


def _snap_from_row(row: dict[str, Any]) -> SymbolSnapshot:
    ctx, alert = row.get("context") or {}, row.get("alert") or {}
    sc = ctx.get("spotChart") or {}
    spot_chart = (
        SpotChart(**{k: sc[k] for k in sc if k in SpotChart.model_fields})
        if sc
        else SpotChart(direction="NEUTRAL", spot=float(ctx.get("spot") or 0))
    )
    ts = _parse_ts(row.get("ts")) or datetime.now(IST)
    return SymbolSnapshot(
        symbol=str(row.get("symbol") or alert.get("symbol") or "SENSEX"),
        timestamp=ts,
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=float(ctx.get("spot") or 0),
        breadth=Breadth(bias=str((ctx.get("breadth") or {}).get("bias") or "NEUTRAL")),
        spotChart=spot_chart,
        tradeQualityScore=float(ctx.get("tradeQualityScore") or 55),
        explosionAlerts=[alert],
    )


def _infer_day_mode(ts: datetime, snapshots: dict[str, SymbolSnapshot]) -> str:
    breadth: dict[str, dict] = {}
    for sym, snap in snapshots.items():
        regime = "RANGE_BOUND"
        if snap.spotChart and snap.spotChart.direction in ("BULLISH", "BEARISH"):
            regime = snap.spotChart.direction
        breadth[sym.upper()] = {
            "bias": (snap.breadth.bias or "NEUTRAL").upper(),
            "regime": regime,
        }
    biases = [b.get("bias", "NEUTRAL") for b in breadth.values()]
    n = len(biases) or 1
    chop = sum(1 for b in biases if b == "NEUTRAL") >= (n + 1) // 2
    hour, minute = ts.hour, ts.minute
    momentum = hour == 11 or hour == 12 or (hour == 13 and minute <= 45)
    before_primary = hour < 10 or (hour == 10 and minute == 0)
    mode, _, _ = _day_mode_label(
        chop=chop, momentum=momentum, breadth=breadth, before_primary=before_primary,
    )
    return mode


def _classify_funnel_reason(reason: str) -> str:
    r = str(reason or "").lower()
    if any(k in r for k in GRADE_KEYS):
        return "grade_gate"
    if any(k in r for k in FLIP_KEYS):
        return "side_flip_or_direction"
    if "explosion_near_miss" in r:
        return "explosion_near_miss"
    if "exec_premium_fading" in r or "exec_mtf_premium" in r:
        return "premium_fading"
    if "allocation_rank" in r or "requires_allocation" in r:
        return "allocation_rank"
    if "per_trade_risk" in r:
        return "risk_cap"
    if "timing" in r:
        return "timing"
    return "other"


def _analyze_radar(date: str, radars: list[dict], settings: Settings) -> dict[str, Any]:
    by_mode: dict[str, Counter] = defaultdict(Counter)
    grade_dist: Counter = Counter()
    policy_off_blocks = 0
    policy_on_blocks = 0
    policy_unlocked = 0

    top_rows = [
        r for r in radars
        if TIER_RANK.get(str((r.get("alert") or {}).get("tier", "")).upper(), 0) >= 3
    ]

    for row in top_rows:
        alert = row.get("alert") or {}
        sym = str(row.get("symbol") or "SENSEX")
        snap = _snap_from_row(row)
        day_mode = _infer_day_mode(snap.timestamp, {sym: snap})
        candidate = _candidate_from_alert(sym, snap, alert)
        ranking = rank_entry_candidate(candidate)
        grade = str(ranking.get("grade") or "C").upper()
        grade_dist[grade] += 1
        evidence = dict(ranking.get("evidence") or {})
        evidence.setdefault("tier", str(alert.get("tier") or "").upper())

        off_settings = Settings(**{
            **settings.model_dump(),
            "top_moments_day_type_grade_policy_enabled": False,
            "top_moments_fast_day_grade_c_enabled": False,
        })
        from unittest.mock import patch

        with patch("app.config.get_settings", return_value=off_settings):
            ok_off, reason_off, _ = top_moment_entry_allowed(
                evidence, ranking, day_mode=day_mode,
            )
        with patch("app.config.get_settings", return_value=settings):
            ok_on, reason_on, _ = top_moment_entry_allowed(
                evidence, ranking, day_mode=day_mode,
            )
        by_mode[day_mode]["total"] += 1
        if ok_on:
            by_mode[day_mode]["top_moment_pass"] += 1
        else:
            by_mode[day_mode][f"block:{reason_on}"] += 1
        if not ok_off:
            policy_off_blocks += 1
        if not ok_on:
            policy_on_blocks += 1
        if not ok_off and ok_on:
            policy_unlocked += 1

    return {
        "topMoments": len(top_rows),
        "gradeDistribution": dict(grade_dist),
        "byDayMode": {k: dict(v) for k, v in by_mode.items()},
        "policyImpact": {
            "blockedOff": policy_off_blocks,
            "blockedOn": policy_on_blocks,
            "unlockedByPolicy": policy_unlocked,
        },
    }


def _analyze_funnel(funnel: list[dict]) -> dict[str, Any]:
    gated = [r for r in funnel if str(r.get("event") or "").upper() == "GATED"]
    reasons = Counter(str(r.get("reason") or "") for r in gated)
    families = Counter(_classify_funnel_reason(r) for r in reasons.elements())
    taken = [r for r in funnel if str(r.get("event") or "").upper() in {"TAKEN", "EXECUTED", "FILLED"}]
    return {
        "events": len(funnel),
        "gated": len(gated),
        "takenEvents": len(taken),
        "topBlockers": reasons.most_common(12),
        "families": dict(families.most_common()),
        "gradeBlocks": sum(v for k, v in reasons.items() if _classify_funnel_reason(k) == "grade_gate"),
        "flipBlocks": sum(v for k, v in reasons.items() if _classify_funnel_reason(k) == "side_flip_or_direction"),
    }


def _summarize_live_trades(trades: list[dict]) -> dict[str, Any]:
    if not trades:
        return {"count": 0}
    pnl = sum(float(t.get("pnlInr") or 0) for t in trades)
    wins = sum(1 for t in trades if float(t.get("pnlInr") or 0) > 0)
    by_side = Counter(str(t.get("side") or "").upper() for t in trades)
    hours = Counter(str((t.get("openedAt") or ""))[11:13] for t in trades if t.get("openedAt"))
    return {
        "count": len(trades),
        "netPnlInr": round(pnl),
        "wins": wins,
        "losses": len(trades) - wins,
        "bySide": dict(by_side),
        "byHour": dict(sorted(hours.items())),
        "entries": [
            {
                "time": (t.get("openedAt") or "")[11:19],
                "symbol": t.get("symbol"),
                "side": t.get("side"),
                "strike": t.get("strike"),
                "pnlInr": round(float(t.get("pnlInr") or 0)),
                "exitReason": t.get("exitReason"),
            }
            for t in sorted(trades, key=lambda x: str(x.get("openedAt") or ""))
        ],
    }


def _gaps_and_status(day: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    funnel = day.get("funnel") or {}
    radar = day.get("radar") or {}
    live = day.get("liveTrades") or {}
    policy = (radar.get("policyImpact") or {})

    if funnel.get("gradeBlocks", 0) > 0:
        gaps.append(f"grade_gate_in_funnel:{funnel['gradeBlocks']}")
    if funnel.get("flipBlocks", 0) > 0:
        gaps.append(f"side_flip_in_funnel:{funnel['flipBlocks']}")
    if funnel.get("families", {}).get("explosion_near_miss", 0) > 100:
        gaps.append("explosion_near_miss_dominant")
    if funnel.get("families", {}).get("premium_fading", 0) > 50:
        gaps.append("premium_fading_dominant")
    if funnel.get("families", {}).get("allocation_rank", 0) > 20:
        gaps.append("allocation_rank_pressure")
    if live.get("count", 0) == 0 and radar.get("topMoments", 0) > 20:
        gaps.append("zero_live_trades_despite_top_moments")
    if live.get("count", 0) > 0 and live.get("netPnlInr", 0) < -10000:
        gaps.append("live_day_loss")
    if policy.get("unlockedByPolicy", 0) > 0:
        gaps.append(f"policy_would_unlock_{policy['unlockedByPolicy']}_radar_moments")
    if day.get("status") == "no_archive":
        gaps.append("missing_eod_archive")
    return gaps


def audit_day(date: str, trades_by_date: dict[str, list], settings: Settings) -> dict[str, Any]:
    path = _download(date)
    if not path:
        return {"date": date, "status": "no_archive", "liveTrades": _summarize_live_trades(trades_by_date.get(date, []))}

    radars = _load_json_from_zip(path, "all_radars.json") or []
    scorecard = _load_json_from_zip(path, "scorecard.json")
    funnel = _load_funnel(path)
    has_tape = "premium_tape.jsonl" in zipfile.ZipFile(path).namelist()

    row = {
        "date": date,
        "status": "ok",
        "archiveKb": path.stat().st_size // 1024,
        "hasPremiumTape": has_tape,
        "scorecardSummary": {
            "radarAlertCount": (scorecard or {}).get("radarAlertCount"),
            "executableRadarCount": (scorecard or {}).get("executableRadarCount"),
            "outcomes": (scorecard or {}).get("outcomes"),
        } if scorecard else None,
        "radar": _analyze_radar(date, radars, settings),
        "funnel": _analyze_funnel(funnel),
        "liveTrades": _summarize_live_trades(trades_by_date.get(date, [])),
    }
    row["gaps"] = _gaps_and_status(row)
    return row


def _synthesize(days: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [d for d in days if d.get("status") == "ok"]
    agg_families: Counter = Counter()
    agg_modes: Counter = Counter()
    total_unlock = 0
    total_live_pnl = 0
    total_live_trades = 0

    for d in ok:
        for fam, cnt in (d.get("funnel") or {}).get("families", {}).items():
            agg_families[fam] += cnt
        for mode, stats in (d.get("radar") or {}).get("byDayMode", {}).items():
            agg_modes[mode] += int(stats.get("total") or 0)
        total_unlock += int((d.get("radar") or {}).get("policyImpact", {}).get("unlockedByPolicy") or 0)
        live = d.get("liveTrades") or {}
        total_live_pnl += int(live.get("netPnlInr") or 0)
        total_live_trades += int(live.get("count") or 0)

    remaining = []
    if agg_families.get("explosion_near_miss", 0) > 500:
        remaining.append("explosion_near_miss still #1 blocker — not solved by grade policy")
    if agg_families.get("premium_fading", 0) > 200:
        remaining.append("exec_premium_fading — execution timing, not grade")
    if agg_families.get("allocation_rank", 0) > 100:
        remaining.append("allocation rank gates — capital/ranking, not day-type")
    if total_unlock > 0:
        remaining.append(f"day-type policy unlocks {total_unlock} radar top-moments across {len(ok)} days")
    else:
        remaining.append("day-type policy: minimal radar unlock (grade rarely the sole blocker)")

    policy_by_mode = {}
    for d in ok:
        for mode, stats in (d.get("radar") or {}).get("byDayMode", {}).items():
            policy_by_mode.setdefault(mode, {"samples": 0, "pass": 0, "blocks": Counter()})
            policy_by_mode[mode]["samples"] += int(stats.get("total") or 0)
            policy_by_mode[mode]["pass"] += int(stats.get("top_moment_pass") or 0)
            for k, v in stats.items():
                if k.startswith("block:"):
                    policy_by_mode[mode]["blocks"][k.replace("block:", "")] += int(v)

    mode_summary = []
    for mode, stats in sorted(policy_by_mode.items(), key=lambda x: -x[1]["samples"]):
        s = stats["samples"]
        mode_summary.append({
            "dayMode": mode,
            "samples": s,
            "topMomentPassPct": round(100 * stats["pass"] / s, 1) if s else 0,
            "topBlockers": stats["blocks"].most_common(4),
            "recommendedMinGrade": (
                "B+C_waiver" if mode in ("MOMENTUM RALLY", "CHOP + RALLY", "BULLISH DAY", "BEARISH DAY")
                else "A"
            ),
        })

    return {
        "daysAudited": len(ok),
        "liveTradesTotal": total_live_trades,
        "liveNetPnlInr": total_live_pnl,
        "funnelBlockFamilies": agg_families.most_common(),
        "dayModeSamples": agg_modes.most_common(),
        "policyRadarUnlocks": total_unlock,
        "dayModePolicySummary": mode_summary,
        "remainingGaps": remaining,
        "leversInScope": [
            "day_type_min_grade (B on directional/momentum, A on chop/expiry)",
            "fast_day_grade_c_waiver (ELITE/EXPLODING, v3>=2, score>=50)",
            "exploding_elite_grade_b_waiver",
            "momentum_rally_grade_b",
            "index_rally_side_flip + neutral_macd_mom5_waiver",
        ],
    }


def main() -> int:
    settings = Settings()
    settings.radar_archive_dir = str(ARCHIVE_DIR)
    print("Fetching live trades...", flush=True)
    trades_by_date = _fetch_trades_by_date()
    print(f"  {sum(len(v) for v in trades_by_date.values())} closed trades loaded", flush=True)

    days = []
    for date in DATES:
        print(f"\n[{date}]", flush=True)
        row = audit_day(date, trades_by_date, settings)
        days.append(row)
        if row.get("status") == "ok":
            r, f, l = row["radar"], row["funnel"], row["liveTrades"]
            print(
                f"  radar top={r['topMoments']} policy_unlock={r['policyImpact']['unlockedByPolicy']} "
                f"funnel_gated={f['gated']} live={l.get('count',0)}t ₹{l.get('netPnlInr',0):,}",
                flush=True,
            )
            print(f"  gaps: {row.get('gaps')}", flush=True)

    out = {
        "runAt": datetime.now(IST).isoformat(),
        "days": days,
        "synthesis": _synthesize(days),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("\n" + json.dumps(out["synthesis"], indent=2), flush=True)
    print(f"\nWrote {OUT_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
