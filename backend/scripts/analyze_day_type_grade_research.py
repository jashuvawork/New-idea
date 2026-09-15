#!/usr/bin/env python3
"""Research: which day types need grade B/C loosening for fast-moving FTV moments."""

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
from app.engines.chop_day_guards import _day_mode_label, in_momentum_rally_window
from app.engines.missed_trade_explainer import _candidate_from_alert, _gate_checks
from app.engines.top_moment_gate import (
    classify_top_moment_type,
    resolve_top_moment_min_grade,
    top_moment_entry_allowed,
)
from app.engines.trade_ranking import rank_entry_candidate, rank_trade_evidence
from app.models.schemas import AutoTraderState, Breadth, MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")
BASE_URL = "https://www.jashuvatrade.xyz"
ARCHIVE_DIR = Path("/tmp/eod_audit_archives")
FIXTURE_FUNNEL = ROOT / "tests/fixtures/radar_archives/aug25/funnel_events.jsonl"
OUT_PATH = Path("/opt/cursor/artifacts/day_type_grade_research.json")

AUDIT_DATES = [
    "2026-08-19",
    "2026-08-24",
    "2026-08-25",
    "2026-08-26",
    "2026-08-27",
    "2026-09-01",
    "2026-09-02",
]

TIER_RANK = {"WATCH": 1, "BUILDING": 2, "EXPLODING": 3, "ELITE": 4}


def _download(date: str) -> Path:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dest = _archive_path(date)
    if dest.exists() and dest.stat().st_size > 1000:
        return dest
    print(f"  downloading {date}...", flush=True)
    urllib.request.urlretrieve(f"{BASE_URL}/api/ai/radar-archives/{date}", dest)
    return dest


def _archive_path(date: str) -> Path:
    return ARCHIVE_DIR / f"radar-{date}.zip"


def _load_radars(date: str) -> list[dict[str, Any]]:
    path = _archive_path(date)
    if path.exists() and path.stat().st_size > 1000:
        with zipfile.ZipFile(path) as zf:
            if "all_radars.json" in zf.namelist():
                return json.loads(zf.read("all_radars.json"))
    if date == "2026-08-25" and FIXTURE_FUNNEL.exists():
        return []
    return []


def _load_funnel(date: str) -> list[dict[str, Any]]:
    path = _archive_path(date)
    if path.exists() and path.stat().st_size > 1000:
        with zipfile.ZipFile(path) as zf:
            if "funnel_events.jsonl" in zf.namelist():
                rows = []
                for line in zf.read("funnel_events.jsonl").decode("utf-8").splitlines():
                    if line.strip():
                        rows.append(json.loads(line))
                return rows
    if date == "2026-08-25" and FIXTURE_FUNNEL.exists():
        rows = []
        for line in FIXTURE_FUNNEL.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows
    return []


def _parse_ts(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(str(raw))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=IST)
        return ts.astimezone(IST)
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


