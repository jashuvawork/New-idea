"""EOD local-base replay — full tape + production entry gates at system parameters.

Unlike ``eod_trade_report`` (hardcoded 10–25% off-base pad), this replays the stored
premium tape through the live explosion detector and only enters when:

- ``explosion_alert_is_top_moment`` (FTV / V / ELITE / EXPLODING focus)
- ``first_lift_entry_readiness`` (V-base / armed / elite / building-rip paths)
- ``top_moment_entry_allowed`` (grade + timing)
- ``local_base_entry_window`` (tier-adaptive base-relative move band)
- Live session gates when ``eod_replay_live_session_gates_enabled`` (power hour,
  directional lock with best-side bypass, best-side rank adjustment)

Exits reuse the production explosion exit stack. Portfolio limits (one position at a
time, daily loss stop) match ``eod_trade_report.apply_portfolio_limits``.

Index ``chartAnalysis`` (squeeze, VWAP, GainzAlgo V2 decisive candle) is rebuilt from
the rolling spot tape so coil-breakout prediction matches live detection/ranking.
"""

from __future__ import annotations

import json
import zipfile
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.eod_trade_report import apply_portfolio_limits
from app.engines.local_base_chart_bypass import local_base_entry_window
from app.engines.top_moment_gate import (
    classify_top_moment_type,
    explosion_alert_is_top_moment,
    top_moment_entry_allowed,
)
from app.engines.trade_ranking import rank_trade_evidence
from app.models.schemas import (
    ChartAnalysis,
    HeatmapStrike,
    MarketPhase,
    MarketProfile,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


class _ReplayDateTime(datetime):
    current = datetime.now(IST)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.current.replace(tzinfo=None)
        return cls.current.astimezone(tz)


def _load_batches(date: str) -> list[dict[str, Any]]:
    from app.services.radar_archive import archive_path
    from app.services.radar_learning import premium_tape_path, read_premium_tape

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
            if line:
                rows.append(json.loads(line))
        return rows


def _sample_spot_closes_from_history(
    spot_hist: list[tuple[datetime, float]],
    spot: float,
    *,
    max_points: int = 400,
    min_interval_seconds: float = 15.0,
) -> list[float]:
    """Down-sample rolling tape spot ticks for synthetic OHLC (one point per ~15s)."""
    if spot <= 0:
        return []
    sampled: list[float] = []
    last_ts: Optional[datetime] = None
    for ts, px in spot_hist[-max_points:]:
        if last_ts is None or (ts - last_ts).total_seconds() >= min_interval_seconds:
            sampled.append(px)
            last_ts = ts
    if spot not in sampled:
        sampled.append(spot)
    return sampled


def _spot_chart_from_history(
    spot_hist: list[tuple[datetime, float]],
    spot: float,
) -> SpotChart:
    """Build a spotChart from rolling tape spot samples (5m synthetic candles)."""
    from app.engines.spot_direction import _closes_to_synthetic_candles, build_spot_chart

    if spot <= 0:
        return SpotChart(direction="NEUTRAL", spot=0)
    sampled = _sample_spot_closes_from_history(spot_hist, spot)
    if len(sampled) < 3:
        return SpotChart(direction="NEUTRAL", spot=round(spot, 2))
    candles = _closes_to_synthetic_candles(sampled)
    profile = MarketProfile(
        poc=spot,
        vah=spot * 1.002,
        val=spot * 0.998,
        openingRangeHigh=spot * 1.003,
        openingRangeLow=spot * 0.997,
    )
    return build_spot_chart(candles, spot, profile)


def _chart_analysis_from_spot_history(
    spot_hist: list[tuple[datetime, float]],
    spot: float,
    *,
    symbol: str = "",
) -> Optional[ChartAnalysis]:
    """Build index chartAnalysis (squeeze, VWAP, GainzAlgo V2 decisive candle) for EOD replay."""
    from app.engines.chart_advanced_analysis import build_chart_analysis
    from app.engines.spot_direction import _closes_to_synthetic_candles

    if spot <= 0:
        return None
    sampled = _sample_spot_closes_from_history(spot_hist, spot)
    if len(sampled) < 16:
        return None
    candles_5m = _closes_to_synthetic_candles(sampled)
    profile = MarketProfile(
        poc=spot,
        vah=spot * 1.002,
        val=spot * 0.998,
        openingRangeHigh=spot * 1.003,
        openingRangeLow=spot * 0.997,
    )
    prev_close = sampled[0]
    day_high = max(sampled)
    day_low = min(sampled)
    try:
        return build_chart_analysis(
            [],
            candles_5m,
            spot,
            profile,
            prev_close=prev_close,
            day_high=day_high,
            day_low=day_low,
            symbol=symbol,
        )
    except Exception:
        return None


def _alert_evidence(alert: dict[str, Any], snap: SymbolSnapshot) -> dict[str, Any]:
    return {
        "mode": "explosion",
        "tier": str(alert.get("tier") or "").upper(),
        "explosionScore": _f(alert.get("explosionScore") or alert.get("score")),
        "tqs": _f(getattr(snap, "tradeQualityScore", 0)),
        "flatVerticalQuality": _f(
            alert.get("flatVerticalQuality") or alert.get("ictFlatVerticalQuality")
        ),
        "chartConfidence": 55.0,
        "velocity3s": _f(alert.get("velocity3s")),
        "velocity9s": _f(alert.get("velocity9s")),
        "localBaseMovePct": _f(
            alert.get("localBaseMovePct") or alert.get("ictBaseRelativeMovePct")
        ),
        "offLowMovePct": _f(alert.get("offLowMovePct")),
        "firstLift": bool(alert.get("ictFirstLift")),
        "eliteBaseReady": bool(alert.get("ictEliteBaseReady")),
        "vRipReady": bool(alert.get("ictVRipReady")),
        "buildingRipReady": bool(alert.get("ictBuildingRipReady")),
        "buildingRipHelpersOk": bool(
            alert.get("buildingRipHelpersOk") or alert.get("buildingLiftHelping")
        ),
        "buildingLiftHelping": bool(alert.get("buildingLiftHelping")),
        "armedBaseLaunch": bool(alert.get("ictArmedBaseLaunch")),
        "armedBaseSustainedLift": bool(alert.get("ictArmedBaseSustainedLift")),
        "flatThenVertical": bool(alert.get("ictFlatThenVertical")),
        "activeBreakout": bool(alert.get("ictBreakout")),
        "midRipCoil": bool(alert.get("ictMidRipCoil") or alert.get("midRipCoil")),
        "orderflowPositive": bool(
            alert.get("ictVolumeAwakening")
            or alert.get("volumeAwaken")
            or alert.get("optionCvdBuying")
            or _f(alert.get("volumeSurge")) >= 1.2
        ),
        "indexHelpersConfirm": bool(alert.get("indexHelpersConfirm")),
        "indexConfirmedLocalBase": bool(
            alert.get("indexConfirmedLocalBase")
            or alert.get("ictIndexConfirmedLocalBase")
        ),
        "slowGrindSuddenLift": bool(
            alert.get("slowGrindSuddenLiftReady")
            or alert.get("ictSlowGrindSuddenLift")
        ),
        "fastBullishLocalBase": bool(
            alert.get("fastBullishLocalBaseReady")
            or alert.get("bullishLocalBaseActive")
        ),
        "squeezeRelease": bool(
            alert.get("squeezeReleaseReady") or alert.get("ictSqueezeRelease")
        ),
        "indexLedOptionLag": bool(
            alert.get("indexLedOptionLagReady") or alert.get("ictIndexLedOptionLag")
        ),
        "stealthCvdCoil": bool(
            alert.get("stealthCvdCoilReady") or alert.get("ictStealthCvdCoil")
        ),
        "microPullbackRetest": bool(
            alert.get("microPullbackRetestReady") or alert.get("ictMicroPullbackRetest")
        ),
        "premiumFvgPad": bool(
            alert.get("premiumFvgPadReady") or alert.get("ictPremiumFvgPad")
        ),
        "doubleDipVbase": bool(
            alert.get("doubleDipVbaseReady") or alert.get("ictDoubleDipVbase")
        ),
        "earlyRadarPadCapture": bool(
            alert.get("earlyRadarPadCapture") or alert.get("ictEarlyRadarPadCapture")
        ),
        "buildingCoilPad": bool(
            alert.get("buildingCoilPad") or alert.get("buildingCoilPadReady")
        ),
        "volumeAwaken": bool(
            alert.get("volumeAwaken")
            or alert.get("ictVolumeAwakening")
            or _f(alert.get("volumeSurge")) >= 1.0
        ),
        "volumeSurge": _f(alert.get("volumeSurge")),
        "ictBaseArmed": bool(alert.get("ictBaseArmed")),
        "coldTroughPad": bool(alert.get("coldTroughPad")),
        "timingAssessment": str(alert.get("timingAssessment") or ""),
        "timingAction": str(alert.get("timingAction") or ""),
    }


def _enrich_alert_from_contract(
    alert: dict[str, Any],
    contract: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Merge stored tape fields (volume, velocity, ICT stamps) into a live alert."""
    if not contract:
        return dict(alert)
    merged = {**contract, **alert}
    vol = _f(contract.get("volume"))
    surge = _f(contract.get("volumeSurge"))
    if vol > 0:
        merged["volume"] = vol
        merged["absoluteVolume"] = vol
    if surge > 0:
        merged["volumeSurge"] = surge
    if surge >= 2.0 or vol >= 25_000:
        merged["volumeAwaken"] = True
        merged["ictVolumeAwakening"] = True
    for field in (
        "velocity3s",
        "velocity9s",
        "flatVerticalQuality",
        "explosionScore",
        "tier",
        "tradeable",
        "ictBasePremium",
        "ictBaseRelativeMovePct",
        "localBaseMovePct",
        "offLowMovePct",
    ):
        val = contract.get(field)
        if val is not None and field not in alert:
            merged[field] = val
    return merged


def evaluate_local_base_entry(
    alert: dict[str, Any],
    snap: SymbolSnapshot,
    *,
    settings: Any = None,
    day_mode: str = "",
) -> tuple[bool, str, Optional[str], dict[str, Any]]:
    """Return (allowed, reason, moment_type, ranking) for one radar alert."""
    s = settings or get_settings()
    if not explosion_alert_is_top_moment(alert):
        return False, "not_top_moment_radar", None, {}

    from app.engines.ict_breakout_monitor import first_lift_entry_readiness
    from app.engines.building_ftv_gates import pad_lane_ready_reason
    from app.engines.pad_lane_capture import pad_lane_early_near_miss_waive

    ready, lift_reason = first_lift_entry_readiness(snap=snap, alert=alert)
    pad_lane_waive = pad_lane_early_near_miss_waive(
        alert, readiness_reason=lift_reason, snap=snap,
    )

    evidence = _alert_evidence(alert, snap)
    from app.engines.index_confirmed_local_base import enrich_evidence_index_confirmed

    enrich_evidence_index_confirmed(
        evidence, snap, alert, str(alert.get("side") or ""),
    )
    ranking = rank_trade_evidence(evidence)
    allowed, reason, moment = top_moment_entry_allowed(
        evidence,
        ranking,
        top_moments_only_enabled=bool(getattr(s, "top_moments_only_enabled", True)),
        min_grade=str(getattr(s, "top_moments_min_grade", "A") or "A"),
        day_mode=day_mode,
        readiness_reason=lift_reason if (ready or pad_lane_waive) else "",
    )
    if not allowed:
        return False, reason, moment, ranking

    if not ready and not pad_lane_waive:
        return False, lift_reason, moment, ranking
    if pad_lane_waive:
        lift_reason = pad_lane_ready_reason(
            alert=alert, readiness_reason=lift_reason,
        ) or lift_reason

    from app.engines.early_radar_pad_capture import alert_has_early_radar_pad_capture
    from app.engines.explosion_entry_guards import tier_promotion_pad_chase_blocked

    if not alert_has_early_radar_pad_capture(alert):
        candidate = _candidate_from_alert(alert, snap)
        from app.engines.ict_breakout_monitor import analyze_explosion_event_ict

        ict_ev = analyze_explosion_event_ict(candidate.explosion_event, snap)
        chase_blocked, chase_reason = tier_promotion_pad_chase_blocked(
            candidate.explosion_event,
            ict=ict_ev,
            alert=alert,
        )
        if chase_blocked:
            return False, chase_reason, moment, ranking

    base_rel = _f(alert.get("ictBaseRelativeMovePct") or alert.get("localBaseMovePct"))
    tier = str(alert.get("tier") or "")
    vol = _f(alert.get("volumeSurge"))
    entry_min, chase_max = local_base_entry_window(tier, vol)
    if base_rel > 0 and not (entry_min <= base_rel <= chase_max):
        # Armed/elite/v-rip paths already checked tighter windows inside first_lift.
        if lift_reason not in (
            "v_rip_session_low_ready",
            "elite_base_ready_s_preauthorized",
            "armed_base_option_led_ready",
            "building_local_base_lift_ready",
            "building_rip_bullish_ready",
            "fast_bullish_local_base_ready",
            "slow_grind_sudden_lift_ready",
            "slow_grind_armed_trough_ready",
            "early_radar_pad_ready",
            "squeeze_release_ready",
            "index_led_option_lag_ready",
            "stealth_cvd_coil_ready",
            "micro_pullback_retest_ready",
            "premium_fvg_pad_ready",
            "double_dip_vbase_ready",
            "building_coil_pad_ready",
            "building_armed_prelaunch_ready",
        ):
            return (
                False,
                f"local_base_window_{entry_min:g}_{chase_max:g}",
                moment,
                ranking,
            )

    prem = _f(alert.get("premium"))
    min_prem = _f(getattr(s, "explosion_min_premium_inr", 15.0), 15.0)
    if prem < min_prem:
        return False, f"premium_below_{min_prem:g}", moment, ranking

    return True, lift_reason, moment, ranking


def _install_replay_clock(replay_dt_class: type) -> list[tuple[Any, Any]]:
    """Point power-hour / chop minute helpers at the replay clock."""
    import app.engines.chop_day_guards as chop_guards
    import app.engines.power_hour_guards as power_hour

    def _minutes_from_replay() -> int:
        ts = replay_dt_class.current
        if ts.tzinfo:
            ts = ts.astimezone(IST)
        return ts.hour * 60 + ts.minute

    saved: list[tuple[Any, Any]] = []
    for module in (power_hour, chop_guards):
        saved.append((module, module._minutes_now))
        module._minutes_now = _minutes_from_replay
    return saved


def _restore_replay_clock(saved: list[tuple[Any, Any]]) -> None:
    for module, original in saved:
        module._minutes_now = original


def _candidate_from_alert(
    alert: dict[str, Any],
    snap: SymbolSnapshot,
) -> Any:
    from types import SimpleNamespace

    from app.engines.explosion_detector import ExplosionEvent

    sym = str(snap.symbol or alert.get("symbol") or "").upper()
    side_str = str(alert.get("side") or "").upper()
    side = Side(side_str)
    strike_v = _f(alert.get("strike"))
    prem = _f(alert.get("premium"))
    event = ExplosionEvent(
        symbol=sym,
        side=side,
        strike=strike_v,
        premium=prem,
        velocity_3s=_f(alert.get("velocity3s")),
        velocity_9s=_f(alert.get("velocity9s")),
        velocity_15s=_f(alert.get("velocity15s")),
        volume_surge=_f(alert.get("volumeSurge"), 1.0),
        explosion_score=_f(alert.get("explosionScore")),
        tier=str(alert.get("tier") or ""),
        reason=str(alert.get("reason") or "replay"),
        daily_move_pct=_f(alert.get("dailyMovePct") or alert.get("openPremiumMove")),
        peak_move_pct=_f(alert.get("peakMovePct")),
        volume=_f(alert.get("volume")),
    )
    return SimpleNamespace(
        symbol=sym,
        side=side,
        strike=strike_v,
        premium=prem,
        snap=snap,
        mode="explosion",
        tier=event.tier,
        score=event.explosion_score,
        explosion_event=event,
        alert=alert,
    )


def evaluate_replay_live_gates(
    alert: dict[str, Any],
    snap: SymbolSnapshot,
    snapshots: dict[str, SymbolSnapshot],
    *,
    settings: Any = None,
    skip_session_gate: bool = False,
) -> tuple[bool, str]:
    """Production session gates: power hour + directional lock (+ best-side bypass)."""
    s = settings or get_settings()
    if not bool(getattr(s, "eod_replay_live_session_gates_enabled", True)):
        return True, "ok"

    from app.engines.directional_lock import check_directional_side_lock
    from app.engines.power_hour_guards import (
        candidate_qualifies_power_hour_top_trade,
        check_power_hour_session_allowed,
        in_power_hour_window,
    )
    from app.models.schemas import AutoTraderState

    candidate = _candidate_from_alert(alert, snap)

    if in_power_hour_window():
        if not skip_session_gate:
            session_ok, session_reason, _ = check_power_hour_session_allowed(
                AutoTraderState(),
                snapshots,
            )
            if not session_ok:
                return False, session_reason
        if not candidate_qualifies_power_hour_top_trade(candidate):
            return False, "power_hour_top_only"

    blocked, dir_reason = check_directional_side_lock(
        snap.symbol,
        candidate.side,
        snap,
        tier=candidate.tier,
        candidate=candidate,
    )
    if blocked:
        return False, dir_reason

    return True, "ok"


def _replay_selection_rank(
    ranking: dict[str, Any],
    alert: dict[str, Any],
    snap: SymbolSnapshot,
    snapshots: dict[str, SymbolSnapshot],
    *,
    settings: Any = None,
    lift_reason: str = "",
) -> float:
    score = _f(ranking.get("rankScore"))
    s = settings or get_settings()
    reason = str(
        lift_reason
        or alert.get("ictBaseReadinessReason")
        or alert.get("readyReason")
        or ""
    )
    pad_lane_reasons = {
        "armed_base_option_led_ready",
        "building_coil_pad_ready",
        "building_armed_prelaunch_ready",
        "slow_grind_sudden_lift_ready",
        "early_radar_pad_ready",
        "v_rip_session_low_ready",
    }
    if reason in pad_lane_reasons or bool(
        alert.get("buildingCoilPad") or alert.get("earlyRadarPadCapture")
    ):
        score += float(getattr(s, "pad_lane_selector_rank_bonus", 18.0) or 18.0)
    if reason in {
        "armed_base_option_led_ready",
        "building_coil_pad_ready",
        "building_armed_prelaunch_ready",
    }:
        score += float(
            getattr(s, "ftv_direct_trade_selector_rank_bonus", 55.0) or 55.0
        ) * 0.5
    if bool(getattr(s, "expansion_strike_rank_bonus_enabled", True)) and (
        alert.get("buildingCoilPad") or reason == "building_coil_pad_ready"
    ):
        score += float(getattr(s, "expansion_strike_rank_bonus", 15.0) or 15.0)
    if reason == "early_radar_pad_ready":
        score -= float(getattr(s, "eod_replay_early_pad_rank_penalty", 12.0) or 12.0)
    from app.engines.coil_breakout_predictor import coil_prediction_rank_delta
    from app.models.schemas import Side as SideEnum

    side_raw = str(alert.get("side") or "").upper()
    side_enum = SideEnum.CALL if side_raw == "CALL" else SideEnum.PUT if side_raw == "PUT" else None
    if side_enum is not None:
        score += coil_prediction_rank_delta(alert, side_enum)
    if bool(getattr(s, "eod_replay_live_session_gates_enabled", True)):
        from app.engines.best_side_selection import (
            best_side_rank_adjustment,
            resolve_global_best_side,
        )
        from app.engines.power_hour_guards import in_power_hour_window

        score += best_side_rank_adjustment(
            _candidate_from_alert(alert, snap),
            snapshots,
            power_hour=in_power_hour_window(),
        )
        global_sym, global_side, _, _ = resolve_global_best_side(
            snapshots,
            power_hour=in_power_hour_window(),
        )
        side_val = str(alert.get("side") or "").upper()
        sym_u = str(snap.symbol or alert.get("symbol") or "").upper()
        if (
            global_side
            and global_side != side_val
            and sym_u == (global_sym or sym_u)
        ):
            score -= float(
                getattr(s, "eod_replay_counter_side_rank_penalty", 35.0) or 35.0
            )
    return score


def _contract_key(symbol: str, side: str, strike: float) -> str:
    return f"{symbol.upper()}:{side.upper()}:{strike:g}"


def _simulate_trade_from_entry(
    *,
    symbol: str,
    side: str,
    strike: float,
    tier: str,
    entry_ts: datetime,
    entry_premium: float,
    base_premium: float,
    forward: list[tuple[datetime, float]],
    settings: Any,
    entry_ctx: dict[str, Any],
) -> dict[str, Any]:
    """Walk forward on premium tape from entry until production exit fires."""
    from app.engines.capital_allocator import lot_multiplier, max_lots_for_capital
    from app.engines.explosion_profit import evaluate_explosion_exit
    from app.engines.moment_stage_trail import build_moment_stage_plan
    from app.models.schemas import PaperTrade, Side as SideEnum, StrategyType

    s = settings
    units = int(lot_multiplier(symbol) or 20)
    ep = entry_premium
    base = base_premium or ep
    lots = max(1, max_lots_for_capital(symbol, ep))
    min_sl_pts = _f(getattr(s, "elite_full_lot_min_stop_points", 16.0), 16.0)
    min_sl_pct = _f(getattr(s, "elite_full_lot_min_stop_pct_of_premium", 0.18), 0.18)
    stop_pts = max(min_sl_pts, ep * max(0.0, min_sl_pct))
    off = (ep - base) / base * 100.0 if base > 0 else 0.0

    plan = build_moment_stage_plan(
        entry_premium=ep,
        base_premium=base,
        velocity_3s=_f(entry_ctx.get("velocity3s"), 3.0),
        volume_surge=_f(entry_ctx.get("volumeSurge"), 2.5),
        session_move_pct=30.0,
        flat_then_vertical=bool(entry_ctx.get("ictFlatThenVertical")),
        max_profit=True,
    )
    ctx = {
        **entry_ctx,
        "momentType": entry_ctx.get("momentType") or "flat_then_vertical",
        "ictFlatThenVertical": bool(entry_ctx.get("ictFlatThenVertical")),
        "maxProfitCapture": True,
        "ictBasePremium": base,
        "eliteFullLot": True,
        "vBaseFtvRunner": True,
        "localBaseBaseRelPct": round(off, 2),
        "exitPlan": {
            "stopPoints": round(stop_pts, 2),
            "entryStopPoints": round(stop_pts, 2),
            "targetPoints": 180.0,
        },
    }
    if plan:
        ctx.update(plan)

    wnow = datetime.now(IST)
    tr = PaperTrade(
        id=f"{symbol}:{side}:{strike}",
        symbol=symbol,
        side=SideEnum(side),
        strike=strike,
        entryPremium=ep,
        currentPremium=ep,
        lots=lots,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=wnow,
        bestPnlPoints=0.0,
        entryContext=ctx,
    )
    best = 0.0
    peak = ep
    exit_rec: Optional[tuple[datetime, float, str]] = None
    for tj, pj in forward:
        if pj <= 0:
            continue
        tr.openedAt = wnow - timedelta(seconds=(tj - entry_ts).total_seconds())
        tr.currentPremium = pj
        best = max(best, pj - ep)
        tr.bestPnlPoints = best
        peak = max(peak, pj)
        v = 2.0 if pj >= peak else -0.8
        tr.entryContext["liveVelocity3s"] = v
        reason, _pnl = evaluate_explosion_exit(tr, pj, tier, units, live_velocity_3s=v)
        if reason:
            exit_rec = (tj, pj, reason)
            break
    if exit_rec is None and forward:
        exit_rec = (forward[-1][0], forward[-1][1], "eod_close")
    if exit_rec is None:
        exit_rec = (entry_ts, ep, "no_forward_tape")
    xt, xp, reason = exit_rec
    pnl = (xp - ep) * lots * units
    return {
        "symbol": symbol,
        "side": side,
        "strike": strike,
        "tier": tier,
        "momentType": entry_ctx.get("topMomentType"),
        "entryReason": entry_ctx.get("entryReason"),
        "entryAt": entry_ts.strftime("%H:%M:%S"),
        "entryPremium": round(ep, 1),
        "basePremium": round(base, 1),
        "offBasePct": round(off, 1),
        "lots": lots,
        "stopPoints": round(stop_pts, 2),
        "slPremium": round(ep - stop_pts, 2),
        "notionalInr": round(ep * lots * units, 0),
        "exitAt": xt.strftime("%H:%M:%S"),
        "exitPremium": round(xp, 1),
        "movePct": round((xp - ep) / ep * 100, 1) if ep > 0 else 0.0,
        "peakPct": round(best / ep * 100, 1) if ep > 0 else 0.0,
        "pnlInr": round(pnl, 0),
        "exitReason": reason,
        "grade": entry_ctx.get("grade"),
        "_entryDt": entry_ts,
        "_exitDt": xt,
    }


def _parse_window_bound(
    date: str,
    hhmmss: Optional[str],
    *,
    end_of_day: bool = False,
) -> Optional[datetime]:
    if not hhmmss:
        return None
    raw = str(hhmmss).strip()
    parts = raw.split(":")
    if len(parts) < 2:
        raise ValueError("window time must be HH:MM or HH:MM:SS")
    hour = int(parts[0])
    minute = int(parts[1])
    second = int(float(parts[2])) if len(parts) > 2 else (59 if end_of_day else 0)
    day = datetime.strptime(date, "%Y-%m-%d").date()
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=IST)


def replay_local_base_day(
    date: str,
    *,
    settings: Any = None,
    max_trades_per_contract: int = 3,
    entry_cooldown_seconds: float = 90.0,
    window_start: Optional[str] = None,
    window_end: Optional[str] = None,
    side_filter: Optional[str] = None,
) -> dict[str, Any]:
    """Replay one session's premium tape with production local-base entry gates."""
    from app.engines import explosion_detector, ict_breakout_monitor, session_timing
    from app.engines.explosion_detector import (
        refresh_snapshot_explosion_alerts,
        reset_detector_state_for_tests,
    )

    s = settings or get_settings()
    batches = sorted(_load_batches(date), key=lambda row: str(row.get("ts") or ""))
    if not batches:
        return {
            "date": date,
            "status": "no_tape",
            "trades": [],
            "gateStats": {},
        }

    win_start = _parse_window_bound(date, window_start)
    win_end = _parse_window_bound(date, window_end, end_of_day=True)
    side_filter_v = str(side_filter or "").upper() or None
    if side_filter_v and side_filter_v not in {"CALL", "PUT"}:
        raise ValueError("side_filter must be CALL or PUT")

    # Pre-index the full premium tape so exit simulation can walk forward from entry.
    premium_series: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for batch in batches:
        ts_raw = batch.get("ts")
        if not ts_raw:
            continue
        try:
            ts = datetime.fromisoformat(str(ts_raw))
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=IST)
        else:
            ts = ts.astimezone(IST)
        for contract in batch.get("contracts") or []:
            sym = str(contract.get("symbol") or "").upper()
            side = str(contract.get("side") or "").upper()
            strike_v = _f(contract.get("strike"))
            prem = _f(contract.get("premium"))
            if sym and side in {"CALL", "PUT"} and strike_v > 0 and prem > 0:
                premium_series[_contract_key(sym, side, strike_v)].append((ts, prem))

    reset_detector_state_for_tests()
    from app.engines.directional_lock import record_trade_side, reset_directional_lock

    reset_directional_lock()
    original_datetimes = (
        explosion_detector.datetime,
        ict_breakout_monitor.datetime,
        session_timing.datetime,
    )
    original_market_phase = session_timing.get_market_phase
    replay_clock_saved: list[tuple[Any, Any]] = []

    state: dict[str, dict[tuple[float, str], dict[str, Any]]] = {}
    spot_hist: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    gate_stats: dict[str, int] = defaultdict(int)
    signal_rows: list[dict[str, Any]] = []
    raw_candidates: list[dict[str, Any]] = []

    cooldown_until: dict[str, datetime] = {}
    trades_per_key: dict[str, int] = defaultdict(int)
    next_ok_after: Optional[datetime] = None

    try:
        explosion_detector.datetime = _ReplayDateTime
        ict_breakout_monitor.datetime = _ReplayDateTime
        session_timing.datetime = _ReplayDateTime
        session_timing.get_market_phase = lambda: "LIVE_MARKET"
        replay_clock_saved = _install_replay_clock(_ReplayDateTime)

        live_gates = bool(getattr(s, "eod_replay_live_session_gates_enabled", True))

        for batch in batches:
            ts_raw = batch.get("ts")
            if not ts_raw:
                continue
            try:
                ts = datetime.fromisoformat(str(ts_raw))
            except ValueError:
                continue
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

            batch_snapshots: dict[str, SymbolSnapshot] = {}
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
                        det_key = explosion_detector._open_key(
                            sym, strike_v, Side(side_name)
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
                chart_analysis = _chart_analysis_from_spot_history(
                    spot_hist[sym], spot, symbol=sym,
                )
                snap = SymbolSnapshot(
                    symbol=sym,
                    timestamp=ts,
                    marketPhase=MarketPhase.LIVE_MARKET,
                    dataAvailable=True,
                    spot=spot,
                    atmStrike=_f(sample.get("atmStrike")),
                    heatmap=heatmap,
                    spotChart=chart,
                    chartAnalysis=chart_analysis,
                    tradeQualityScore=55.0,
                )
                refresh_snapshot_explosion_alerts(snap)
                batch_snapshots[sym] = snap

            if not batch_snapshots:
                continue

            if next_ok_after is not None and ts < next_ok_after:
                continue

            if win_start is not None and ts < win_start:
                continue
            if win_end is not None and ts > win_end:
                continue

            session_gate_blocked = False
            if live_gates:
                from app.engines.power_hour_guards import (
                    check_power_hour_session_allowed,
                    in_power_hour_window,
                )
                from app.models.schemas import AutoTraderState

                if in_power_hour_window():
                    session_ok, session_reason, _ = check_power_hour_session_allowed(
                        AutoTraderState(),
                        batch_snapshots,
                    )
                    if not session_ok:
                        gate_stats[session_reason] += 1
                        session_gate_blocked = True

            if session_gate_blocked:
                continue

            ranked_candidates: list[tuple[float, str, SymbolSnapshot, dict[str, Any], str, Optional[str], dict[str, Any]]] = []
            for sym, snap in batch_snapshots.items():
                symbol_state = state[sym]
                for alert in snap.explosionAlerts or []:
                    strike_v = _f(alert.get("strike"))
                    side = str(alert.get("side") or "").upper()
                    if strike_v <= 0 or side not in {"CALL", "PUT"}:
                        continue
                    if side_filter_v and side != side_filter_v:
                        continue
                    key = _contract_key(sym, side, strike_v)
                    if trades_per_key[key] >= max_trades_per_contract:
                        gate_stats["max_trades_per_contract"] += 1
                        continue
                    cd = cooldown_until.get(key)
                    if cd is not None and ts < cd:
                        gate_stats["contract_cooldown"] += 1
                        continue

                    contract = symbol_state.get((strike_v, side))
                    alert_eval = _enrich_alert_from_contract(alert, contract)

                    allowed, reason, moment, ranking = evaluate_local_base_entry(
                        alert_eval, snap, settings=s,
                    )
                    if not allowed:
                        gate_stats[reason] += 1
                        if len(signal_rows) < 500:
                            signal_rows.append({
                                "ts": ts.isoformat(),
                                "key": key,
                                "tier": alert.get("tier"),
                                "premium": alert.get("premium"),
                                "baseRelPct": alert.get("ictBaseRelativeMovePct"),
                                "allowed": False,
                                "reason": reason,
                            })
                        continue

                    gate_stats["entry_allowed"] += 1
                    if live_gates:
                        live_ok, live_reason = evaluate_replay_live_gates(
                            alert_eval,
                            snap,
                            batch_snapshots,
                            settings=s,
                            skip_session_gate=True,
                        )
                        if not live_ok:
                            gate_stats[live_reason] += 1
                            if len(signal_rows) < 500:
                                signal_rows.append({
                                    "ts": ts.isoformat(),
                                    "key": key,
                                    "tier": alert.get("tier"),
                                    "premium": alert.get("premium"),
                                    "baseRelPct": alert.get("ictBaseRelativeMovePct"),
                                    "allowed": False,
                                    "reason": live_reason,
                                })
                            continue

                    rank_score = _replay_selection_rank(
                        ranking,
                        alert_eval,
                        snap,
                        batch_snapshots,
                        settings=s,
                        lift_reason=reason,
                    )
                    ranked_candidates.append(
                        (rank_score, sym, snap, alert_eval, key, moment, ranking),
                    )

            if not ranked_candidates:
                continue

            ranked_candidates.sort(key=lambda row: row[0], reverse=True)
            _, sym, snap, alert, key, moment, ranking = ranked_candidates[0]
            strike_v = _f(alert.get("strike"))
            side = str(alert.get("side") or "").upper()
            tier = str(alert.get("tier") or "").upper()
            ep = _f(alert.get("premium"))
            base = _f(alert.get("ictBasePremium") or alert.get("basePremium"))
            if base <= 0:
                hist = [
                    p for t, p in premium_series.get(key, [])
                    if (ts - t).total_seconds() <= 1200 and p > 0
                ]
                base = min(hist) if hist else ep

            _, entry_reason, moment, ranking = evaluate_local_base_entry(
                alert, snap, settings=s,
            )
            forward = [
                (t, p)
                for t, p in premium_series.get(key, [])
                if t >= ts
            ]
            entry_ctx = {
                "topMomentType": moment,
                "entryReason": entry_reason,
                "grade": ranking.get("grade"),
                "explosionTier": tier,
                "velocity3s": alert.get("velocity3s"),
                "volumeSurge": alert.get("volumeSurge"),
                "ictFlatThenVertical": alert.get("ictFlatThenVertical"),
                "ictFirstLift": alert.get("ictFirstLift"),
                "ictArmedBaseLaunch": alert.get("ictArmedBaseLaunch"),
                "ictEliteBaseReady": alert.get("ictEliteBaseReady"),
                "ictVRipReady": alert.get("ictVRipReady"),
                "momentType": classify_top_moment_type(_alert_evidence(alert, snap)),
            }
            trade = _simulate_trade_from_entry(
                symbol=sym,
                side=side,
                strike=strike_v,
                tier=tier,
                entry_ts=ts,
                entry_premium=ep,
                base_premium=base,
                forward=forward,
                settings=s,
                entry_ctx=entry_ctx,
            )
            raw_candidates.append(trade)
            trades_per_key[key] += 1
            record_trade_side(sym, Side(side), snap)
            cooldown_until[key] = trade["_exitDt"] + timedelta(
                seconds=entry_cooldown_seconds
            )
            next_ok_after = trade["_exitDt"] + timedelta(
                seconds=entry_cooldown_seconds
            )
            if len(signal_rows) < 500:
                signal_rows.append({
                    "ts": ts.isoformat(),
                    "key": key,
                    "tier": tier,
                    "premium": ep,
                    "baseRelPct": alert.get("ictBaseRelativeMovePct"),
                    "allowed": True,
                    "reason": entry_reason,
                    "momentType": moment,
                    "grade": ranking.get("grade"),
                })

    finally:
        (
            explosion_detector.datetime,
            ict_breakout_monitor.datetime,
            session_timing.datetime,
        ) = original_datetimes
        session_timing.get_market_phase = original_market_phase
        if replay_clock_saved:
            _restore_replay_clock(replay_clock_saved)
        reset_detector_state_for_tests()

    taken = apply_portfolio_limits(raw_candidates, settings=s)
    for t in taken:
        t.pop("_entryDt", None)
        t.pop("_exitDt", None)

    total = round(sum(_f(t.get("pnlInr")) for t in taken), 0)
    wins = sum(1 for t in taken if _f(t.get("pnlInr")) > 0)
    daily_stop = _f(getattr(s, "daily_loss_stop_inr", 20_000.0), 20_000.0)

    mode = "local_base_system_params"
    if win_start or win_end or side_filter_v:
        mode = "window_replay"
    return {
        "date": date,
        "status": "ok",
        "mode": mode,
        "windowStart": win_start.isoformat() if win_start else None,
        "windowEnd": win_end.isoformat() if win_end else None,
        "sideFilter": side_filter_v,
        "sampleBatches": len(batches),
        "tradeCount": len(taken),
        "candidateCount": len(raw_candidates),
        "wins": wins,
        "losses": len(taken) - wins,
        "netPnlInr": total,
        "dailyLossStopInr": daily_stop,
        "gateStats": dict(sorted(gate_stats.items(), key=lambda kv: -kv[1])),
        "signals": signal_rows[:100],
        "note": (
            "Full-tape replay with production top-moment + first-lift + "
            "local-base window gates + live session gates (power hour, "
            "directional lock, best-side rank). One position at a time + "
            "daily loss stop."
        ),
        "trades": taken,
    }


def generate_lever_replay_compare(
    date: str,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    side: Optional[str] = None,
) -> dict[str, Any]:
    """Run premium-tape replay twice — levers OFF vs ON (Sep2 afternoon miss analysis)."""
    from copy import deepcopy

    from app.config import Settings

    base = get_settings()
    off_data = deepcopy(base.model_dump())
    off_data["top_moments_exploding_elite_grade_b_enabled"] = False
    off_data["top_moments_momentum_rally_grade_b_enabled"] = False
    off_data["top_moments_day_type_grade_policy_enabled"] = False
    off_data["top_moments_fast_day_grade_c_enabled"] = False
    off_data["index_rally_side_flip_neutral_macd_mom5_waiver_enabled"] = False
    off_settings = Settings(**off_data)

    on_data = deepcopy(base.model_dump())
    on_data["top_moments_exploding_elite_grade_b_enabled"] = True
    on_data["top_moments_momentum_rally_grade_b_enabled"] = True
    on_data["index_rally_side_flip_neutral_macd_mom5_waiver_enabled"] = True
    on_settings = Settings(**on_data)

    kwargs = {
        "window_start": start,
        "window_end": end,
        "side_filter": side,
    }
    off = replay_local_base_day(date, settings=off_settings, **kwargs)
    on = replay_local_base_day(date, settings=on_settings, **kwargs)

    def _trade_key(row: dict[str, Any]) -> str:
        return "|".join(
            [
                str(row.get("entryAt") or ""),
                str(row.get("symbol") or ""),
                str(row.get("side") or ""),
                str(row.get("strike") or ""),
            ]
        )

    off_trades = list(off.get("trades") or [])
    on_trades = list(on.get("trades") or [])
    off_keys = {_trade_key(t) for t in off_trades}
    unlocked = [t for t in on_trades if _trade_key(t) not in off_keys]

    return {
        "date": date,
        "window": {"start": start, "end": end, "side": side},
        "leversOff": off,
        "leversOn": on,
        "delta": {
            "tradeCount": int(on.get("tradeCount") or len(on_trades))
            - int(off.get("tradeCount") or len(off_trades)),
            "netPnlInr": round(
                float(on.get("netPnlInr") or 0) - float(off.get("netPnlInr") or 0),
                0,
            ),
        },
        "tradesUnlockedByLevers": unlocked,
        "note": (
            "OFF disables grade-B EXPLODING pad waiver, MOMENTUM RALLY grade loosening, "
            "and NEUTRAL MACD+mom5 index side-flip waiver."
        ),
    }


def generate_window_replay(
    date: str,
    *,
    start: str,
    end: str,
    side: Optional[str] = None,
) -> dict[str, Any]:
    """Replay a premium-tape window with production entry/exit gates."""
    report = replay_local_base_day(
        date,
        window_start=start,
        window_end=end,
        side_filter=side,
    )
    if report.get("status") != "ok":
        return report
    report["note"] = (
        f"Premium-tape replay {start}–{end} IST"
        + (f" ({side} only)" if side else "")
        + " with production gates + exit stack."
    )
    return report


def generate_eod_local_base_replay(date: str) -> dict[str, Any]:
    """Run local-base replay and attach a quick comparison vs simplified EOD report."""
    report = replay_local_base_day(date)
    if report.get("status") != "ok":
        return report

    try:
        from app.engines.eod_trade_report import generate_eod_trade_report

        legacy = generate_eod_trade_report(date)
        report["comparison"] = {
            "legacyEodReport": {
                "tradeCount": legacy.get("tradeCount"),
                "netPnlInr": legacy.get("netPnlInr"),
                "note": legacy.get("note"),
            },
            "deltaPnlInr": round(
                _f(report.get("netPnlInr")) - _f(legacy.get("netPnlInr")),
                0,
            ),
        }
    except Exception:
        report["comparison"] = None

    return report


def generate_eod_local_base_replay_week(
    start_date: str,
    *,
    days: int = 5,
) -> dict[str, Any]:
    """Roll up local-base replays across a validation week (default Mon–Fri)."""
    from datetime import datetime as dt

    start = dt.strptime(start_date, "%Y-%m-%d")
    day_rows: list[dict[str, Any]] = []
    for offset in range(days):
        date = (start + timedelta(days=offset)).strftime("%Y-%m-%d")
        if date.weekday() >= 5:
            continue
        day_rows.append(generate_eod_local_base_replay(date))

    taken = [r for r in day_rows if r.get("status") == "ok"]
    return {
        "startDate": start_date,
        "days": days,
        "sessions": len(day_rows),
        "tradeCount": sum(int(r.get("tradeCount") or 0) for r in taken),
        "netPnlInr": round(sum(_f(r.get("netPnlInr")) for r in taken), 0),
        "wins": sum(int(r.get("wins") or 0) for r in taken),
        "losses": sum(int(r.get("losses") or 0) for r in taken),
        "daily": day_rows,
    }
