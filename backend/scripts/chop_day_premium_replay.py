#!/usr/bin/env python3
"""Offline chop vs trend book on radar premium_tape.jsonl (no live gates)."""

from __future__ import annotations

import argparse
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
ENTRY_EARLIEST = time(9, 45)
SESSION_END = time(15, 30)


@dataclass
class TapePoint:
    ts: datetime
    premium: float
    spot: float
    off_low_pct: float


@dataclass
class OpenTrade:
    key: str
    side: str
    entry_ts: datetime
    entry_premium: float
    session_prem_low: float
    mode: str
    mfe_pct: float = 0.0
    mae_pct: float = 0.0


def _parse_ts(raw: str) -> datetime:
    ts = datetime.fromisoformat(raw)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=IST)
    return ts.astimezone(IST)


def iter_tape(zip_path: Path) -> Iterator[dict[str, Any]]:
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open("premium_tape.jsonl") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    yield json.loads(line)


def load_symbol_spots(zip_path: Path, symbol: str) -> list[tuple[datetime, float]]:
    spots: list[tuple[datetime, float]] = []
    for batch in iter_tape(zip_path):
        ts = _parse_ts(batch["ts"])
        for c in batch.get("contracts") or []:
            key = str(c.get("key") or "")
            if key.startswith(f"{symbol}:") and c.get("spot"):
                spots.append((ts, float(c["spot"])))
                break
    return spots


def chop_day_heuristic(spots: list[tuple[datetime, float]]) -> dict[str, Any]:
    """Range-bound day: modest spot range, low net drift."""
    if len(spots) < 50:
        return {"chopLikely": False, "reason": "insufficient_spot"}
    by_ts = sorted(spots, key=lambda x: x[0])
    vals = [v for _, v in by_ts if v > 0]
    hi, lo = max(vals), min(vals)
    mid = (hi + lo) / 2.0
    range_pct = (hi - lo) / mid * 100.0 if mid else 0.0
    net_pct = abs(vals[-1] - vals[0]) / mid * 100.0 if mid else 0.0
    chop_likely = range_pct < 0.85 and net_pct < 0.45
    return {
        "chopLikely": chop_likely,
        "spotRangePct": round(range_pct, 3),
        "spotNetPct": round(net_pct, 3),
        "spotHigh": hi,
        "spotLow": lo,
    }


def load_contract_series(zip_path: Path, contract_key: str) -> list[TapePoint]:
    out: list[TapePoint] = []
    for batch in iter_tape(zip_path):
        ts = _parse_ts(batch["ts"])
        for c in batch.get("contracts") or []:
            if c.get("key") == contract_key:
                prem = float(c.get("premium") or 0)
                if prem <= 0:
                    break
                out.append(
                    TapePoint(
                        ts=ts,
                        premium=prem,
                        spot=float(c.get("spot") or 0),
                        off_low_pct=float(c.get("offLowMovePct") or 0),
                    )
                )
                break
    return out


