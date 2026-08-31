"""Live best-trades-only gate — strict quality bar for real-money entries."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import get_settings
from app.models.schemas import AutoTraderState, Side, SymbolSnapshot


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def _live_trade(trade: Any) -> bool:
    ctx = getattr(trade, "entryContext", None) or {}
    if ctx.get("executionMode") == "LIVE":
        return True
    if ctx.get("brokerAdopted"):
        return True
    return False


def _phantom_live_trade(trade: Any) -> bool:
    ctx = getattr(trade, "entryContext", None) or {}
    if not ctx.get("brokerAdopted"):
        return False
    entry = float(getattr(trade, "entryPremium", 0) or 0)
    strike = float(getattr(trade, "strike", 0) or 0)
    return entry <= 0 or strike > 100_000.0


def live_session_loss_count(state: AutoTraderState) -> int:
    """Count real closed live losses today — ignores phantom adopted rows."""
    losses = 0
    for trade in state.closedPaperTrades:
        if getattr(trade, "status", "CLOSED") != "CLOSED":
            continue
        if not _live_trade(trade) or _phantom_live_trade(trade):
            continue
        if float(getattr(trade, "pnlInr", 0) or 0) < 0:
            losses += 1
    return losses


def live_open_position_count(state: AutoTraderState) -> int:
    settings = get_settings()
    if not settings.enable_live_trading:
        return 0
    return sum(
        1
        for trade in state.openPaperTrades
        if getattr(trade, "status", "OPEN") == "OPEN"
    )


def live_best_trade_entry_blocked(
    candidate: Any,
    snap: SymbolSnapshot,
    state: AutoTraderState,
    *,
    snapshots: dict[str, SymbolSnapshot] | None = None,
    ranking: Mapping[str, Any] | None = None,
    chart_meta: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Final live-only quality gate at the order wire.

    Targets small live books: grade S, mature first-lift pad, chart aligned,
    one position max, pause after session loss.
    """
    settings = get_settings()
    meta: dict[str, Any] = {"liveBestTradeGate": True}
    if not getattr(settings, "live_best_trades_only_enabled", True):
        return False, "ok", meta
    if not settings.enable_live_trading:
        return False, "ok", meta
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False, "ok", meta

    event = getattr(candidate, "explosion_event", None)

    max_open = int(getattr(settings, "live_max_open_positions", 1) or 1)
    open_count = live_open_position_count(state)
    if open_count >= max_open:
        meta["liveOpenCount"] = open_count
        return True, "live_best_trades_max_open_positions", meta

    loss_pause = int(getattr(settings, "live_pause_after_session_losses", 1) or 1)
    loss_count = live_session_loss_count(state)
    meta["liveSessionLosses"] = loss_count
    if loss_count >= loss_pause:
        return True, "live_best_trades_session_loss_pause", meta

    ranking = ranking or {}
    if not ranking.get("grade") and event is not None:
        from app.engines.trade_ranking import rank_entry_candidate

        ranking = rank_entry_candidate(candidate, snapshot=snap)
    evidence = ranking.get("evidence") or {}
    grade = str(ranking.get("grade") or "").upper()
    min_grade = str(getattr(settings, "live_best_trades_min_grade", "S") or "S").upper()
    if grade != min_grade and min_grade == "S":
        return True, "live_best_trades_requires_grade_s", meta
    if min_grade == "A" and grade not in ("S", "A"):
        return True, "live_best_trades_requires_grade_a_or_s", meta

    from app.engines.top_moment_gate import top_moment_entry_allowed

    top_ok, top_reason, moment = top_moment_entry_allowed(
        evidence,
        ranking,
        top_moments_only_enabled=True,
        min_grade=min_grade,
    )
    meta["topMomentType"] = moment
    if not top_ok:
        return True, f"live_best_trades_{top_reason}", meta

    allowed_tiers = {
        t.strip().upper()
        for t in str(
            getattr(settings, "live_best_trades_tiers_csv", "ELITE,EXPLODING") or ""
        ).split(",")
        if t.strip()
    }
    tier = str(
        evidence.get("tier")
        or getattr(getattr(candidate, "explosion_event", None), "tier", "")
        or ""
    ).upper()
    if allowed_tiers and tier not in allowed_tiers:
        return True, f"live_best_trades_tier_{tier}_blocked", meta

    min_score = float(
        getattr(settings, "live_best_trades_min_explosion_score", 200.0) or 200.0
    )
    score = float(getattr(event, "explosion_score", 0) or 0) if event else 0.0
    meta["explosionScore"] = round(score, 1)
    if score < min_score:
        return True, f"live_best_trades_score_{score:.0f}_lt_{min_score:.0f}", meta

    if bool(getattr(settings, "live_best_trades_require_chart_aligned", True)):
        from app.engines.spot_direction import side_aligned_with_chart

        if snap.spotChart and not side_aligned_with_chart(candidate.side, snap.spotChart):
            return True, "live_best_trades_chart_not_aligned", meta

    if bool(getattr(settings, "live_best_trades_require_first_lift", True)):
        from app.engines.ict_breakout_monitor import first_lift_entry_readiness
        from app.engines.explosion_entry_guards import (
            effective_local_base_move_pct,
            trustworthy_local_base_move,
        )
        from app.engines.ict_breakout_monitor import analyze_explosion_event_ict

        alert = getattr(candidate, "alert", None)
        if not isinstance(alert, dict):
            alert = None
        ict = analyze_explosion_event_ict(event, snap) if event else None
        ready, ready_reason = first_lift_entry_readiness(
            snap=snap,
            event=event,
            alert=alert,
            ict=ict,
        )
        pad = max(
            effective_local_base_move_pct(event, ict) if event else 0.0,
            trustworthy_local_base_move(ict),
        )
        min_pad = float(
            getattr(settings, "live_best_trades_min_local_base_pct", 15.0) or 15.0
        )
        meta["localBaseMovePct"] = round(pad, 2)
        meta["firstLiftReady"] = ready
        meta["firstLiftReason"] = ready_reason
        if not ready and pad < min_pad:
            return True, f"live_best_trades_immature_pad_{pad:.1f}%", meta

    same_side_cap = int(getattr(settings, "live_max_same_side_positions", 1) or 1)
    if same_side_cap <= 1:
        side_v = _side_val(getattr(candidate, "side", Side.CALL))
        symbol = str(getattr(candidate, "symbol", "") or snap.symbol or "").upper()
        for trade in state.openPaperTrades:
            if trade.status != "OPEN" or not _live_trade(trade):
                continue
            if str(trade.symbol or "").upper() == symbol and _side_val(trade.side) == side_v:
                return True, "live_best_trades_same_side_open", meta

    return False, "ok", meta


