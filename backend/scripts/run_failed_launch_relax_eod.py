#!/usr/bin/env python3
"""Compare failed_launch exit P&L: legacy thresholds vs global relax + elite runner relax."""

from __future__ import annotations

import json
import statistics
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import Settings
from app.engines.chop_day_guards import _day_mode_label
from app.engines.day_type_grade_policy import fast_moving_grade_c_waiver, resolve_day_type_min_grade
from app.engines.day_adaptive_engine import classify_day_type
from app.engines.eod_local_base_replay import _simulate_trade_from_entry
from app.engines.entry_timing import assess_entry_timing, timing_blocks_entry
from app.engines.elite_score_engine import (
    STAGE_RANK,
    build_elite_assessment,
    elite_entry_allowed,
    infer_setup_type,
    infer_stage,
)
from app.engines.ict_breakout_monitor import ICTBreakoutSignal
from app.engines.missed_trade_explainer import _candidate_from_alert
from app.engines.top_moment_gate import classify_top_moment_type
from app.engines.trade_ranking import rank_entry_candidate
from app.models.schemas import Breadth, MarketPhase, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")
ARCHIVE_DIR = Path("/tmp/eod_audit_archives")
OUT_PATH = Path("/opt/cursor/artifacts/elite_failed_launch_relax_eod.json")
_MOMENTUM_RALLY_DAY_MODE = "MOMENTUM RALLY"


def _contract_key(symbol: str, side: str, strike: float) -> str:
    return f"{symbol.upper()}:{side.upper()}:{strike:g}"


def _parse_ts(raw: Any, fallback_date: str = "") -> datetime:
    if raw:
        ts = datetime.fromisoformat(str(raw))
        return ts.replace(tzinfo=IST) if ts.tzinfo is None else ts.astimezone(IST)
    if fallback_date:
        return datetime.fromisoformat(f"{fallback_date}T12:00:00+05:30")
    return datetime.now(IST)


def _snap(row: dict[str, Any], date: str = "") -> SymbolSnapshot:
    ctx, alert = row.get("context") or {}, row.get("alert") or {}
    sc = ctx.get("spotChart") or {}
    spot_chart = (
        SpotChart(**{k: sc[k] for k in sc if k in SpotChart.model_fields})
        if sc
        else SpotChart(direction="NEUTRAL", spot=float(ctx.get("spot") or 0))
    )
    sym = str(row.get("symbol") or alert.get("symbol") or "SENSEX")
    return SymbolSnapshot(
        symbol=sym,
        timestamp=_parse_ts(row.get("ts"), date),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=float(ctx.get("spot") or 0),
        breadth=Breadth(bias=str((ctx.get("breadth") or {}).get("bias") or "NEUTRAL")),
        spotChart=spot_chart,
        tradeQualityScore=float(ctx.get("tradeQualityScore") or 55),
        explosionAlerts=[alert],
    )