def _spot_range_pos(spot: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.5
    return (spot - lo) / (hi - lo)


def _chop_entry_signal(
    pt: TapePoint,
    side: str,
    spot_lo: float,
    spot_hi: float,
    session_prem_low: float,
    last_entry_ts: datetime | None,
    *,
    cooldown_s: int = 900,
) -> bool:
    if pt.ts.time() < ENTRY_EARLIEST:
        return False
    if last_entry_ts and (pt.ts - last_entry_ts).total_seconds() < cooldown_s:
        return False
    pos = _spot_range_pos(pt.spot, spot_lo, spot_hi)
    prem_near_low = (pt.premium - session_prem_low) / session_prem_low * 100.0 if session_prem_low > 0 else 99.0
    if prem_near_low > 18.0:
        return False
    if pt.off_low_pct > 22.0:
        return False
    if side == "PUT":
        return pos >= 0.72
    return pos <= 0.28


def _trend_entry_signal(pt: TapePoint, side: str, last_entry_ts: datetime | None, *, cooldown_s: int = 600) -> bool:
    """Trend book proxy: breakout-style (high off-low), mid-range OK."""
    if pt.ts.time() < time(9, 20):
        return False
    if last_entry_ts and (pt.ts - last_entry_ts).total_seconds() < cooldown_s:
        return False
    return pt.off_low_pct >= 12.0 and pt.off_low_pct <= 45.0


def _simulate_side(
    series: list[TapePoint],
    side: str,
    spot_lo: float,
    spot_hi: float,
    mode: str,
) -> list[dict[str, Any]]:
    if not series:
        return []
    tp = 25.0 if mode == "chop" else 50.0
    sl = 8.0 if mode == "chop" else 10.0
    max_hold = 2700 if mode == "chop" else 5400
    size_mult = 0.5 if mode == "chop" else 1.0
    trades: list[dict[str, Any]] = []
    open_t: OpenTrade | None = None
    session_prem_low = series[0].premium
    last_entry: datetime | None = None

    for pt in series:
        if pt.ts.time() > SESSION_END:
            if open_t:
                move = (pt.premium - open_t.entry_premium) / open_t.entry_premium * 100.0
                trades.append(_close(open_t, pt.ts, pt.premium, move, "session_end", size_mult))
                open_t = None
            break
        session_prem_low = min(session_prem_low, pt.premium)

        if open_t:
            move = (pt.premium - open_t.entry_premium) / open_t.entry_premium * 100.0
            open_t.mfe_pct = max(open_t.mfe_pct, move)
            open_t.mae_pct = min(open_t.mae_pct, move)
            age = (pt.ts - open_t.entry_ts).total_seconds()
            if move >= tp:
                trades.append(_close(open_t, pt.ts, pt.premium, move, "take_profit", size_mult))
                open_t = None
                continue
            if move <= -sl:
                trades.append(_close(open_t, pt.ts, pt.premium, move, "stop_loss", size_mult))
                open_t = None
                continue
            if age >= max_hold:
                trades.append(_close(open_t, pt.ts, pt.premium, move, "time_stop", size_mult))
                open_t = None
            continue

        if mode == "chop":
            ok = _chop_entry_signal(pt, side, spot_lo, spot_hi, session_prem_low, last_entry)
        else:
            ok = _trend_entry_signal(pt, side, last_entry)
        if ok:
            open_t = OpenTrade(
                key="",
                side=side,
                entry_ts=pt.ts,
                entry_premium=pt.premium,
                session_prem_low=session_prem_low,
                mode=mode,
            )
            last_entry = pt.ts

    return trades


def _close(tr: OpenTrade, exit_ts: datetime, exit_prem: float, move_pct: float, reason: str, size_mult: float) -> dict[str, Any]:
    hold_s = (exit_ts - tr.entry_ts).total_seconds()
    return {
        "mode": tr.mode,
        "side": tr.side,
        "entryAt": tr.entry_ts.isoformat(),
        "exitAt": exit_ts.isoformat(),
        "entryPremium": round(tr.entry_premium, 2),
        "exitPremium": round(exit_prem, 2),
        "movePct": round(move_pct, 2),
        "mfePct": round(tr.mfe_pct, 2),
        "maePct": round(tr.mae_pct, 2),
        "holdSeconds": int(hold_s),
        "exitReason": reason,
        "notionalMult": size_mult,
        "scorePts": round(move_pct * size_mult, 2),
    }


def _pick_contracts(zip_path: Path, symbol: str, max_keys: int = 6) -> list[str]:
    counts: dict[str, int] = {}
    for batch in iter_tape(zip_path):
        for c in batch.get("contracts") or []:
            key = str(c.get("key") or "")
            if key.startswith(f"{symbol}:") and float(c.get("premium") or 0) > 50:
                counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return [k for k, _ in ranked[:max_keys]]


_index_day_types_cache: dict[tuple[str, str, str], dict[str, str]] = {}


def _load_index_day_types(symbol: str, from_date: str, to_date: str) -> dict[str, str]:
    key = (symbol, from_date, to_date)
    if key in _index_day_types_cache:
        return _index_day_types_cache[key]
    from datetime import date as date_cls
    from scripts.index_5y_daytype_study import daily_bars

    lo, hi = date_cls.fromisoformat(from_date), date_cls.fromisoformat(to_date)
    mapping = {b["date"]: b["dayType"] for b in daily_bars(symbol, lo, hi)}
    _index_day_types_cache[key] = mapping
    return mapping


def analyze_zip(
    zip_path: Path,
    symbol: str = "NIFTY",
    extra_keys: list[str] | None = None,
    *,
    index_day_types: dict[str, str] | None = None,
) -> dict[str, Any]:
    date = zip_path.stem.replace("radar-", "")
    spots = load_symbol_spots(zip_path, symbol)
    day_meta = chop_day_heuristic(spots)
    day_meta["indexDayType"] = (index_day_types or {}).get(date)
    spot_lo, spot_hi = day_meta.get("spotLow", 0), day_meta.get("spotHigh", 0)
    keys = list(dict.fromkeys((extra_keys or []) + _pick_contracts(zip_path, symbol)))
    per_key: list[dict[str, Any]] = []
    totals = {"chop": 0.0, "trend": 0.0}
    counts = {"chop": 0, "trend": 0}

    for key in keys:
        side = "PUT" if ":PUT:" in key else "CALL"
        series = load_contract_series(zip_path, key)
        if len(series) < 100:
            continue
        chop_tr = _simulate_side(series, side, spot_lo, spot_hi, "chop")
        trend_tr = _simulate_side(series, side, spot_lo, spot_hi, "trend")
        chop_score = sum(t["scorePts"] for t in chop_tr)
        trend_score = sum(t["scorePts"] for t in trend_tr)
        totals["chop"] += chop_score
        totals["trend"] += trend_score
        counts["chop"] += len(chop_tr)
        counts["trend"] += len(trend_tr)
        hi_prem = max(p.premium for p in series)
        lo_prem = min(p.premium for p in series)
        per_key.append(
            {
                "key": key,
                "tapeSamples": len(series),
                "sessionPremiumLow": round(lo_prem, 2),
                "sessionPremiumHigh": round(hi_prem, 2),
                "swingPct": round((hi_prem - lo_prem) / lo_prem * 100.0, 2) if lo_prem else 0,
                "chopTrades": len(chop_tr),
                "trendTrades": len(trend_tr),
                "chopScorePts": round(chop_score, 2),
                "trendScorePts": round(trend_score, 2),
                "chopDeltaVsTrend": round(chop_score - trend_score, 2),
                "bestChopTrade": max(chop_tr, key=lambda t: t["movePct"], default=None),
            }
        )

    return {
        "date": date,
        "zip": str(zip_path),
        "dayMeta": day_meta,
        "contracts": per_key,
        "totals": {
            **{f"{k}ScorePts": round(v, 2) for k, v in totals.items()},
            **{f"{k}Trades": counts[k] for k in counts},
            "chopMinusTrendPts": round(totals["chop"] - totals["trend"], 2),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", action="append", type=Path, default=[])
    parser.add_argument("--zip-dir", type=Path, default=None)
    parser.add_argument("--symbol", default="NIFTY")
    parser.add_argument("--extra-key", action="append", default=["NIFTY:PUT:25200"])
    parser.add_argument("--out", type=Path, default=Path("/opt/cursor/artifacts/chop-day-replay-report.json"))
    args = parser.parse_args()

    zips = list(args.zip)
    if args.zip_dir and args.zip_dir.is_dir():
        zips.extend(sorted(args.zip_dir.glob("radar-*.zip")))
    zips = sorted(dict.fromkeys(zips))
    if not zips:
        parser.error("No radar ZIPs (use --zip or --zip-dir)")

    dates = sorted(p.stem.replace("radar-", "") for p in zips)
    index_day_types = (
        _load_index_day_types(args.symbol, dates[0], dates[-1]) if dates else {}
    )
    reports = [
        analyze_zip(
            p,
            symbol=args.symbol,
            extra_keys=args.extra_key,
            index_day_types=index_day_types,
        )
        for p in zips
    ]
    chop_days = [r for r in reports if r["dayMeta"].get("chopLikely")]
    by_day_type: dict[str, dict[str, float]] = {}
    for r in reports:
        dt = r["dayMeta"].get("indexDayType") or "UNKNOWN"
        row = by_day_type.setdefault(
            dt,
            {"days": 0, "chopScorePts": 0.0, "trendScorePts": 0.0, "chopMinusTrendPts": 0.0},
        )
        row["days"] += 1
        row["chopScorePts"] += r["totals"]["chopScorePts"]
        row["trendScorePts"] += r["totals"]["trendScorePts"]
        row["chopMinusTrendPts"] += r["totals"]["chopMinusTrendPts"]
    for row in by_day_type.values():
        row["chopScorePts"] = round(row["chopScorePts"], 2)
        row["trendScorePts"] = round(row["trendScorePts"], 2)
        row["chopMinusTrendPts"] = round(row["chopMinusTrendPts"], 2)
    summary = {
        "zipCount": len(reports),
        "chopHeuristicDays": len(chop_days),
        "aggregate": {
            "chopScorePts": round(sum(r["totals"]["chopScorePts"] for r in reports), 2),
            "trendScorePts": round(sum(r["totals"]["trendScorePts"] for r in reports), 2),
            "chopMinusTrendPts": round(
                sum(r["totals"]["chopMinusTrendPts"] for r in reports), 2
            ),
            "chopOnlyDays": {
                "chopScorePts": round(sum(r["totals"]["chopScorePts"] for r in chop_days), 2),
                "trendScorePts": round(sum(r["totals"]["trendScorePts"] for r in chop_days), 2),
                "chopMinusTrendPts": round(
                    sum(r["totals"]["chopMinusTrendPts"] for r in chop_days), 2
                ),
            },
        },
        "byIndexDayType": dict(sorted(by_day_type.items())),
        "days": reports,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "days"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())