def live_early_fail_exit_reason(
    trade: Any,
    *,
    hold_seconds: float,
    best_points: float,
    pnl_points: float,
    live_velocity_3s: float,
) -> Optional[str]:
    """Scratch live entries that never go green — even under structural hold."""
    settings = get_settings()
    if not getattr(settings, "live_early_fail_exit_enabled", True):
        return None
    ctx = getattr(trade, "entryContext", None) or {}
    if ctx.get("executionMode") != "LIVE" and not ctx.get("liveBestTradeGate"):
        return None

    min_hold = int(getattr(settings, "live_early_fail_min_hold_seconds", 45) or 45)
    max_hold = int(getattr(settings, "live_early_fail_max_hold_seconds", 240) or 240)
    max_best = float(getattr(settings, "live_early_fail_max_best_points", 1.0) or 1.0)
    min_loss = float(getattr(settings, "live_early_fail_min_loss_points", 2.5) or 2.5)
    max_v3 = float(getattr(settings, "live_early_fail_max_velocity_3s", 0.5) or 0.5)

    if not (min_hold <= hold_seconds <= max_hold):
        return None
    if best_points > max_best:
        return None
    if pnl_points > -min_loss:
        return None
    if live_velocity_3s >= max_v3:
        return None
    return "live_early_fail"
