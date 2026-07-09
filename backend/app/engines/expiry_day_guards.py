"""Expiry-day playbook — fewer trades, morning focus, worst-day prediction, dual CE/PE scalp."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.capital_allocator import compute_session_pnl
from app.engines.chop_day_guards import is_chop_session
from app.engines.pretrade_validator import collect_session_trades, compute_symbol_stats
from app.engines.whipsaw_guards import is_bearish_sideways_session
from app.models.schemas import AutoTraderState, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _minutes_now() -> int:
    now = datetime.now(IST)
    return now.hour * 60 + now.minute


def _today_str() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def _tomorrow_str() -> str:
    today_dt = datetime.strptime(_today_str(), "%Y-%m-%d").replace(tzinfo=IST)
    return (today_dt + timedelta(days=1)).strftime("%Y-%m-%d")


def is_symbol_expiry_day(snap: SymbolSnapshot) -> bool:
    """True when today's session date matches the option chain expiry."""
    settings = get_settings()
    if not settings.expiry_day_guards_enabled:
        return False
    if not snap.dataAvailable or not snap.optionExpiry:
        return False
    expiry = str(snap.optionExpiry)[:10]
    return expiry == _today_str()


_expiry_session_active: bool = False


def refresh_expiry_session(snapshots: dict[str, SymbolSnapshot]) -> None:
    """Cache expiry-session flag for fast entry-scan cadence without snapshot coupling."""
    global _expiry_session_active
    _expiry_session_active = is_expiry_session(snapshots)


def any_expiry_session_active() -> bool:
    return _expiry_session_active


def expiry_symbols(snapshots: dict[str, SymbolSnapshot]) -> list[str]:
    return [sym.upper() for sym, snap in snapshots.items() if is_symbol_expiry_day(snap)]


def near_expiry_symbols(snapshots: dict[str, SymbolSnapshot]) -> list[str]:
    """Symbols whose chain expires today or tomorrow (pre-expiry + expiry session)."""
    return [sym.upper() for sym, snap in snapshots.items() if is_near_expiry_day(snap)]


def is_pre_expiry_day(snap: SymbolSnapshot) -> bool:
    """True when chain expires tomorrow only — not yet expiry day."""
    if not snap.dataAvailable or not snap.optionExpiry:
        return False
    expiry = str(snap.optionExpiry)[:10]
    return expiry == _tomorrow_str()


def is_expiry_session(snapshots: dict[str, SymbolSnapshot]) -> bool:
    return len(expiry_symbols(snapshots)) > 0


def is_near_expiry_day(snap: SymbolSnapshot) -> bool:
    """True when chain expiry is today or tomorrow (pre-expiry + expiry session)."""
    if not snap.dataAvailable or not snap.optionExpiry:
        return False
    expiry = str(snap.optionExpiry)[:10]
    return expiry in (_today_str(), _tomorrow_str())


def in_expiry_pm_itm_window() -> bool:
    """14:00–15:25 IST window for small ITM quick scalps near expiry."""
    from app.services.upstox import get_market_phase

    settings = get_settings()
    if not settings.expiry_pm_itm_quick_enabled or get_market_phase() != "LIVE_MARKET":
        return False
    current = _minutes_now()
    start = settings.expiry_pm_itm_window_start_hour * 60 + settings.expiry_pm_itm_window_start_minute
    end = settings.expiry_pm_itm_window_end_hour * 60 + settings.expiry_pm_itm_window_end_minute
    return start <= current < end


def expiry_pm_itm_quick_active(
    snap: SymbolSnapshot,
    state: AutoTraderState | None = None,
    snapshots: dict[str, SymbolSnapshot] | None = None,
) -> bool:
    if not in_expiry_pm_itm_window():
        return False
    if is_near_expiry_day(snap):
        return True
    if state is not None and snapshots is not None:
        from app.engines.bad_day_routing import pm_itm_alternate_symbol_active

        return pm_itm_alternate_symbol_active(snap, state, snapshots)
    return False


