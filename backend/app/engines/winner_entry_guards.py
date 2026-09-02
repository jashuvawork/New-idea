"""Entry guards biased toward winners — block fading rips and loss-streak churn."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.engines.edge_engine import session_pf_feedback
from app.engines.pretrade_validator import analyze_last_n_trades, collect_session_trades
from app.models.schemas import AutoTraderState, SymbolSnapshot


def premium_fading_blocks_entry(
    *,
    trade_score: float = 0.0,
    premium_momentum_3s: float = 0.0,
    premium_momentum_5s: float = 0.0,
    premium_direction: str = "",
    explosion_event: Any = None,
    confirmed_ftv_bypass: bool = False,
    pad_lane_bypass: bool = False,
) -> tuple[bool, str]:
    """
    Block entries when option premium is fading at execution.
    High explosion score does NOT bypass — score measures radar, not live fill timing.

    Exception: a CONFIRMED near-base FTV first-lift (``confirmed_ftv_bypass``) may fill
    through a *shallow* dip — that dip is the base retest right before the vertical, so
    blocking it means chasing the move after it lifts instead of taking it at the base. The
    bypass is bounded: only shallow dips (shallower than the configured floor) pass; a deeper
    collapse still blocks, and only ELITE/EXPLODING events qualify.
    """
    settings = get_settings()
    if not settings.execution_chart_premium_check_enabled:
        return False, "ok"

    daily_move = 0.0
    tier = ""
    if explosion_event is not None:
        daily_move = float(getattr(explosion_event, "daily_move_pct", 0) or 0)
        tier = str(getattr(explosion_event, "tier", "") or "").upper()

    # Only extreme session rips may enter on briefly fading premium
    if tier == "ELITE" and daily_move >= settings.all_day_explosion_extreme_move_min_pct:
        return False, "ok"

    # Confirmed near-base FTV first-lift: let a SHALLOW base-retest dip fill so we take it AT
    # the base. A deeper collapse (below the floor) is a real fade and still blocks.
    if (
        confirmed_ftv_bypass
        and bool(getattr(settings, "ftv_premium_fade_fill_enabled", True))
        and tier in ("ELITE", "EXPLODING")
    ):
        shallow_floor = float(
            getattr(settings, "ftv_premium_fade_fill_max_drawdown_pct", -0.6) or -0.6
        )
        if premium_momentum_5s >= shallow_floor and premium_momentum_3s >= shallow_floor:
            return False, "ftv_shallow_fade_ok"

    # Pad-lane local-base retest — cold/flat velocity before the vertical is normal.
    if (
        pad_lane_bypass
        and bool(getattr(settings, "pad_lane_premium_fade_fill_enabled", True))
        and tier in ("ELITE", "EXPLODING", "BUILDING", "WATCH")
    ):
        shallow_floor = float(
            getattr(settings, "pad_lane_premium_fade_fill_max_drawdown_pct", -1.2)
            or -1.2
        )
        if premium_momentum_5s >= shallow_floor and premium_momentum_3s >= shallow_floor:
            return False, "pad_lane_shallow_fade_ok"

    min_mom = settings.execution_chart_min_premium_momentum_pct
    if premium_momentum_5s < min_mom and premium_momentum_3s < 0:
        return True, "premium_fading_at_execution"
    if premium_direction.upper() == "BEARISH" and premium_momentum_5s < -0.12:
        return True, "premium_chart_fading"
    if trade_score >= 90 and premium_momentum_3s < -0.25:
        return True, "premium_fading_high_score"
    return False, "ok"


def chop_weak_explosion_blocks_entry(
    candidate: Any,
    snap: SymbolSnapshot,
) -> tuple[bool, str]:
    """
    CHOP / RANGE_BOUND — require a real session premium rip.

    Jul20: rank-score bypass let EXPLODING entries through at +0.8%/+1.4% move.
    Use event explosion_score + session move — never candidate rank.
    """
    settings = get_settings()
    if getattr(candidate, "mode", "") != "explosion":
        return False, "ok"

    regime = str(snap.regime.value if hasattr(snap.regime, "value") else snap.regime or "").upper()
    # Also treat day-mode chop via breadth-neutral sessions when regime lags.
    chart = snap.spotChart
    chopish = regime in ("CHOP", "RANGE_BOUND")
    if not chopish and chart is not None:
        mom = abs(float(getattr(chart, "momentum5Pct", 0) or 0))
        strength = float(getattr(chart, "trendStrength", 100) or 100)
        if mom < 0.25 and strength < 45:
            chopish = True
    if not chopish:
        return False, "ok"

    event = getattr(candidate, "explosion_event", None)
    alert = getattr(candidate, "alert", None) or {}
    daily_move = float(getattr(event, "daily_move_pct", 0) or 0) if event else 0.0
    peak_move = float(getattr(event, "peak_move_pct", 0) or 0) if event else 0.0
    move = max(daily_move, peak_move)
    tier = str(
        getattr(event, "tier", "")
        or alert.get("tier")
        or getattr(candidate, "tier", "")
        or ""
    ).upper()
    exp_score = float(getattr(event, "explosion_score", 0) or 0) if event else 0.0

    ict_flat = bool(alert.get("ictFlatThenVertical"))
    ict_vol = bool(alert.get("volumeAwaken") or alert.get("ictVolumeAwakening"))
    if event is not None and not ict_flat:
        from app.engines.ict_breakout_monitor import analyze_explosion_event_ict

        ict = analyze_explosion_event_ict(event, snap)
        ict_flat = bool(ict.flat_then_vertical and ict.active)
        ict_vol = ict_vol or bool(ict.volume_awakening)
        move = max(move, float(ict.session_move_pct or 0))

    # A range-bound index is exactly where a coiled option base can launch. Admit
    # only the strict first-lift proof; generic low-move explosions remain blocked.
    from app.engines.ict_breakout_monitor import first_lift_entry_readiness

    first_lift_ready, readiness_reason = first_lift_entry_readiness(
        snap=snap,
        event=event,
        alert=alert,
    )
    from app.engines.early_radar_pad_capture import EARLY_RADAR_PAD_READY
    from app.engines.pad_lane_capture import pad_lane_early_near_miss_waive

    waive = pad_lane_early_near_miss_waive(
        alert, readiness_reason=readiness_reason, snap=snap,
    )
    early_pad_chop_bypass = (
        readiness_reason == EARLY_RADAR_PAD_READY
        and tier in ("WATCH", "BUILDING")
        and (first_lift_ready or waive)
    )
    if early_pad_chop_bypass or (
        readiness_reason != EARLY_RADAR_PAD_READY
        and (first_lift_ready or waive)
    ):
        return False, "first_lift_local_base_confirmed"

    chop_min = float(
        getattr(settings, "explosion_chop_min_session_move_pct", 28.0) or 28.0
    )
    early_min = float(
        getattr(settings, "ict_early_vertical_min_session_move_pct", 28.0) or 28.0
    )

    # Open-gap ELITE (Jul29 77500 CE / 24200 CE) — never die as chop_immature pre-10.
    from app.engines.open_gap_capture import open_gap_chop_bypass

    if open_gap_chop_bypass(candidate, snap):
        return False, "ok"

    # True flat→vertical with volume at early floor — allow on chop.
    if ict_flat and ict_vol and move >= early_min:
        return False, "ok"

    if move < chop_min:
        return True, f"chop_immature_explosion_{move:.1f}%"

    # Proven rip on chop: ELITE/EXPLODING with session move ≥ all-day floor.
    if tier in ("ELITE", "EXPLODING") and move >= settings.all_day_explosion_session_move_min_pct:
        return False, "ok"

    # Extreme radar score still needs meaningful move (no rank bypass).
    if exp_score >= settings.aggressive_min_explosion_score + 40 and move >= chop_min + 10:
        return False, "ok"

    return True, "chop_weak_explosion"


def session_winner_gate(
    candidate: Any,
    state: AutoTraderState,
) -> tuple[bool, str, dict[str, Any]]:
    """
    After a losing session, only take high-edge setups — stop churning losers.
    """
    settings = get_settings()
    if not settings.controlled_trading_enabled:
        return True, "ok", {}

    trades = collect_session_trades(state)
    if len(trades) < 3:
        return True, "ok", {}

    summary = analyze_last_n_trades(trades, min(len(trades), settings.last_n_trades_lookback))
    losses = int(summary.get("losses") or 0)
    pf = float(summary.get("profitFactor") or 0)
    meta = {"sessionPf": round(pf, 2), "sessionLosses": losses}

    if losses < settings.last_n_elevate_after_losses:
        return True, "ok", meta

    edge_total = 0.0
    if getattr(candidate, "pretrade_meta", None):
        edge_total = float((candidate.pretrade_meta or {}).get("edgeTotal") or 0)

    fb = session_pf_feedback(state)
    min_edge = settings.edge_min_score_for_entry
    if pf < settings.edge_session_pf_tighten_below:
        min_edge = max(min_edge, settings.daily_18pct_high_confidence_min)
    if pf < 1.0 and losses >= settings.last_n_pause_after_losses:
        min_edge = max(min_edge, settings.daily_18pct_elite_confidence_min)

    if edge_total > 0 and edge_total < min_edge:
        return False, f"session_winner_gate_edge_{edge_total:.0f}<{min_edge:.0f}", meta

    min_score = settings.pretrade_min_rank_score
    if pf < 1.0 and losses >= settings.last_n_elevate_after_losses:
        min_score = max(min_score, settings.last_n_elevated_min_rank_score)
    cand_score = float(getattr(candidate, "score", 0) or 0)
    if cand_score < min_score and getattr(candidate, "mode", "") == "explosion":
        event = getattr(candidate, "explosion_event", None)
        daily_move = float(getattr(event, "daily_move_pct", 0) or 0) if event else 0.0
        if daily_move < settings.all_day_explosion_session_move_min_pct:
            return False, f"session_winner_gate_score_{cand_score:.0f}<{min_score:.0f}", meta

    return True, "ok", meta