def _infer_day_mode(ts: datetime, snap: SymbolSnapshot) -> str:
    breadth = {
        snap.symbol.upper(): {
            "bias": (snap.breadth.bias or "NEUTRAL").upper(),
            "regime": snap.spotChart.direction
            if snap.spotChart and snap.spotChart.direction in ("BULLISH", "BEARISH")
            else "RANGE_BOUND",
        }
    }
    biases = [b["bias"] for b in breadth.values()]
    n = len(biases)
    chop = n > 0 and (
        sum(1 for b in biases if b == "NEUTRAL") >= (n + 1) // 2
        or sum(1 for b in breadth.values() if b.get("regime") == "RANGE_BOUND")
        >= max(1, (2 * n + 2) // 3)
    )
    h, m = ts.hour, ts.minute
    momentum = h == 11 or h == 12 or (h == 13 and m <= 45)
    before_primary = h < 10 or (h == 10 and m == 0)
    mode, _, _ = _day_mode_label(
        chop=chop, momentum=momentum, breadth=breadth, before_primary=before_primary
    )
    return mode


def _ict(alert: dict[str, Any]) -> ICTBreakoutSignal:
    return ICTBreakoutSignal(
        active=bool(alert.get("ictBreakout") or alert.get("ictFlatThenVertical")),
        pattern=str(alert.get("momentType") or alert.get("ictPattern") or ""),
        score=float(alert.get("flatVerticalQuality") or 0),
        reasons=[],
        premium_fvg=bool(alert.get("ictPremiumFvg") or alert.get("premiumFvgPad")),
        flat_then_vertical=bool(alert.get("ictFlatThenVertical")),
        displacement=bool(alert.get("ictDisplacement")),
        volume_awakening=bool(alert.get("ictVolumeAwakening") or alert.get("volumeAwaken")),
        session_move_pct=float(alert.get("dailyMovePct") or alert.get("peakMovePct") or 0),
        velocity_3s=float(alert.get("velocity3s") or 0),
        volume_surge=float(alert.get("volumeSurge") or 1),
        base_premium=float(alert.get("ictBasePremium") or 0),
        base_relative_move_pct=float(
            alert.get("ictBaseRelativeMovePct") or alert.get("localBaseMovePct") or 0
        ),
        local_swing_base=bool(alert.get("ictLocalSwingBase")),
        flat_vertical_quality=float(alert.get("flatVerticalQuality") or 0),
        flat_vertical_grade=str(alert.get("flatVerticalGrade") or ""),
        first_lift=bool(alert.get("ictFirstLift")),
        base_armed=bool(alert.get("ictBaseArmed")),
        elite_base_ready=bool(alert.get("ictEliteBaseReady")),
        v_rip_ready=bool(alert.get("ictVRipReady")),
        building_rip_ready=bool(alert.get("ictBuildingRipReady")),
        armed_base_launch=bool(alert.get("ictArmedBaseLaunch")),
        armed_base_sustained_lift=bool(alert.get("ictArmedBaseSustainedLift")),
    )


def _load_radars(date: str) -> list[dict[str, Any]]:
    path = ARCHIVE_DIR / f"radar-{date}.zip"
    if not path.exists() or path.stat().st_size < 1000:
        return []
    with zipfile.ZipFile(path) as zf:
        if "all_radars.json" not in zf.namelist():
            return []
        return json.loads(zf.read("all_radars.json"))


def _live_gate_row(date: str, row: dict[str, Any], settings: Settings) -> dict[str, Any] | None:
    alert = row.get("alert") or {}
    outcome = row.get("outcome") or {}
    mfe = float(outcome.get("mfePct") or 0)
    mae = float(outcome.get("maePct") or 0)
    if mfe <= 0 and mae == 0:
        return None

    sym = str(row.get("symbol") or alert.get("symbol") or "SENSEX")
    snap = _snap(row, date)
    ict = _ict(alert)
    candidate = _candidate_from_alert(sym, snap, alert)
    ranking = rank_entry_candidate(candidate)
    ev = dict(ranking.get("evidence") or {})
    ev.setdefault("tier", str(alert.get("tier") or "").upper())
    ev.setdefault("explosionScore", float(alert.get("explosionScore") or 0))
    moment = classify_top_moment_type(ev)
    setup = infer_setup_type(ev, moment=moment)
    stage = infer_stage(ev)
    local = float(alert.get("ictBaseRelativeMovePct") or alert.get("localBaseMovePct") or 999)
    timing = assess_entry_timing(candidate.explosion_event, ict=ict, snap=snap)
    timing_assessment = str(timing.get("assessment") or "")
    timing_ok = timing_assessment in ("GOOD", "OK") and not timing_blocks_entry(timing)[0]
    ev = {**ev, "timingAssessment": timing_assessment}
    day_mode = _infer_day_mode(snap.timestamp, snap)
    day_type = classify_day_type(day_mode, "MEDIUM", {sym: snap})

    with patch("app.config.get_settings", return_value=settings):
        elite_ok, _, assessment = elite_entry_allowed(
            ev, ranking, settings=settings, day_mode=day_mode, snapshots={sym: snap},
        )

    if not elite_ok:
        return None
    if not (
        setup in ("FTV", "V", "EXPLOSIVE")
        and STAGE_RANK.get(stage, 0) >= STAGE_RANK["ARMED"]
        and local <= 25.0
        and timing_ok
    ):
        return None
    if (
        str(day_type).upper() == "WORST"
        and str(day_mode).upper() == _MOMENTUM_RALLY_DAY_MODE
    ):
        return None

    ts = _parse_ts(row.get("ts"), date)
    return {
        "date": date,
        "ts": ts,
        "symbol": sym,
        "side": str(alert.get("side") or "").upper(),
        "strike": float(alert.get("strike") or 0),
        "tier": str(alert.get("tier") or "").upper(),
        "localBasePct": round(local, 1),
        "dayMode": day_mode,
        "dayType": day_type,
        "eliteScore": float(assessment.get("eliteScore") or 0),
        "grade": str(ranking.get("grade") or "").upper(),
        "assessment": assessment,
        "alert": alert,
        "entryCtx": {
            "topMomentType": moment,
            "grade": str(ranking.get("grade") or "").upper(),
            "velocity3s": alert.get("velocity3s"),
            "volumeSurge": alert.get("volumeSurge"),
            "ictFlatThenVertical": alert.get("ictFlatThenVertical"),
            "ictFirstLift": alert.get("ictFirstLift"),
            "ictArmedBaseLaunch": alert.get("ictArmedBaseLaunch"),
            "ictEliteBaseReady": alert.get("ictEliteBaseReady"),
            "ictVRipReady": alert.get("ictVRipReady"),
            "momentType": moment,
            "eliteAssessment": assessment,
            "timingAssessment": timing_assessment,
        },
    }


def _premium_series(date: str) -> dict[str, list[tuple[datetime, float]]]:
    series: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    zip_path = ARCHIVE_DIR / f"radar-{date}.zip"
    if not zip_path.exists():
        return series
    with zipfile.ZipFile(zip_path) as zf:
        if "premium_tape.jsonl" not in zf.namelist():
            return series
        for line in zf.read("premium_tape.jsonl").decode("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            batch = json.loads(line)
            ts = _parse_ts(batch.get("ts"), date)
            for row in batch.get("contracts") or batch.get("premiums") or []:
                sym = str(row.get("symbol") or batch.get("symbol") or "").upper()
                side = str(row.get("side") or "").upper()
                strike = float(row.get("strike") or 0)
                prem = float(row.get("premium") or row.get("ltp") or 0)
                if sym and side and strike > 0 and prem > 0:
                    series[_contract_key(sym, side, strike)].append((ts, prem))
    for key in series:
        series[key].sort(key=lambda x: x[0])
    return series


def _simulate(row: dict[str, Any], settings: Settings, premium: dict) -> dict[str, Any] | None:
    key = _contract_key(row["symbol"], row["side"], row["strike"])
    alert = row["alert"]
    ep = float(alert.get("premium") or 0)
    if ep <= 0:
        return None
    base = float(alert.get("ictBasePremium") or alert.get("basePremium") or 0)
    forward = [(t, p) for t, p in premium.get(key, []) if t >= row["ts"]]
    if len(forward) < 2:
        return None
    if base <= 0:
        hist = [p for t, p in premium.get(key, []) if (row["ts"] - t).total_seconds() <= 1200 and p > 0]
        base = min(hist) if hist else ep
    return _simulate_trade_from_entry(
        symbol=row["symbol"],
        side=row["side"],
        strike=row["strike"],
        tier=row["tier"],
        entry_ts=row["ts"],
        entry_premium=ep,
        base_premium=base,
        forward=forward,
        settings=settings,
        entry_ctx=row["entryCtx"],
    )


def _summary(trades: list[dict[str, Any]], label: str) -> dict[str, Any]:
    if not trades:
        return {"label": label, "trades": 0, "totalPnlInr": 0}
    pnls = [float(t["pnlInr"]) for t in trades]
    reasons = Counter(str(t.get("exitReason") or "") for t in trades)
    return {
        "label": label,
        "trades": len(trades),
        "totalPnlInr": round(sum(pnls), 0),
        "avgPnlInr": round(statistics.mean(pnls), 0),
        "winRatePct": round(100 * sum(1 for p in pnls if p > 0) / len(pnls), 1),
        "exitReasons": reasons.most_common(),
        "failedLaunchCount": reasons.get("explosion_failed_launch", 0),
    }


def main() -> int:
    base = Settings(
        elite_trade_engine_enabled=True,
        max_sizing_capital_inr=200_000.0,
        fallback_capital_inr=200_000.0,
        per_trade_capital_pct=0.90,
        use_upstox_capital_for_sizing=False,
    )
    legacy = Settings(**{
        **base.model_dump(),
        "explosion_failed_launch_max_hold_seconds": 45,
        "explosion_failed_launch_max_best_points": 1.0,
        "explosion_failed_launch_max_velocity_3s": 0.0,
        "elite_failed_launch_relax_enabled": False,
    })
    current = Settings(**{
        **base.model_dump(),
        "explosion_failed_launch_max_hold_seconds": 60,
        "explosion_failed_launch_max_best_points": 2.0,
        "elite_failed_launch_relax_enabled": True,
    })

    dates = sorted(
        p.stem.replace("radar-", "")
        for p in ARCHIVE_DIR.glob("radar-*.zip")
        if p.stat().st_size > 5000
    )

    candidates: list[dict[str, Any]] = []
    for date in dates:
        for row in _load_radars(date):
            parsed = _live_gate_row(date, row, base)
            if parsed:
                candidates.append(parsed)

    # De-dupe: one entry per contract per timestamp
    seen: set[tuple] = set()
    unique: list[dict[str, Any]] = []
    for r in sorted(candidates, key=lambda x: x["ts"]):
        key = (r["date"], r["symbol"], r["side"], r["strike"], r["ts"].isoformat())
        if key not in seen:
            seen.add(key)
            unique.append(r)

    legacy_trades: list[dict[str, Any]] = []
    current_trades: list[dict[str, Any]] = []
    skipped = 0
    premium_cache: dict[str, dict] = {}

    for row in unique:
        date = row["date"]
        if date not in premium_cache:
            premium_cache[date] = _premium_series(date)
        premium = premium_cache[date]
        leg = _simulate(row, legacy, premium)
        cur = _simulate(row, current, premium)
        if leg is None or cur is None:
            skipped += 1
            continue
        legacy_trades.append({**row, **leg, "policy": "legacy"})
        current_trades.append({**row, **cur, "policy": "current"})

    out = {
        "liveGateCandidates": len(unique),
        "replayedWithPremiumTape": len(legacy_trades),
        "skippedNoTape": skipped,
        "legacy": _summary(legacy_trades, "legacy thresholds (45s/1pt, no elite relax)"),
        "current": _summary(current_trades, "current (60s/2pt + elite runner relax)"),
        "upliftInr": round(
            sum(float(t["pnlInr"]) for t in current_trades)
            - sum(float(t["pnlInr"]) for t in legacy_trades),
            0,
        ),
        "improvedTrades": sum(
            1
            for leg, cur in zip(legacy_trades, current_trades)
            if float(cur["pnlInr"]) > float(leg["pnlInr"]) + 1
        ),
        "worsenedTrades": sum(
            1
            for leg, cur in zip(legacy_trades, current_trades)
            if float(cur["pnlInr"]) < float(leg["pnlInr"]) - 1
        ),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