def in_morning_slow_bounce_window() -> bool:
    """10:30–13:30 IST — post-open consolidation bounces on near-expiry ITM."""
    from app.services.upstox import get_market_phase

    settings = get_settings()
    if not settings.morning_slow_bounce_enabled or get_market_phase() != "LIVE_MARKET":
        return False
    current = _minutes_now()
    start = settings.morning_slow_bounce_start_hour * 60 + settings.morning_slow_bounce_start_minute
    end = settings.morning_slow_bounce_end_hour * 60 + settings.morning_slow_bounce_end_minute
    return start <= current < end


def slow_bounce_premium_max_inr(snap: SymbolSnapshot) -> float:
    """Higher cap on near-expiry days (e.g. SENSEX 77600 PE at ₹216)."""
    settings = get_settings()
    if is_near_expiry_day(snap):
        return settings.expiry_near_expiry_premium_max_inr
    return settings.expiry_pm_itm_premium_max_inr


def slow_bounce_session_active(
    snap: SymbolSnapshot,
    state: AutoTraderState | None = None,
    snapshots: dict[str, SymbolSnapshot] | None = None,
) -> bool:
    """PM ITM window (14:00+) or morning consolidation window on near-expiry."""
    if expiry_pm_itm_quick_active(snap, state, snapshots):
        return True
    if in_morning_slow_bounce_window() and is_near_expiry_day(snap):
        return True
    return False


def slow_bounce_session_active_any(
    snapshots: dict[str, SymbolSnapshot],
    state: AutoTraderState | None = None,
) -> bool:
    if expiry_pm_itm_quick_session_active(snapshots, state):
        return True
    if not in_morning_slow_bounce_window():
        return False
    return any(is_near_expiry_day(s) for s in snapshots.values() if s.dataAvailable)


def expiry_pm_itm_quick_session_active(
    snapshots: dict[str, SymbolSnapshot],
    state: AutoTraderState | None = None,
) -> bool:
    if not in_expiry_pm_itm_window():
        return False
    if any(is_near_expiry_day(s) for s in snapshots.values() if s.dataAvailable):
        return True
    if state is not None:
        from app.engines.bad_day_routing import pm_itm_alternate_symbols

        return bool(pm_itm_alternate_symbols(state, snapshots))
    return False


def expiry_pm_itm_chart_bypass_allowed(
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    mode: str = "",
    state: AutoTraderState | None = None,
    snapshots: dict[str, SymbolSnapshot] | None = None,
) -> bool:
    """Allow ITM quick scalps through opposite 5m chart when breadth aligns (PM expiry window)."""
    settings = get_settings()
    if not settings.expiry_pm_itm_chart_bypass_breadth:
        return False
    if str(mode or "") not in ("quick_sideways", "slow_bounce"):
        return False
    if not expiry_pm_itm_quick_active(snap, state, snapshots) and not (
        in_morning_slow_bounce_window() and is_near_expiry_day(snap)
    ):
        return False
    return _breadth_aligned_for_side(side, snap.breadth)


def in_expiry_morning_window() -> bool:
    """Preferred entry window on expiry — before afternoon theta crush."""
    settings = get_settings()
    current = _minutes_now()
    start = settings.entry_earliest_hour * 60 + settings.entry_earliest_minute
    end = settings.expiry_morning_end_hour * 60 + settings.expiry_morning_end_minute
    return start <= current < end


def in_expiry_explosion_open_block() -> bool:
    """First N minutes after entry window on expiry — block noisy EXPLODING opens."""
    from app.services.upstox import get_market_phase

    settings = get_settings()
    if not settings.expiry_day_guards_enabled or get_market_phase() != "LIVE_MARKET":
        return False
    start = settings.entry_earliest_hour * 60 + settings.entry_earliest_minute
    end = start + settings.expiry_explosion_open_block_minutes
    return start <= _minutes_now() < end


