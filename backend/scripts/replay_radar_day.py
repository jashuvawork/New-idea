#!/usr/bin/env python3
"""Replay a stored premium tape through the production explosion detector in isolation.

Usage:
  python -m scripts.replay_radar_day --date 2026-08-19
  python -m scripts.replay_radar_day --date 2026-08-19 --symbol SENSEX --strike 76900

Reads telemetry/{date}.premium.jsonl when present, otherwise extracts
premium_tape.jsonl from radar-{date}.zip under the archive dir.
"""

from __future__ import annotations

import argparse
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.engines import explosion_detector, ict_breakout_monitor, session_timing
from app.engines.explosion_detector import (
    refresh_snapshot_explosion_alerts,
    reset_detector_state_for_tests,
)
from app.models.schemas import (
    HeatmapStrike,
    MarketPhase,
    Side,
    SymbolSnapshot,
)
from app.services.radar_archive import _review_rank, archive_path
from app.services.radar_learning import premium_tape_path, read_premium_tape

IST = ZoneInfo("Asia/Kolkata")


class _ReplayDateTime(datetime):
    current = datetime.now(IST)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.current.replace(tzinfo=None)
        return cls.current.astimezone(tz)


def _rank(alert: dict[str, Any]) -> tuple[float, ...]:
    return _review_rank(alert)