def _breadth_summary(snapshots: dict[str, SymbolSnapshot]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for sym, snap in snapshots.items():
        regime = "RANGE_BOUND"
        if snap.spotChart and snap.spotChart.direction in ("BULLISH", "BEARISH"):
            regime = snap.spotChart.direction
        out[sym.upper()] = {
            "bias": (snap.breadth.bias or "NEUTRAL").upper(),
            "regime": regime,
        }
    return out


def _infer_day_mode(ts: datetime, snapshots: dict[str, SymbolSnapshot]) -> str:
    """Best-effort day mode from timestamp + snapshot breadth (historical)."""
    breadth = _breadth_summary(snapshots)
    biases = [b.get("bias", "NEUTRAL") for b in breadth.values()]
    bullish = sum(1 for b in biases if b == "BULLISH")
    bearish = sum(1 for b in biases if b == "BEARISH")
    n = len(biases)
    chop = n > 0 and (
        sum(1 for b in biases if b == "NEUTRAL") >= (n + 1) // 2
        or sum(1 for b in breadth.values() if b.get("regime") == "RANGE_BOUND")
        >= max(1, (2 * n + 2) // 3)
    )
    hour, minute = ts.hour, ts.minute
    momentum = (hour == 11 or hour == 12 or (hour == 13 and minute <= 45))
    before_primary = hour < 10 or (hour == 10 and minute == 0)

    mode, _, _ = _day_mode_label(
        chop=chop,
        momentum=momentum,
        breadth=breadth,
        before_primary=before_primary,
    )
    return mode


def _alert_evidence(alert: dict[str, Any], ranking: dict[str, Any]) -> dict[str, Any]:
    ev = dict(ranking.get("evidence") or {})
    ev.setdefault("tier", str(alert.get("tier") or "").upper())
    ev.setdefault("explosionScore", float(alert.get("explosionScore") or 0))
    return ev


def analyze_date(date: str, settings: Settings) -> dict[str, Any]:
    radars = _load_radars(date)
    funnel = _load_funnel(date)
    if not radars and not funnel:
        return {"date": date, "status": "no_data"}

    state = AutoTraderState()
    by_day_mode: dict[str, Counter] = defaultdict(Counter)
    grade_at_moment: Counter = Counter()
    blocked_at_min: dict[str, Counter] = {"A": Counter(), "B": Counter(), "C": Counter()}
    fast_move_c_blocked: Counter = Counter()
    moment_types: Counter = Counter()

    top_rows = [
        r
        for r in radars
        if TIER_RANK.get(str((r.get("alert") or {}).get("tier", "")).upper(), 0) >= 3
    ]

    for row in top_rows:
        alert = row.get("alert") or {}
        sym = str(row.get("symbol") or "SENSEX")
        snap = _snap_from_row(row)
        ts = snap.timestamp
        day_mode = _infer_day_mode(ts, {sym: snap})

        candidate = _candidate_from_alert(sym, snap, alert)
        ranking = rank_entry_candidate(candidate)
        grade = str(ranking.get("grade") or "C").upper()
        score = float(ranking.get("rankScore") or 0)
        evidence = _alert_evidence(alert, ranking)
        moment = classify_top_moment_type(evidence)

        grade_at_moment[grade] += 1
        if moment:
            moment_types[moment] += 1

        v3 = float(evidence.get("velocity3s") or 0)
        tier = str(evidence.get("tier") or "").upper()
        is_fast = v3 >= 2.0 or tier in ("ELITE", "EXPLODING")

        for min_g in ("A", "B", "C"):
            ok, reason, _ = top_moment_entry_allowed(
                evidence,
                ranking,
                top_moments_only_enabled=True,
                min_grade=min_g,
                day_mode=day_mode,
            )
            if not ok:
                blocked_at_min[min_g][reason] += 1

        effective_min = resolve_top_moment_min_grade(
            min_grade="A", day_mode=day_mode, settings=settings,
        )
        ok_eff, reason_eff, _ = top_moment_entry_allowed(
            evidence,
            ranking,
            top_moments_only_enabled=True,
            min_grade="A",
            day_mode=day_mode,
        )
        by_day_mode[day_mode]["total"] += 1
        if ok_eff:
            by_day_mode[day_mode]["pass_current_policy"] += 1
        else:
            by_day_mode[day_mode][f"block:{reason_eff}"] += 1

        if grade == "C" and is_fast and moment:
            fast_move_c_blocked[day_mode] += 1
            # Would C min grade + current day policy allow?
            ok_c, _, _ = top_moment_entry_allowed(
                evidence, ranking, min_grade="C", day_mode=day_mode,
            )
            if ok_c:
                by_day_mode[day_mode]["fast_c_would_pass_at_c"] += 1

    funnel_blocks = Counter(
        str(r.get("reason") or "")
        for r in funnel
        if str(r.get("event") or "").upper() == "GATED"
    )

    return {
        "date": date,
        "status": "ok",
        "topMoments": len(top_rows),
        "gradeDistribution": dict(grade_at_moment),
        "momentTypes": dict(moment_types),
        "byDayMode": {k: dict(v) for k, v in by_day_mode.items()},
        "blockedAtMinGrade": {k: dict(v.most_common(8)) for k, v in blocked_at_min.items()},
        "fastMoveGradeCByDayMode": dict(fast_move_c_blocked),
        "funnelGateBlocks": funnel_blocks.most_common(12),
        "funnelEvents": len(funnel),
    }


def synthesize_recommendations(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate cross-day patterns into day-type grade policy recommendations."""
    agg: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        if row.get("status") != "ok":
            continue
        for mode, stats in (row.get("byDayMode") or {}).items():
            total = int(stats.get("total") or 0)
            if total <= 0:
                continue
            agg[mode]["total"] += total
            agg[mode]["pass"] += int(stats.get("pass_current_policy") or 0)
            agg[mode]["fast_c"] += int(stats.get("fast_c_would_pass_at_c") or 0)
            for k, v in stats.items():
                if k.startswith("block:top_moment_requires_grade"):
                    agg[mode]["grade_blocks"] += int(v)

    recs: list[dict[str, Any]] = []
    for mode, stats in sorted(agg.items(), key=lambda x: -x[1]["total"]):
        total = stats["total"]
        pass_pct = round(100 * stats["pass"] / total, 1) if total else 0
        grade_block_pct = round(100 * stats["grade_blocks"] / total, 1) if total else 0
        fast_c = stats["fast_c"]
        suggested_min = "A"
        rationale = []

        if mode in ("MOMENTUM RALLY", "CHOP + RALLY"):
            suggested_min = "B"
            rationale.append("Fast velocity window — grade-B EXPLODING pads common")
            if fast_c >= 3 or grade_block_pct >= 25:
                suggested_min = "C"
                rationale.append(
                    f"{fast_c} fast EXPLODING/ELITE grade-C moments would pass at min C"
                )
        elif mode in ("BULLISH DAY", "BEARISH DAY", "LEAN BULLISH", "LEAN BEARISH"):
            suggested_min = "B"
            rationale.append("Directional day — allow causal B moments on aligned side")
            if grade_block_pct >= 30 and fast_c >= 2:
                suggested_min = "C"
                rationale.append("High grade-block rate on directional rip days")
        elif mode in ("CHOP DAY", "CHOP (PRE-10)"):
            suggested_min = "A"
            rationale.append("Chop — keep strict; C grade adds noise")
        elif mode == "EXPIRY WORST":
            suggested_min = "A"
            rationale.append("Expiry worst — existing strict FTV floors apply")
        elif mode == "MIXED DAY":
            suggested_min = "B"
            rationale.append("Mixed breadth — B for confirmed top moments only")
        else:
            suggested_min = "A"
            rationale.append("Normal/default — grade A unless proven fast-day pattern")

        recs.append(
            {
                "dayMode": mode,
                "samples": total,
                "currentPassPct": pass_pct,
                "gradeBlockPct": grade_block_pct,
                "fastGradeCMoments": fast_c,
                "suggestedMinGrade": suggested_min,
                "rationale": rationale,
            }
        )

    return {"dayTypePolicies": recs}


def main() -> int:
    settings = Settings()
    settings.radar_archive_dir = str(ARCHIVE_DIR)
    settings.trade_store_dir = str(ARCHIVE_DIR.parent / "trades")
    settings.top_moments_momentum_rally_grade_b_enabled = True
    settings.top_moments_exploding_elite_grade_b_enabled = True
    settings.top_moments_day_type_grade_policy_enabled = True
    settings.top_moments_fast_day_grade_c_enabled = True

    for d in AUDIT_DATES:
        try:
            _download(d)
        except Exception as exc:
            print(f"  warn: could not download {d}: {exc}", flush=True)

    rows = [analyze_date(d, settings) for d in AUDIT_DATES]
    out = {
        "runAt": datetime.now(IST).isoformat(),
        "dates": rows,
        "recommendations": synthesize_recommendations(rows),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
