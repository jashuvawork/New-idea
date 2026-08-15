#!/usr/bin/env python3
"""Replay a stored premium tape through the production explosion detector in isolation."""

from __future__ import annotations

import argparse
import json
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
from app.services.radar_archive import _review_rank
from app.services.radar_learning import read_premium_tape

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


def replay_radar_day(date: str) -> dict[str, Any]:
    batches = sorted(
        read_premium_tape(date),
        key=lambda row: str(row.get("ts") or ""),
    )
    state: dict[str, dict[tuple[float, str], dict[str, Any]]] = {}
    best: dict[str, tuple[float, ...]] = {}
    timeline: list[dict[str, Any]] = []
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
            for symbol, contracts in grouped.items():
                symbol_state = state.setdefault(symbol, {})
                for contract in contracts:
                    strike = float(contract.get("strike") or 0)
                    side = str(contract.get("side") or "").upper()
                    if strike > 0 and side in {"CALL", "PUT"}:
                        symbol_state[(strike, side)] = dict(contract)
                strikes = sorted({strike for strike, _ in symbol_state})
                heatmap: list[HeatmapStrike] = []
                for strike in strikes:
                    call = symbol_state.get((strike, Side.CALL.value), {})
                    put = symbol_state.get((strike, Side.PUT.value), {})
                    heatmap.append(HeatmapStrike(
                        strike=strike,
                        callLtp=float(call.get("premium") or 0) or None,
                        putLtp=float(put.get("premium") or 0) or None,
                        callOi=int(call.get("oi") or 0),
                        putOi=int(put.get("oi") or 0),
                    ))
                sample = contracts[0]
                snap = SymbolSnapshot(
                    symbol=symbol,
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
                        f"{symbol}:{str(alert.get('side') or '').upper()}:"
                        f"{float(alert.get('strike') or 0):g}"
                    )
                    rank = _rank(alert)
                    if rank <= best.get(key, ()):
                        continue
                    best[key] = rank
                    timeline.append({
                        "ts": ts.isoformat(),
                        "key": key,
                        "tier": alert.get("tier"),
                        "score": alert.get("explosionScore"),
                        "premium": alert.get("premium"),
                        "momentType": alert.get("momentType"),
                        "ictFirstLift": alert.get("ictFirstLift"),
                        "tradeable": alert.get("tradeable"),
                    })
    finally:
        (
            explosion_detector.datetime,
            ict_breakout_monitor.datetime,
            session_timing.datetime,
        ) = original_datetimes
        session_timing.get_market_phase = original_market_phase
        reset_detector_state_for_tests()
    return {
        "date": date,
        "mode": "isolated_production_detector",
        "sampleBatches": len(batches),
        "uniqueRadarKeys": len(best),
        "timeline": timeline,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = replay_radar_day(args.date)
    payload = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