def _load_batches(date: str) -> list[dict[str, Any]]:
    tape = premium_tape_path(date)
    if tape.exists():
        return read_premium_tape(date)
    zip_path = archive_path(date)
    if not zip_path.exists():
        return []
    with zipfile.ZipFile(zip_path, "r") as archive:
        names = set(archive.namelist())
        member = "premium_tape.jsonl" if "premium_tape.jsonl" in names else None
        if member is None:
            return []
        rows: list[dict[str, Any]] = []
        for line in archive.read(member).decode("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
        return rows


def _is_v_base_moment(alert: dict[str, Any]) -> bool:
    return bool(
        alert.get("ictEliteBaseReady")
        or alert.get("ictArmedBaseLaunch")
        or alert.get("ictFirstLift")
        or (
            alert.get("ictBaseArmed")
            and float(alert.get("ictBaseRelativeMovePct") or 0) <= 25.0
            and float(alert.get("offLowMovePct") or alert.get("localBaseMovePct") or 0)
            <= 25.0
        )
    )


def replay_radar_day(
    date: str,
    *,
    symbol: str | None = None,
    strike: float | None = None,
) -> dict[str, Any]:
    batches = sorted(
        _load_batches(date),
        key=lambda row: str(row.get("ts") or ""),
    )
    symbol_filter = (symbol or "").upper() or None
    state: dict[str, dict[tuple[float, str], dict[str, Any]]] = {}
    best: dict[str, tuple[float, ...]] = {}
    timeline: list[dict[str, Any]] = []
    v_base_moments: list[dict[str, Any]] = []
    mid_rip_rejects: list[dict[str, Any]] = []
    reset_detector_state_for_tests()
    original_datetimes = (
        explosion_detector.datetime,
        ict_breakout_monitor.datetime,
        session_timing.datetime,
    )
    original_market_phase = session_timing.get_market_phase
    try:
        explosion_detector.datetime = _ReplayDateTime
        ict_breakout_monitor.datetime = _ReplayDateTime
        session_timing.datetime = _ReplayDateTime
        session_timing.get_market_phase = lambda: "LIVE_MARKET"
        for batch in batches:
            ts = datetime.fromisoformat(str(batch["ts"]))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=IST)
            _ReplayDateTime.current = ts.astimezone(IST)
            grouped: dict[str, list[dict[str, Any]]] = {}
            for contract in batch.get("contracts") or []:
                grouped.setdefault(str(contract.get("symbol") or "").upper(), []).append(
                    contract
                )
            for sym, contracts in grouped.items():
                if symbol_filter and sym != symbol_filter:
                    continue
                symbol_state = state.setdefault(sym, {})
                for contract in contracts:
                    strike_v = float(contract.get("strike") or 0)
                    side = str(contract.get("side") or "").upper()
                    if strike is not None and abs(strike_v - float(strike)) >= 1e-6:
                        continue
                    if strike_v > 0 and side in {"CALL", "PUT"}:
                        symbol_state[(strike_v, side)] = dict(contract)
                if strike is not None:
                    symbol_state = {
                        key: value
                        for key, value in symbol_state.items()
                        if abs(key[0] - float(strike)) < 1e-6
                    }
                    if not symbol_state:
                        continue
                strikes = sorted({s for s, _ in symbol_state})
                heatmap: list[HeatmapStrike] = []
                for strike_v in strikes:
                    call = symbol_state.get((strike_v, Side.CALL.value), {})
                    put = symbol_state.get((strike_v, Side.PUT.value), {})
                    heatmap.append(HeatmapStrike(
                        strike=strike_v,
                        callLtp=float(call.get("premium") or 0) or None,
                        putLtp=float(put.get("premium") or 0) or None,
                        callOi=int(call.get("oi") or 0),
                        putOi=int(put.get("oi") or 0),
                    ))
                sample = next(iter(symbol_state.values()))
                # Seed session extremes from tape so V-base replay sees day/session low.
                for (strike_v, side_name), contract in symbol_state.items():
                    sess_low = float(contract.get("sessionLow") or 0)
                    sess_peak = float(contract.get("sessionPeak") or 0)
                    prem = float(contract.get("premium") or 0)
                    if sess_low > 0 or sess_peak > 0:
                        key = explosion_detector._open_key(
                            sym, strike_v, Side(side_name)
                        )
                        if sess_low > 0:
                            cur = explosion_detector._session_low.get(key)
                            if cur is None or sess_low < cur:
                                explosion_detector._session_low[key] = sess_low
                        if sess_peak > 0:
                            cur_p = explosion_detector._session_peak.get(key)
                            if cur_p is None or sess_peak > cur_p:
                                explosion_detector._session_peak[key] = sess_peak
                        if prem > 0:
                            explosion_detector._record_local_base(key, ts, prem)
                snap = SymbolSnapshot(
                    symbol=sym,
                    timestamp=ts,
                    marketPhase=MarketPhase.LIVE_MARKET,
                    dataAvailable=True,
                    spot=float(sample.get("spot") or 0),
                    atmStrike=float(sample.get("atmStrike") or 0),
                    heatmap=heatmap,
                )
                refresh_snapshot_explosion_alerts(snap)
                for alert in snap.explosionAlerts or []:
                    key = (
                        f"{sym}:{str(alert.get('side') or '').upper()}:"
                        f"{float(alert.get('strike') or 0):g}"
                    )
                    if strike is not None and abs(
                        float(alert.get("strike") or 0) - float(strike)
                    ) >= 1e-6:
                        continue
                    row = {
                        "ts": ts.isoformat(),
                        "key": key,
                        "tier": alert.get("tier"),
                        "score": alert.get("explosionScore"),
                        "premium": alert.get("premium"),
                        "momentType": alert.get("momentType"),
                        "ictFirstLift": alert.get("ictFirstLift"),
                        "ictBaseArmed": alert.get("ictBaseArmed"),
                        "ictEliteBaseReady": alert.get("ictEliteBaseReady"),
                        "ictArmedBaseLaunch": alert.get("ictArmedBaseLaunch"),
                        "ictBasePremium": alert.get("ictBasePremium"),
                        "ictBaseRelativeMovePct": alert.get("ictBaseRelativeMovePct"),
                        "offLowMovePct": alert.get("offLowMovePct"),
                        "localBaseMovePct": alert.get("localBaseMovePct"),
                        "ictMidRipCoil": alert.get("ictMidRipCoil"),
                        "tradeable": alert.get("tradeable"),
                    }
                    if alert.get("ictMidRipCoil"):
                        mid_rip_rejects.append(row)
                    if _is_v_base_moment(alert):
                        v_base_moments.append(row)
                    rank = _rank(alert)
                    if rank <= best.get(key, ()):
                        continue
                    best[key] = rank
                    timeline.append(row)
    finally:
        (
            explosion_detector.datetime,
            ict_breakout_monitor.datetime,
            session_timing.datetime,
        ) = original_datetimes
        session_timing.get_market_phase = original_market_phase
        reset_detector_state_for_tests()

    elite_ready = [
        row for row in v_base_moments if row.get("ictEliteBaseReady")
    ]
    return {
        "date": date,
        "mode": "isolated_production_detector",
        "sampleBatches": len(batches),
        "uniqueRadarKeys": len(best),
        "filters": {"symbol": symbol_filter, "strike": strike},
        "vBaseMomentCount": len(v_base_moments),
        "eliteBaseReadyCount": len(elite_ready),
        "midRipRejectCount": len(mid_rip_rejects),
        "vBaseMoments": v_base_moments[:200],
        "midRipRejects": mid_rip_rejects[:100],
        "timeline": timeline,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--symbol")
    parser.add_argument("--strike", type=float)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = replay_radar_day(
        args.date,
        symbol=args.symbol,
        strike=args.strike,
    )
    payload = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
