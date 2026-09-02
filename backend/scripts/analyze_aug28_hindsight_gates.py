#!/usr/bin/env python3
"""Aug 28 hindsight vs live gate analysis at each sim entry time."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings, get_settings
from app.engines.eod_local_base_replay import (
    _ReplayDateTime,
    _alert_evidence,
    _contract_key,
    _enrich_alert_from_contract,
    _f,
    _load_batches,
    _spot_chart_from_history,
    evaluate_local_base_entry,
    evaluate_replay_live_gates,
)
from app.engines.explosion_detector import (
    refresh_snapshot_explosion_alerts,
    reset_detector_state_for_tests,
)
from app.models.schemas import (
    AutoTraderState,
    HeatmapStrike,
    MarketPhase,
    Side,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")

TARGETS = [
    {
        "id": 1,
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 24050,
        "entry": "11:12",
        "pnl": 78618,
        "lots": 82,
    },
    {
        "id": 2,
        "symbol": "SENSEX",
        "side": "PUT",
        "strike": 77500,
        "entry": "11:43",
        "pnl": -561,
        "lots": 1,
    },
    {
        "id": 3,
        "symbol": "SENSEX",
        "side": "PUT",
        "strike": 77500,
        "entry": "11:49",
        "pnl": 9027,
        "lots": 1,
    },
    {
        "id": 4,
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 24050,
        "entry": "12:59",
        "pnl": -13000,
        "lots": 1,
    },
    {
        "id": 5,
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 24150,
        "entry": "13:40",
        "pnl": -7719,
        "lots": 1,
    },
    {
        "id": 6,
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 24200,
        "entry": "14:50",
        "pnl": 565,
        "lots": 1,
    },
    {
        "id": 7,
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 24200,
        "entry": "14:58",
        "pnl": 24765,
        "lots": 1,
    },
]

LIVE_TRADES = [
    "NIFTY PUT 24200/24100 @11:20",
    "NIFTY PUT 24050 @12:55/13:28",
    "SENSEX PUT 77300/77200 @15:02",
]


def _parse_hm(hm: str) -> time:
    h, m = hm.split(":")
    return time(int(h), int(m))


def _target_dt(date: str, hm: str) -> datetime:
    t = _parse_hm(hm)
    return datetime.fromisoformat(date).replace(
        hour=t.hour, minute=t.minute, second=0, tzinfo=IST,
    )


def _selector_blocks(
    symbol: str,
    snap: SymbolSnapshot,
    alert: dict[str, Any],
    state: AutoTraderState,
    settings: Any,
) -> tuple[bool, str, dict[str, Any]]:
    """Mirror trade_selector._explosion_candidates filters for one alert."""
    from app.engines.early_radar_pad_capture import (
        alert_has_building_coil_pad,
        alert_has_early_radar_pad_capture,
        building_coil_pad_lift_signal,
    )
    from app.engines.ict_breakout_monitor import first_lift_entry_readiness
    from app.engines.pad_lane_capture import pad_lane_early_near_miss_waive
    from app.engines.premium_filter import premium_in_band
    from app.engines.trade_ranking import rank_trade_evidence

    meta: dict[str, Any] = {}
    first_lift_ready, lift_reason = first_lift_entry_readiness(
        snap=snap, alert=alert, state=state,
    )
    early_pad = alert_has_early_radar_pad_capture(alert)
    coil_pad = alert_has_building_coil_pad(alert)
    pad_lane_waive = pad_lane_early_near_miss_waive(
        alert, readiness_reason=lift_reason,
    )
    lift_ready = first_lift_ready or early_pad or coil_pad or pad_lane_waive
    meta["liftReason"] = lift_reason
    meta["liftReady"] = lift_ready
    meta["earlyPad"] = early_pad
    meta["coilPad"] = coil_pad
    meta["coilPadSignal"] = building_coil_pad_lift_signal(alert, settings)
    meta["padLaneWaive"] = pad_lane_waive

    if not alert.get("tradeable") and not lift_ready:
        return True, "not_tradeable_no_lift", meta

    if not premium_in_band(
        alert.get("premium"),
        mode="explosion",
        peak_move_pct=float(alert.get("peakMovePct") or 0),
        snap=snap,
    ):
        return True, "premium_out_of_band", meta

    tier_u = str(alert.get("tier") or "").upper()
    elite_only = bool(getattr(settings, "explosion_elite_exploding_only", True))
    top_only = bool(getattr(settings, "top_moments_only_enabled", True))
    ranking = rank_trade_evidence(_alert_evidence(alert, snap))
    meta["grade"] = ranking.get("grade")
    meta["rankScore"] = ranking.get("rankScore")

    from app.engines.building_ftv_gates import (
        building_armed_base_grade_a_live_ok,
        building_coil_pad_grade_a_live_ok,
    )
    from app.engines.top_moment_gate import explosion_alert_is_top_moment

    armed_base_ok = building_armed_base_grade_a_live_ok(
        alert,
        snap,
        readiness_reason=lift_reason,
        ranking=ranking,
        state=state,
        snapshots={symbol: snap},
    )
    coil_pad_ok = building_coil_pad_grade_a_live_ok(
        alert,
        snap,
        readiness_reason=lift_reason,
        ranking=ranking,
        state=state,
        snapshots={symbol: snap},
    )
    top_moment = explosion_alert_is_top_moment(alert)
    meta["armedBaseGradeA"] = armed_base_ok
    meta["coilPadGradeA"] = coil_pad_ok
    meta["topMoment"] = top_moment

    if elite_only and tier_u not in ("ELITE", "EXPLODING"):
        if top_only:
            if not top_moment and not pad_lane_waive and not armed_base_ok and not coil_pad_ok:
                return True, "tier_not_elite_exploding_top_moment", meta
        elif not lift_ready and not armed_base_ok and not coil_pad_ok:
            return True, "tier_not_elite_exploding", meta

    if bool(getattr(settings, "explosion_require_chart_align_enabled", True)):
        from app.models.schemas import Side as _Side
        from app.engines.spot_direction import side_aligned_with_chart

        side_raw = str(alert.get("side") or "").upper()
        try:
            side_v = _Side(side_raw)
        except Exception:
            side_v = None
        chart_aligned = (
            side_v is not None
            and snap.spotChart is not None
            and side_aligned_with_chart(side_v, snap.spotChart)
        )
        meta["chartAligned"] = chart_aligned
        if (
            side_v is not None
            and snap.spotChart is not None
            and not chart_aligned
            and not lift_ready
        ):
            from app.engines.local_base_chart_bypass import local_base_ichimoku_chart_bypass
            from app.engines.pad_lane_capture import pad_lane_turnaround_chart_bypass
            from app.engines.grade_a_ftv_capture import grade_a_ftv_chart_bypass

            local_base_ok = local_base_ichimoku_chart_bypass(side_v, snap, alert=alert)
            pad_lane_ok = pad_lane_turnaround_chart_bypass(side_v, snap, alert=alert)
            grade_a_ok = grade_a_ftv_chart_bypass(alert, snap)
            meta["localBaseChartBypass"] = local_base_ok
            meta["padLaneChartBypass"] = pad_lane_ok
            meta["gradeAFtvBypass"] = grade_a_ok
            if not local_base_ok and not pad_lane_ok and not grade_a_ok:
                return True, "chart_not_aligned", meta

    from app.engines.explosion_detector import effective_explosion_min_score

    score_val = float(alert.get("explosionScore", 0))
    min_score = effective_explosion_min_score(
        tier=tier_u,
        peak_move_pct=float(alert.get("peakMovePct") or 0),
        daily_move_pct=float(alert.get("dailyMovePct") or 0),
        first_lift_ready=first_lift_ready,
        local_base_move_pct=float(
            alert.get("localBaseMovePct") or alert.get("ictBaseRelativeMovePct") or 0
        ),
        v_rip_ready=bool(alert.get("ictVRipReady")),
    )
    meta["explosionScore"] = score_val
    meta["minExplosionScore"] = min_score
    if score_val < min_score and not lift_ready:
        return True, f"explosion_score_below_{min_score:g}", meta

    from app.engines.early_radar_pad_capture import cold_trough_pad_lift_signal

    meta["coldTroughPad"] = cold_trough_pad_lift_signal(alert, settings)

    return False, "selector_ok", meta


def _auto_trader_blocks(
    symbol: str,
    snap: SymbolSnapshot,
    alert: dict[str, Any],
    state: AutoTraderState,
    settings: Any,
) -> tuple[bool, str, dict[str, Any]]:
    """Key auto_trader pre-open gates."""
    from app.engines.ict_breakout_monitor import analyze_explosion_event_ict
    from app.engines.eod_local_base_replay import _candidate_from_alert
    from app.engines.explosion_entry_guards import (
        explosion_entry_window_blocked,
        live_explosion_confirmation_blocked,
    )

    meta: dict[str, Any] = {}
    candidate = _candidate_from_alert(alert, snap)
    event = candidate.explosion_event
    ict = analyze_explosion_event_ict(event, snap)

    from app.engines.ict_breakout_monitor import first_lift_entry_readiness

    first_lift_ready, lift_reason = first_lift_entry_readiness(
        snap=snap, alert=alert, state=state,
    )
    meta["liftReason"] = lift_reason

    window_blocked, window_reason = explosion_entry_window_blocked(
        event, ict=ict,
    )
    if window_blocked and not first_lift_ready:
        return True, f"entry_window:{window_reason}", meta

    from app.engines.elite_never_block import elite_never_block_active

    must_take = elite_never_block_active(
        event=event, ict=ict, snap=snap, alert=alert,
    )
    live_blocked, live_reason = live_explosion_confirmation_blocked(
        event, ict=ict, snap=snap,
    )
    meta["mustTake"] = must_take
    meta["liveConfirmBlocked"] = live_blocked
    if live_blocked and not must_take and not first_lift_ready:
        return True, f"live_confirm:{live_reason}", meta

    if settings.execution_chart_gate_enabled:
        from app.engines.spot_direction import (
            chart_blocks_side,
            hard_counter_trend_chart,
        )
        from app.engines.local_base_chart_bypass import local_base_ichimoku_chart_bypass
        from app.engines.pad_lane_capture import (
            pad_lane_turnaround_chart_bypass,
            resolve_strict_pad_lane_chart_bypass,
        )
        from app.engines.ftv_candlestick_confirm import ftv_candlestick_chart_bypass

        pad_lane_ok, strict_first_lift_ok = resolve_strict_pad_lane_chart_bypass(
            candidate, snap,
        )
        local_base_ok = local_base_ichimoku_chart_bypass(
            candidate.side, snap, event=event, alert=alert,
        )
        candlestick_ok = ftv_candlestick_chart_bypass(
            candidate.side, snap, alert=alert, event=event,
        )
        premium_bypass = pad_lane_ok or local_base_ok or candlestick_ok
        if (
            getattr(settings, "chart_counter_trend_bypass_block_enabled", True)
            and hard_counter_trend_chart(candidate.side, snap.spotChart)
            and not strict_first_lift_ok
        ):
            premium_bypass = False
            pad_lane_ok = False
        blocked, chart_reason = chart_blocks_side(
            candidate.side, snap.spotChart,
            premium_led_bypass=premium_bypass,
            strict_first_lift_bypass=strict_first_lift_ok,
        )
        meta["executionChartBlocked"] = blocked
        meta["executionChartReason"] = chart_reason
        meta["padLaneChartBypass"] = pad_lane_ok
        meta["strictFirstLiftBypass"] = strict_first_lift_ok
        if blocked:
            return True, f"execution_chart:{chart_reason}", meta

    from app.engines.capital_allocator import max_lots_for_capital

    prem = _f(alert.get("premium"))
    meta["maxLots"] = max_lots_for_capital(symbol, prem)
    return False, "auto_trader_ok", meta


def _find_alert_at_time(
    date: str,
    target: dict[str, Any],
    *,
    window_minutes: int = 3,
) -> dict[str, Any]:
    from app.engines import explosion_detector, ict_breakout_monitor, session_timing

    batches = sorted(_load_batches(date), key=lambda row: str(row.get("ts") or ""))
    target_dt = _target_dt(date, target["entry"])
    window_start = target_dt - timedelta(minutes=window_minutes)
    window_end = target_dt + timedelta(minutes=window_minutes)
    key = _contract_key(target["symbol"], target["side"], target["strike"])

    reset_detector_state_for_tests()
    state: dict[str, dict[tuple[float, str], dict[str, Any]]] = {}
    spot_hist: dict[str, list[tuple[datetime, float]]] = defaultdict(list)

    original_datetimes = (
        explosion_detector.datetime,
        ict_breakout_monitor.datetime,
        session_timing.datetime,
    )
    original_market_phase = session_timing.get_market_phase

    best: Optional[dict[str, Any]] = None
    best_delta = timedelta(days=1)

    try:
        explosion_detector.datetime = _ReplayDateTime
        ict_breakout_monitor.datetime = _ReplayDateTime
        session_timing.datetime = _ReplayDateTime
        session_timing.get_market_phase = lambda: "LIVE_MARKET"

        for batch in batches:
            ts_raw = batch.get("ts")
            if not ts_raw:
                continue
            ts = datetime.fromisoformat(str(ts_raw))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=IST)
            else:
                ts = ts.astimezone(IST)
            if ts > window_end:
                break
            _ReplayDateTime.current = ts

            sym = target["symbol"]
            contracts = [
                c
                for c in batch.get("contracts") or []
                if str(c.get("symbol") or "").upper() == sym
            ]
            if not contracts:
                continue

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
                    det_key = explosion_detector._open_key(
                        sym, strike_v, Side(side_name),
                    )
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

            if ts < window_start:
                continue

            contract = symbol_state.get(
                (target["strike"], target["side"]), {},
            )
            for alert in snap.explosionAlerts or []:
                if (
                    str(alert.get("side") or "").upper() == target["side"]
                    and _f(alert.get("strike")) == target["strike"]
                ):
                    delta = abs(ts - target_dt)
                    if delta < best_delta:
                        best_delta = delta
                        enriched = _enrich_alert_from_contract(alert, contract)
                        best = {
                            "ts": ts.strftime("%H:%M:%S"),
                            "deltaSec": int(delta.total_seconds()),
                            "alert": enriched,
                            "snap": snap,
                            "contract": contract,
                        }
    finally:
        explosion_detector.datetime = original_datetimes[0]
        ict_breakout_monitor.datetime = original_datetimes[1]
        session_timing.datetime = original_datetimes[2]
        session_timing.get_market_phase = original_market_phase

    return best or {}


def analyze_target(date: str, target: dict[str, Any], settings: Any) -> dict[str, Any]:
    found = _find_alert_at_time(date, target)
    if not found:
        return {
            **target,
            "status": "no_alert_in_window",
            "wouldEnter": False,
        }

    alert = found["alert"]
    snap = found["snap"]
    state = AutoTraderState()
    snapshots = {target["symbol"]: snap}

    replay_ok, replay_reason, moment, ranking = evaluate_local_base_entry(
        alert, snap, settings=settings,
    )
    session_ok, session_reason = evaluate_replay_live_gates(
        alert, snap, snapshots, settings=settings,
    )
    selector_blocked, selector_reason, selector_meta = _selector_blocks(
        target["symbol"], snap, alert, state, settings,
    )
    trader_blocked, trader_reason, trader_meta = _auto_trader_blocks(
        target["symbol"], snap, alert, state, settings,
    )

    blocks = []
    if not replay_ok:
        blocks.append(f"replay:{replay_reason}")
    if not session_ok:
        blocks.append(f"session:{session_reason}")
    if selector_blocked:
        blocks.append(f"selector:{selector_reason}")
    if trader_blocked:
        blocks.append(f"auto_trader:{trader_reason}")

    would_enter = not blocks

    return {
        **target,
        "status": "ok",
        "foundAt": found["ts"],
        "deltaSec": found["deltaSec"],
        "tier": str(alert.get("tier") or ""),
        "premium": round(_f(alert.get("premium")), 1),
        "explosionScore": round(_f(alert.get("explosionScore")), 1),
        "baseRelPct": round(
            _f(alert.get("ictBaseRelativeMovePct") or alert.get("localBaseMovePct")), 1,
        ),
        "offLowPct": round(_f(alert.get("offLowMovePct")), 1),
        "velocity3s": round(_f(alert.get("velocity3s")), 2),
        "replayAllowed": replay_ok,
        "replayReason": replay_reason,
        "moment": moment,
        "grade": ranking.get("grade") if ranking else None,
        "sessionAllowed": session_ok,
        "sessionReason": session_reason,
        "selectorBlocked": selector_blocked,
        "selectorReason": selector_reason,
        "selectorMeta": selector_meta,
        "autoTraderBlocked": trader_blocked,
        "autoTraderReason": trader_reason,
        "autoTraderMeta": trader_meta,
        "blocks": blocks,
        "wouldEnter": would_enter,
        "primaryBlock": blocks[0] if blocks else None,
    }


def main() -> None:
    date = "2026-08-28"
    settings = get_settings()
    results = [analyze_target(date, t, settings) for t in TARGETS]

    from app.engines.eod_local_base_replay import replay_local_base_day
    from app.engines.eod_trade_report import generate_eod_trade_report

    # eod trade report needs zip fallback — use replay instead
    replay_day = replay_local_base_day(date, settings=settings)

    out = {
        "date": date,
        "branch": "cursor/aug28-win-entry-gates-f5cb",
        "liveTradesNote": LIVE_TRADES,
        "eodLocalBaseReplay": {
            "status": replay_day.get("status"),
            "tradeCount": len(replay_day.get("trades") or []),
            "netPnlInr": replay_day.get("netPnlInr"),
            "trades": replay_day.get("trades"),
        },
        "hindsightTargets": results,
    }

    out_path = Path("/opt/cursor/artifacts/aug28_hindsight_gate_analysis.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