def _breadth_aligned_for_side(side: Side | str, breadth: Any) -> bool:
    side_val = side.value if isinstance(side, Side) else str(side).upper()
    side_bias = "BULLISH" if side_val == "CALL" else "BEARISH"
    bias = (getattr(breadth, "bias", None) or "NEUTRAL")
    if hasattr(bias, "upper"):
        bias = bias.upper()
    else:
        bias = str(bias).upper()
    aligned = bool(getattr(breadth, "aligned", False))
    return aligned or bias == side_bias


def check_expiry_explosion_open_block(
    *,
    snap: SymbolSnapshot,
    tier: str,
    side: Side | str,
    breadth: Any,
) -> tuple[bool, str]:
    """
    On expiry, block EXPLODING tier in the first minutes after open.
    ELITE + breadth-aligned legs may still enter.
    Returns (blocked, reason).
    """
    if not is_symbol_expiry_day(snap):
        return False, "ok"
    if not in_expiry_explosion_open_block():
        return False, "ok"
    tier_u = str(tier or "").upper()
    if tier_u == "ELITE" and _breadth_aligned_for_side(side, breadth):
        return False, "ok"
    if tier_u in ("EXPLODING", "BUILDING"):
        return True, "expiry_open_block_exploding"
    return False, "ok"


def in_expiry_evening_block() -> bool:
    """Block new entries in expiry afternoon/evening — gamma + pin risk."""
    settings = get_settings()
    if not settings.expiry_day_guards_enabled:
        return False
    current = _minutes_now()
    block_from = settings.expiry_evening_block_hour * 60 + settings.expiry_evening_block_minute
    return current >= block_from


