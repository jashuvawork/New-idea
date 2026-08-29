#!/usr/bin/env python3
"""False-start analysis for grade-A BUILDING armed_base_option_led_ready entries."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.engines.eod_local_base_replay import (
    _ReplayDateTime,
    _alert_evidence,
    _contract_key,
    _f,
    _load_batches,
    _spot_chart_from_history,
    evaluate_local_base_entry,
)
from app.engines.explosion_detector import (
    refresh_snapshot_explosion_alerts,
    reset_detector_state_for_tests,
)
from app.engines.ict_breakout_monitor import first_lift_entry_readiness
from app.engines.local_base_chart_bypass import local_base_entry_window
from app.engines.trade_ranking import rank_trade_evidence
from app.models.schemas import HeatmapStrike, MarketPhase, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")

DATES = ["2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28"]
MFE_WIN_PCT = 15.0
MFE_FALSE_START_PCT = 8.0
LOOKAHEAD_MINUTES = 120


def _forward_mfe(
    premium_series: dict[str, list[tuple[datetime, float]]],
    key: str,
    entry_ts: datetime,
    entry_prem: float,
    *,
    minutes: int = LOOKAHEAD_MINUTES,
) -> tuple[float, float]:
    series = premium_series.get(key) or []
    end_ts = entry_ts + timedelta(minutes=minutes)
    best = entry_prem
    last = entry_prem
    for ts, prem in series:
        if ts <= entry_ts:
            continue
        if ts > end_ts:
            break
        best = max(best, prem)
        last = prem
    if entry_prem <= 0:
        return 0.0, 0.0
    return (best - entry_prem) / entry_prem * 100.0, (last - entry_prem) / entry_prem * 100.0


def analyze_date(date: str) -> dict[str, Any]:
    from app.engines import explosion_detector, ict_breakout_monitor, session_timing

    settings = get_settings()
    batches = sorted(_load_batches(date), key=lambda row: str(row.get("ts") or ""))
    if not batches:
        return {"date": date, "status": "no_tape", "signals": []}

    premium_series: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for batch in batches:
        ts_raw = batch.get("ts")
        if not ts_raw:
            continue
        ts = datetime.fromisoformat(str(ts_raw))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=IST)
        else:
            ts = ts.astimezone(IST)
        for contract in batch.get("contracts") or []:
            sym = str(contract.get("symbol") or "").upper()
            side = str(contract.get("side") or "").upper()
            strike = _f(contract.get("strike"))
            prem = _f(contract.get("premium"))
            if sym and side in {"CALL", "PUT"} and strike > 0 and prem > 0:
                premium_series[_contract_key(sym, side, strike)].append((ts, prem))

    reset_detector_state_for_tests()
    state: dict[str, dict[tuple[float, str], dict[str, Any]]] = {}
    spot_hist: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    seen_keys: set[str] = set()
    signals: list[dict[str, Any]] = []

    original_datetimes = (
        explosion_detector.datetime,
        ict_breakout_monitor.datetime,
        session_timing.datetime,
    )
    session_timing.get_market_phase = lambda: "LIVE_MARKET"

    try:
        explosion_detector.datetime = _ReplayDateTime
        ict_breakout_monitor.datetime = _ReplayDateTime
        session_timing.datetime = _ReplayDateTime

        for batch in batches:
            ts_raw = batch.get("ts")
            if not ts_raw:
                continue
            ts = datetime.fromisoformat(str(ts_raw))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=IST)
            else:
                ts = ts.astimezone(IST)
            _ReplayDateTime.current = ts

            grouped: dict[str, list[dict[str, Any]]] = {}
            for contract in batch.get("contracts") or []:
                sym = str(contract.get("symbol") or "").upper()
                if sym:
                    grouped.setdefault(sym, []).append(contract)

            for sym, contracts in grouped.items():
                symbol_state = state.setdefault(sym, {})
                for contract in contracts:
                    strike_v = _f(contract.get("strike"))
                    side = str(contract.get("side") or "").upper()
                    prem = _f(contract.get("premium"))
                    spot = _f(contract.get("spot"))
                    if strike_v > 0 and side in {"CALL", "PUT"} and prem > 0:
                        symbol_state[(strike_v, side)] = dict(contract)
                        if spot > 0:
                            spot_hist[sym].append((ts, spot))

                if not symbol_state:
                    continue

                sample = next(iter(symbol_state.values()))
                spot = _f(sample.get("spot"))
                for (strike_v, side_name), contract in symbol_state.items():
                    sess_low = _f(contract.get("sessionLow"))
                    sess_peak = _f(contract.get("sessionPeak"))
                    prem = _f(contract.get("premium"))
                    if sess_low > 0 or sess_peak > 0:
                        det_key = explosion_detector._open_key(sym, strike_v, Side(side_name))
                        if sess_low > 0:
                            cur = explosion_detector._session_low.get(det_key)
                            if cur is None or sess_low < cur:
                                explosion_detector._session_low[det_key] = sess_low
                        if sess_peak > 0:
                            cur_p = explosion_detector._session_peak.get(det_key)
                            if cur_p is None or sess_peak > cur_p:
                                explosion_detector._session_peak[det_key] = sess_peak
                        if prem > 0:
                            explosion_detector._record_local_base(det_key, ts, prem)

                strikes = sorted({stk for stk, _ in symbol_state})
                heatmap: list[HeatmapStrike] = []
                for strike_v in strikes:
                    call = symbol_state.get((strike_v, Side.CALL.value), {})
                    put = symbol_state.get((strike_v, Side.PUT.value), {})
                    heatmap.append(
                        HeatmapStrike(
                            strike=strike_v,
                            callLtp=_f(call.get("premium")) or None,
                            putLtp=_f(put.get("premium")) or None,
                            callOi=int(call.get("oi") or 0),
                            putOi=int(put.get("oi") or 0),
                        )
                    )

                chart = _spot_chart_from_history(spot_hist[sym], spot)
                snap = SymbolSnapshot(
                    symbol=sym,
                    timestamp=ts,
                    marketPhase=MarketPhase.LIVE_MARKET,
                    dataAvailable=True,
                    spot=spot,
                    atmStrike=_f(sample.get("atmStrike")),
                    heatmap=heatmap,
                    spotChart=chart,
                    tradeQualityScore=55.0,
                )
                refresh_snapshot_explosion_alerts(snap)

                for alert in snap.explosionAlerts or []:
                    tier = str(alert.get("tier") or "").upper()
                    if tier != "BUILDING":
                        continue

                    ready, lift_reason = first_lift_entry_readiness(snap=snap, alert=alert)
                    if lift_reason != "armed_base_option_led_ready":
                        continue

                    evidence = _alert_evidence(alert, snap)
                    ranking = rank_trade_evidence(evidence)
                    grade = str(ranking.get("grade") or "").upper()
                    if grade != "A":
                        continue

                    side = str(alert.get("side") or "").upper()
                    strike = _f(alert.get("strike"))
                    key = _contract_key(sym, side, strike)
                    dedupe = f"{key}:{ts.strftime('%H:%M')}"
                    if dedupe in seen_keys:
                        continue
                    seen_keys.add(dedupe)

                    base_rel = _f(alert.get("ictBaseRelativeMovePct") or alert.get("localBaseMovePct"))
                    vol = _f(alert.get("volumeSurge"))
                    entry_min, chase_max = local_base_entry_window(tier, vol)
                    in_window = entry_min <= base_rel <= chase_max if base_rel > 0 else False

                    allowed, gate_reason, moment, _ = evaluate_local_base_entry(
                        alert, snap, settings=settings,
                    )
                    entry_prem = _f(alert.get("premium"))
                    mfe_pct, end_pct = _forward_mfe(premium_series, key, ts, entry_prem)
                    is_winner = mfe_pct >= MFE_WIN_PCT
                    is_false = mfe_pct < MFE_FALSE_START_PCT and end_pct <= 0

                    signals.append({
                        "time": ts.strftime("%H:%M:%S"),
                        "key": key,
                        "grade": grade,
                        "baseRelPct": round(base_rel, 1),
                        "inLocalBaseWindow": in_window,
                        "replayAllowed": allowed,
                        "gateReason": gate_reason,
                        "moment": moment,
                        "score": round(_f(alert.get("explosionScore")), 1),
                        "premium": round(entry_prem, 1),
                        "mfePct": round(mfe_pct, 1),
                        "endPct": round(end_pct, 1),
                        "outcome": "WINNER" if is_winner else ("FALSE_START" if is_false else "MIXED"),
                    })
    finally:
        explosion_detector.datetime = original_datetimes[0]
        ict_breakout_monitor.datetime = original_datetimes[1]
        session_timing.datetime = original_datetimes[2]

    winners = sum(1 for s in signals if s["outcome"] == "WINNER")
    false_starts = sum(1 for s in signals if s["outcome"] == "FALSE_START")
    mixed = len(signals) - winners - false_starts
    in_window = [s for s in signals if s["inLocalBaseWindow"]]
    iw_winners = sum(1 for s in in_window if s["outcome"] == "WINNER")
    iw_false = sum(1 for s in in_window if s["outcome"] == "FALSE_START")

    return {
        "date": date,
        "status": "ok",
        "totalSignals": len(signals),
        "winners": winners,
        "falseStarts": false_starts,
        "mixed": mixed,
        "inWindowSignals": len(in_window),
        "inWindowWinners": iw_winners,
        "inWindowFalseStarts": iw_false,
        "winRatePct": round(winners / len(signals) * 100, 1) if signals else 0.0,
        "inWindowWinRatePct": round(iw_winners / len(in_window) * 100, 1) if in_window else 0.0,
        "falseStartRatePct": round(false_starts / len(signals) * 100, 1) if signals else 0.0,
        "signals": signals,
    }


def main() -> None:
    results = [analyze_date(d) for d in DATES]
    summary = {
        "dates": DATES,
        "totalSignals": sum(r.get("totalSignals", 0) for r in results),
        "totalWinners": sum(r.get("winners", 0) for r in results),
        "totalFalseStarts": sum(r.get("falseStarts", 0) for r in results),
        "inWindowSignals": sum(r.get("inWindowSignals", 0) for r in results),
        "inWindowWinners": sum(r.get("inWindowWinners", 0) for r in results),
        "inWindowFalseStarts": sum(r.get("inWindowFalseStarts", 0) for r in results),
        "daily": results,
    }
    if summary["totalSignals"]:
        summary["winRatePct"] = round(
            summary["totalWinners"] / summary["totalSignals"] * 100, 1
        )
        summary["falseStartRatePct"] = round(
            summary["totalFalseStarts"] / summary["totalSignals"] * 100, 1
        )
    if summary["inWindowSignals"]:
        summary["inWindowWinRatePct"] = round(
            summary["inWindowWinners"] / summary["inWindowSignals"] * 100, 1
        )

    out_path = Path("/opt/cursor/artifacts/building_armed_base_false_starts.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