def _session_declining(state: AutoTraderState, snapshots: dict[str, SymbolSnapshot]) -> bool:
    """Session PnL bleeding + bearish sideways — hard to make money trending."""
    settings = get_settings()
    session_pnl = compute_session_pnl(state)
    if session_pnl <= settings.expiry_decline_session_loss_inr:
        return True
    trades = collect_session_trades(state)
    if len(trades) >= 3:
        stats = compute_symbol_stats(trades)
        net = sum(s.net_pnl_inr for s in stats.values())
        if net <= settings.expiry_decline_session_loss_inr:
            return True
    if is_bearish_sideways_session(snapshots):
        declining = 0
        for snap in snapshots.values():
            if not snap.dataAvailable or not snap.spotChart:
                continue
            mom = float(snap.spotChart.momentum5Pct or 0)
            if mom < -0.03:
                declining += 1
        live = sum(1 for s in snapshots.values() if s.dataAvailable)
        if live and declining >= max(1, live // 2):
            return True
    return False


def predict_worst_expiry_day(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, float, list[str]]:
    """
    Predict a worst expiry chop day before taking more risk.
    Returns (is_worst, score 0-100, human reasons).
    """
    settings = get_settings()
    if not settings.expiry_day_guards_enabled or not is_expiry_session(snapshots):
        return False, 0.0, []

    score = 0.0
    reasons: list[str] = []

    if is_chop_session(snapshots):
        score += 25
        reasons.append("chop_regime")
    if is_bearish_sideways_session(snapshots):
        score += 25
        reasons.append("bearish_sideways")
    session_pnl = compute_session_pnl(state)
    if session_pnl <= settings.expiry_worst_day_session_loss_inr:
        score += 20
        reasons.append(f"session_loss_{session_pnl:.0f}")
    trades = collect_session_trades(state)
    if len(trades) >= 2:
        losses = sum(1 for t in trades if t.pnl_inr < 0)
        if losses >= settings.expiry_worst_day_loss_count:
            score += 15
            reasons.append(f"loss_cluster_{losses}")
    if _session_declining(state, snapshots):
        score += 15
        reasons.append("declining_session")
    if in_expiry_evening_block():
        score += 10
        reasons.append("expiry_evening")

    is_worst = score >= settings.expiry_worst_day_score_threshold
    return is_worst, round(score, 1), reasons


def expiry_trade_cap(state: AutoTraderState, snapshots: dict[str, SymbolSnapshot]) -> tuple[int, str]:
    settings = get_settings()
    if not settings.expiry_day_guards_enabled or not is_expiry_session(snapshots):
        return 999, "normal"
    is_worst, _, _ = predict_worst_expiry_day(state, snapshots)
    if is_worst:
        return settings.expiry_worst_day_max_trades, "expiry_worst"
    return settings.expiry_max_trades_per_day, "expiry_day"


def expiry_trades_cap_reached(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, str]:
    cap, label = expiry_trade_cap(state, snapshots)
    closed = len(state.closedPaperTrades)
    if closed >= cap:
        return True, f"expiry_trade_cap_{closed}>={cap}_{label}"
    return False, "ok"


def expiry_min_rank_score(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> float:
    settings = get_settings()
    if not settings.expiry_day_guards_enabled or not is_expiry_session(snapshots):
        return 0.0
    is_worst, _, _ = predict_worst_expiry_day(state, snapshots)
    if is_worst:
        return settings.expiry_worst_day_min_rank_score
    return settings.expiry_min_rank_score


def check_expiry_entry_allowed(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, str, dict[str, Any]]:
    """Session-level expiry gates before any new entry."""
    settings = get_settings()
    meta: dict[str, Any] = {}
    if not settings.expiry_day_guards_enabled:
        return True, "ok", meta

    has_expiry_today = is_expiry_session(snapshots)
    pm_itm = expiry_pm_itm_quick_session_active(snapshots, state)
    meta["expiryPmItmQuickActive"] = pm_itm

    if not has_expiry_today and not pm_itm:
        return True, "ok", meta

    if has_expiry_today:
        meta["expirySymbols"] = expiry_symbols(snapshots)
        is_worst, worst_score, worst_reasons = predict_worst_expiry_day(state, snapshots)
        meta["worstDay"] = is_worst
        meta["worstDayScore"] = worst_score
        meta["worstDayReasons"] = worst_reasons

    if pm_itm:
        meta["expiryPmItmQuickOnly"] = True
        if not has_expiry_today:
            return True, "ok", meta

    if in_expiry_evening_block() and has_expiry_today:
        if pm_itm:
            return True, "ok", meta
        return False, "expiry_evening_block", meta

    if not in_expiry_morning_window() and settings.expiry_morning_only and has_expiry_today:
        if pm_itm:
            return True, "ok", meta
        return False, "expiry_afternoon_wait", meta

    if has_expiry_today:
        cap_hit, cap_reason = expiry_trades_cap_reached(state, snapshots)
        if cap_hit:
            return False, cap_reason, meta

        if is_worst and settings.expiry_worst_day_halt_entries:
            if _session_declining(state, snapshots):
                return False, "expiry_worst_day_declining_halt", meta

    return True, "ok", meta


def check_expiry_candidate(
    candidate: Any,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, str, dict[str, Any]]:
    """Per-candidate expiry rules."""
    settings = get_settings()
    meta: dict[str, Any] = {}
    sym = candidate.symbol.upper()
    snap = snapshots.get(sym) or candidate.snap
    score = float(getattr(candidate, "score", 0) or 0)
    mode = str(getattr(candidate, "mode", "") or "")
    pm_itm = expiry_pm_itm_quick_active(snap, state, snapshots)
    meta["expiryPmItmQuick"] = pm_itm

    if pm_itm:
        if mode not in ("quick_sideways", "slow_bounce"):
            return False, "expiry_pm_itm_quick_only", meta
        from app.engines.moneyness import classify_moneyness

        money = classify_moneyness(
            candidate.side, float(candidate.strike), float(snap.spot or 0),
            symbol=sym, atm=float(snap.atmStrike or 0) or None,
        )
        meta["moneyness"] = money
        if money != "ITM":
            return False, "expiry_pm_itm_strike_only", meta
        floor = settings.expiry_pm_itm_min_rank_score
        if score < floor:
            return False, f"expiry_pm_itm_rank_below_{floor:.0f}", meta
        return True, "ok", meta

    if not is_symbol_expiry_day(snap):
        return True, "ok", meta

    if mode == "explosion":
        tier = str(getattr(candidate, "tier", "") or "")
        blocked, block_reason = check_expiry_explosion_open_block(
            snap=snap,
            tier=tier,
            side=candidate.side,
            breadth=snap.breadth,
        )
        if blocked:
            return False, block_reason, meta

        from app.engines.aligned_explosion_bypass import expiry_aligned_explosion_trade_allowed

        if expiry_aligned_explosion_trade_allowed(candidate, snap)[0]:
            meta["expiryAlignedBypass"] = True
            return True, "ok", meta

    from app.engines.pretrade_validator import candidate_trade_score

    rank_score = candidate_trade_score(candidate)
    min_rank = expiry_min_rank_score(state, snapshots)
    meta["expiryMinRank"] = min_rank
    meta["rankScore"] = rank_score
    if min_rank > 0 and rank_score < min_rank:
        return False, f"expiry_rank_below_{min_rank:.0f}", meta

    is_worst, _, _ = predict_worst_expiry_day(state, snapshots)
    if is_worst and _session_declining(state, snapshots):
        if score < settings.expiry_worst_day_min_rank_score:
            return False, "expiry_worst_day_low_score", meta

    return True, "ok", meta


def expiry_dual_scalp_active(snapshots: dict[str, SymbolSnapshot]) -> bool:
    """On expiry chop, allow managed CE+PE scalps instead of one-sided churn."""
    settings = get_settings()
    return (
        settings.expiry_day_guards_enabled
        and settings.expiry_dual_scalp_mode
        and is_expiry_session(snapshots)
        and is_chop_session(snapshots)
    )


def relax_opposite_side_for_expiry_dual(
    symbol: str,
    side: Side | str,
    snap: SymbolSnapshot,
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """
    On expiry dual-scalp mode, shorten opposite-side cooldown when session is declining
    so we can hedge with the other leg instead of fighting one direction.
    """
    if not expiry_dual_scalp_active(snapshots):
        return False
    if not is_symbol_expiry_day(snap):
        return False
    settings = get_settings()
    return settings.expiry_dual_scalp_relax_whipsaw


def expiry_guard_summary(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> dict[str, Any]:
    settings = get_settings()
    symbols = expiry_symbols(snapshots)
    is_worst, worst_score, worst_reasons = predict_worst_expiry_day(state, snapshots)
    cap, cap_label = expiry_trade_cap(state, snapshots)
    cap_hit, cap_msg = expiry_trades_cap_reached(state, snapshots)
    allowed, block_reason, _ = check_expiry_entry_allowed(state, snapshots)

    pm_alts: list[str] = []
    if state is not None:
        from app.engines.bad_day_routing import pm_itm_alternate_symbols

        pm_alts = sorted(pm_itm_alternate_symbols(state, snapshots))

    near = near_expiry_symbols(snapshots)
    pre_only = [s for s in near if s not in symbols]
    return {
        "enabled": settings.expiry_day_guards_enabled,
        "expirySession": bool(symbols),
        "expirySymbols": symbols,
        "nearExpirySymbols": near,
        "preExpirySymbols": pre_only,
        "eveningBlockActive": in_expiry_evening_block() and bool(symbols),
        "morningWindow": in_expiry_morning_window(),
        "eveningBlock": in_expiry_evening_block(),
        "worstDay": is_worst,
        "worstDayScore": worst_score,
        "worstDayReasons": worst_reasons,
        "decliningSession": _session_declining(state, snapshots),
        "dailyTradeCap": cap,
        "dailyTradeCapLabel": cap_label,
        "tradeCapReached": cap_hit,
        "tradeCapMessage": cap_msg if cap_hit else None,
        "entriesAllowed": allowed,
        "blockReason": block_reason if not allowed else None,
        "dualScalpMode": expiry_dual_scalp_active(snapshots),
        "minRankScore": expiry_min_rank_score(state, snapshots),
        "sessionPnlInr": round(compute_session_pnl(state), 2),
        "expiryPmItmQuickActive": expiry_pm_itm_quick_session_active(snapshots, state),
        "expiryPmItmWindow": in_expiry_pm_itm_window(),
        "expiryPmItmAlternateSymbols": pm_alts,
    }
