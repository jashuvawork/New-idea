"""Pre-trade validation — session backtest stats, index selection, controlled entry gates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import AutoTraderState, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def candidate_trade_score(candidate: Any) -> float:
    """Composite score used consistently across pretrade and execution chart gates."""
    return max(
        float(getattr(candidate, "tqs", 0) or 0),
        float(getattr(candidate, "confidence", 0) or 0),
        float(getattr(candidate, "score", 0) or 0),
    )


@dataclass
class TradeRecord:
    symbol: str
    side: str
    pnl_inr: float
    exit_reason: str = ""
    strike: float = 0.0
    trade_id: str = ""


@dataclass
class SymbolSessionStats:
    symbol: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    net_pnl_inr: float = 0.0
    profit_factor: float = 0.0
    win_rate: float = 0.0


def _profit_factor(trades: list[TradeRecord]) -> float:
    gross_win = sum(t.pnl_inr for t in trades if t.pnl_inr > 0)
    gross_loss = abs(sum(t.pnl_inr for t in trades if t.pnl_inr < 0))
    if gross_loss <= 0:
        return gross_win if gross_win > 0 else 0.0
    return gross_win / gross_loss


def _paper_trade_records(state: AutoTraderState, reset_at: Optional[datetime] = None) -> list[TradeRecord]:
    out: list[TradeRecord] = []
    for t in state.closedPaperTrades:
        if reset_at:
            closed_at = t.closedAt
            if closed_at is None:
                continue
            if closed_at.tzinfo is None:
                closed_at = closed_at.replace(tzinfo=IST)
            if closed_at <= reset_at:
                continue
        side = t.side.value if isinstance(t.side, Side) else str(t.side).upper()
        out.append(TradeRecord(
            symbol=t.symbol.upper(),
            side=side,
            pnl_inr=float(t.pnlInr or 0),
            exit_reason=str(t.exitReason or ""),
            strike=float(t.strike or 0),
            trade_id=str(t.id),
        ))
    return out


def collect_session_trades(state: AutoTraderState) -> list[TradeRecord]:
    """Session closed trades — in-memory plus today's archive (survives restarts)."""
    today = datetime.now(IST).strftime("%Y-%m-%d")
    reset_at: Optional[datetime] = None

    try:
        from app.services import trade_store

        reset_at = trade_store.get_session_reset_at()
    except Exception:
        pass

    records = _paper_trade_records(state, reset_at)
    seen = {r.trade_id for r in records if r.trade_id}

    try:
        from app.services import trade_store

        day = trade_store.get_day_detail(today)
        for row in day.get("trades", []):
            if row.get("status") != "CLOSED":
                continue
            exit_reason = str(row.get("exitReason") or "")
            if exit_reason in ("SESSION_RESET", "manual_reset"):
                continue
            closed_raw = row.get("closedAt")
            if reset_at and closed_raw:
                try:
                    closed_at = datetime.fromisoformat(str(closed_raw))
                    if closed_at <= reset_at:
                        continue
                except ValueError:
                    pass
            tid = str(row.get("id", ""))
            if tid and tid in seen:
                continue
            records.append(TradeRecord(
                symbol=str(row.get("symbol", "")).upper(),
                side=str(row.get("side", "")).upper(),
                pnl_inr=float(row.get("pnlInr") or 0),
                exit_reason=exit_reason,
                strike=float(row.get("strike") or 0),
                trade_id=tid,
            ))
    except Exception:
        pass

    if reset_at:
        filtered: list[TradeRecord] = []
        for rec in records:
            if rec.exit_reason in ("SESSION_RESET", "manual_reset"):
                continue
            filtered.append(rec)
        records = filtered

    return records


def momentum_rally_bypass_last_n(snapshots: Optional[dict[str, SymbolSnapshot]]) -> bool:
    """Allow entries during 11:00–13:45 rally when premium velocity is expanding."""
    if not snapshots:
        return False
    settings = get_settings()
    if not settings.last_n_momentum_rally_bypass_enabled:
        return False
    from app.engines.chop_day_guards import in_momentum_rally_window, is_momentum_surge

    if not in_momentum_rally_window():
        return False
    for snap in snapshots.values():
        if not snap.dataAvailable:
            continue
        vel = 0.0
        vol = 1.0
        score = 0.0
        runner = snap.explosiveRunner
        if runner and runner.signal:
            vel = float(runner.signal.premiumVelocityPct or 0)
            score = float(runner.score or 0)
            vol = float(runner.signal.volumeSurge or 1.0)
        top = snap.topExplosion or {}
        if top:
            vel = max(vel, float(top.get("velocity3s") or 0))
            score = max(score, float(top.get("score") or 0))
        if is_momentum_surge(vel, vol, score):
            return True
    return False


def compute_symbol_stats(trades: list[TradeRecord]) -> dict[str, SymbolSessionStats]:
    buckets: dict[str, list[TradeRecord]] = {}
    for t in trades:
        buckets.setdefault(t.symbol, []).append(t)

    stats: dict[str, SymbolSessionStats] = {}
    for symbol, rows in buckets.items():
        wins = sum(1 for r in rows if r.pnl_inr > 0)
        losses = sum(1 for r in rows if r.pnl_inr < 0)
        net = sum(r.pnl_inr for r in rows)
        stats[symbol] = SymbolSessionStats(
            symbol=symbol,
            trades=len(rows),
            wins=wins,
            losses=losses,
            net_pnl_inr=round(net, 2),
            profit_factor=round(_profit_factor(rows), 2),
            win_rate=round(100.0 * wins / len(rows), 1) if rows else 0.0,
        )
    return stats


def index_rank_from_backtest(stats: dict[str, SymbolSessionStats]) -> dict[str, float]:
    """Prefer index with better session PF when both have enough samples."""
    settings = get_settings()
    min_n = settings.pretrade_min_symbol_trades_for_stats
    eligible = {sym: st for sym, st in stats.items() if st.trades >= min_n}
    if len(eligible) < 2:
        return {}

    ranked = sorted(
        eligible.items(),
        key=lambda item: (item[1].profit_factor, item[1].net_pnl_inr),
        reverse=True,
    )
    best_sym, best_st = ranked[0]
    adjustments: dict[str, float] = {best_sym: settings.index_selection_pf_bonus}

    for sym, st in ranked[1:]:
        if st.profit_factor < settings.pretrade_block_symbol_pf_below:
            adjustments[sym] = -settings.index_selection_pf_bonus
        elif st.net_pnl_inr < 0 and best_st.net_pnl_inr > 0:
            adjustments[sym] = -settings.index_selection_pf_bonus * 0.5

    return adjustments


def seconds_since_last_exit(state: AutoTraderState) -> float:
    last = state.lastExit
    if not last or not last.get("at"):
        return 999_999.0
    try:
        closed = datetime.fromisoformat(str(last["at"]).replace("Z", "+00:00")).astimezone(IST)
        return (datetime.now(IST) - closed).total_seconds()
    except Exception:
        return 999_999.0


def check_min_entry_interval(
    state: AutoTraderState,
    *,
    chop: bool = False,
    quick_sideways: bool = False,
    candidate: Any = None,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
) -> tuple[bool, str]:
    settings = get_settings()
    last = state.lastExit
    if not last or not last.get("at"):
        return True, "ok"
    try:
        closed = datetime.fromisoformat(str(last["at"]).replace("Z", "+00:00")).astimezone(IST)
    except Exception:
        return True, "ok"

    pnl = float(last.get("pnlInr", 0) or 0)
    after_loss = pnl < 0

    from app.engines.aligned_explosion_bypass import (
        entry_interval_gap_seconds,
        is_aligned_explosion_rip,
    )

    aligned_rip = False
    if candidate is not None and snapshots is not None:
        sym = str(getattr(candidate, "symbol", "")).upper()
        snap = snapshots.get(sym) or getattr(candidate, "snap", None)
        if snap is not None:
            aligned_rip, _ = is_aligned_explosion_rip(candidate, snap)

    gap = entry_interval_gap_seconds(
        chop=chop,
        quick_sideways=quick_sideways,
        after_loss=after_loss and not aligned_rip,
        aligned_rip=aligned_rip,
    )

    elapsed = (datetime.now(IST) - closed).total_seconds()
    if elapsed < gap:
        remain = int(gap - elapsed)
        if aligned_rip:
            suffix = "aligned_rip"
        elif after_loss:
            suffix = "after_loss"
        else:
            suffix = "after_exit"
        return False, f"pretrade_entry_interval_{suffix}_{remain}s"
    return True, "ok"


def resolve_effective_daily_trade_cap(
    state: AutoTraderState,
    snapshots: Optional[dict] = None,
) -> tuple[int, str]:
    """
    Effective closed-trade cap — merges controlled base, daily 18% strategy, rally windows.
    Avoids hard 6-trade ceiling blocking momentum rallies toward 18% target.
    """
    settings = get_settings()
    if not settings.controlled_trading_enabled:
        return 999, "off"

    cap = settings.controlled_max_trades_per_day
    label = "controlled"

    from app.engines.daily_18pct_strategy import get_session_limits

    limits = get_session_limits()
    if limits and settings.daily_18pct_strategy_enabled:
        cap = max(cap, limits.maxTradesToday)
        label = "daily_strategy"

    if snapshots:
        from app.engines.chop_day_guards import in_momentum_rally_window, is_chop_session
        from app.engines.morning_premium_capture import (
            in_afternoon_premium_capture_window,
            in_morning_premium_capture_window,
        )

        if in_momentum_rally_window():
            cap = max(cap, settings.daily_18pct_chop_max_trades)
            cap += settings.controlled_rally_trade_cap_bonus
            label = "momentum_rally"
        elif in_morning_premium_capture_window():
            cap = max(cap, settings.controlled_max_trades_per_day + 4)
            label = "morning_capture"
        elif in_afternoon_premium_capture_window():
            cap = max(cap, settings.controlled_max_trades_per_day + 2)
            label = "afternoon_capture"
        elif is_chop_session(snapshots):
            cap = max(cap, settings.daily_18pct_chop_max_trades)

        if limits and settings.day_adaptive_enabled:
            from app.engines.day_adaptive_engine import build_day_adaptive_profile

            profile = build_day_adaptive_profile(
                limits.dayMode,
                limits.confidenceTier,
                snapshots,
                phase=limits.phase,
                state=state,
            )
            if profile.day_type in ("GOOD", "ELITE"):
                cap = max(cap, settings.daily_18pct_chop_max_trades + 2)

    return cap, label


def controlled_daily_cap_reached(
    state: AutoTraderState,
    snapshots: Optional[dict] = None,
) -> tuple[bool, str]:
    settings = get_settings()
    if not settings.controlled_trading_enabled:
        return False, "ok"
    cap, _ = resolve_effective_daily_trade_cap(state, snapshots)
    if cap <= 0:
        return False, "ok"
    closed = len(collect_session_trades(state))
    if closed >= cap:
        return True, f"controlled_daily_cap_{cap}"
    return False, "ok"


def analyze_last_n_trades(trades: list[TradeRecord], n: int = 5) -> dict[str, Any]:
    """Summarize the most recent closed trades for gating."""
    recent = trades[-n:] if trades else []
    if not recent:
        return {"count": 0, "wins": 0, "losses": 0, "netPnlInr": 0.0, "profitFactor": 0.0}

    wins = sum(1 for t in recent if t.pnl_inr > 0)
    losses = sum(1 for t in recent if t.pnl_inr < 0)
    net = sum(t.pnl_inr for t in recent)
    pf = round(_profit_factor(recent), 2)

    return {
        "count": len(recent),
        "lookback": n,
        "wins": wins,
        "losses": losses,
        "netPnlInr": round(net, 2),
        "profitFactor": pf,
        "allLosses": losses == len(recent) and len(recent) >= n,
        "trades": [
            {
                "symbol": t.symbol,
                "side": t.side,
                "strike": t.strike,
                "pnlInr": round(t.pnl_inr, 2),
                "exitReason": t.exit_reason,
            }
            for t in recent
        ],
    }


def last_n_trades_summary(state: AutoTraderState) -> dict[str, Any]:
    settings = get_settings()
    trades = collect_session_trades(state)
    n = settings.last_n_trades_lookback
    return analyze_last_n_trades(trades, n)


def check_last_n_trades_pause(
    state: AutoTraderState,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Session-level pause when last N trades are catastrophic (e.g. 4/5 losses)."""
    settings = get_settings()
    if not settings.last_n_trades_gate_enabled:
        return False, "ok", {}

    trades = collect_session_trades(state)
    if len(trades) < settings.last_n_trades_min_count:
        return False, "ok", last_n_trades_summary(state)

    summary = analyze_last_n_trades(trades, settings.last_n_trades_lookback)
    if momentum_rally_bypass_last_n(snapshots):
        return False, "momentum_rally_bypass", summary

    from app.engines.morning_premium_capture import premium_capture_active

    if premium_capture_active(snapshots):
        return False, "premium_capture_bypass", summary

    losses = summary["losses"]
    count = summary["count"]

    if count >= settings.last_n_trades_lookback and losses >= settings.last_n_pause_after_losses:
        return True, f"last_n_pause_{losses}_of_{count}_losses", summary

    if count >= settings.last_n_trades_lookback and summary.get("allLosses"):
        return True, f"last_n_pause_all_{count}_losses", summary

    if count >= settings.last_n_trades_lookback and summary["profitFactor"] < settings.last_n_block_pf_below:
        return True, f"last_n_pause_pf_{summary['profitFactor']:.2f}", summary

    if summary["netPnlInr"] <= settings.last_n_block_net_inr_below:
        return True, f"last_n_pause_net_{summary['netPnlInr']:.0f}", summary

    return False, "ok", summary


def last_n_elevated_min_rank(state: AutoTraderState) -> float:
    """Raise rank floor when last N shows a loss cluster."""
    settings = get_settings()
    if not settings.last_n_trades_gate_enabled:
        return 0.0
    trades = collect_session_trades(state)
    if len(trades) < settings.last_n_trades_min_count:
        return 0.0
    summary = analyze_last_n_trades(trades, settings.last_n_trades_lookback)
    if summary["losses"] >= settings.last_n_elevate_after_losses:
        return settings.last_n_elevated_min_rank_score
    return 0.0


def check_last_n_candidate_gate(
    candidate: Any,
    state: AutoTraderState,
    session_trades: Optional[list[TradeRecord]] = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Per-candidate gate from last N trade performance."""
    settings = get_settings()
    trades = session_trades if session_trades is not None else collect_session_trades(state)
    summary = analyze_last_n_trades(trades, settings.last_n_trades_lookback)
    meta = {"lastN": summary}

    if not settings.last_n_trades_gate_enabled or len(trades) < settings.last_n_trades_min_count:
        return True, "ok", meta

    score = float(getattr(candidate, "score", 0) or 0)
    elevated = last_n_elevated_min_rank(state)
    if elevated > 0 and score < elevated:
        return False, f"last_n_elevated_rank_{elevated:.0f}", meta

    if (
        settings.best_trades_only_enabled
        and summary["losses"] >= settings.best_trades_explosion_only_after_losses
        and getattr(candidate, "mode", "") != "explosion"
    ):
        return False, "last_n_explosion_only", meta

    if settings.best_trades_only_enabled and getattr(candidate, "mode", "") == "quick_sideways":
        return True, "ok", meta

    snap = getattr(candidate, "snap", None)
    if snap is not None:
        from app.engines.aligned_explosion_bypass import expiry_aligned_explosion_trade_allowed

        if expiry_aligned_explosion_trade_allowed(candidate, snap)[0]:
            return True, "ok", meta

    if settings.best_trades_only_enabled and score < settings.best_trades_min_rank_score:
        return False, f"best_trades_rank_below_{settings.best_trades_min_rank_score:.0f}", meta

    return True, "ok", meta


def validate_candidate(
    candidate: Any,
    state: AutoTraderState,
    session_trades: Optional[list[TradeRecord]] = None,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Pre-trade backtest checks before execution.
    Returns (passed, reason, metadata for entryContext.pretrade).
    """
    settings = get_settings()
    if not settings.controlled_trading_enabled:
        return True, "ok", {}

    trades = session_trades if session_trades is not None else collect_session_trades(state)
    meta: dict[str, Any] = {"controlledTrading": True}

    from app.engines.chop_day_guards import is_chop_session

    snap_map = snapshots or {candidate.symbol.upper(): candidate.snap}
    chop = is_chop_session(snap_map)

    ok, reason = check_min_entry_interval(
        state,
        chop=chop,
        quick_sideways=getattr(candidate, "mode", "") in ("quick_sideways", "slow_bounce"),
        candidate=candidate,
        snapshots=snap_map,
    )
    if not ok:
        return False, reason, meta

    if getattr(candidate, "mode", "") == "explosion":
        from app.engines.morning_premium_capture import counter_trend_entry_allowed

        snap_pre = snap_map.get(candidate.symbol.upper()) or candidate.snap
        explosion_event = getattr(candidate, "explosion_event", None)
        if explosion_event is not None and not counter_trend_entry_allowed(
            candidate.side, snap_pre, explosion_event=explosion_event,
        ):
            return False, "counter_trend_requires_elite", meta

    cap_hit, cap_reason = controlled_daily_cap_reached(state, snap_map)
    if cap_hit:
        return False, cap_reason, meta

    ln_ok, ln_reason, ln_meta = check_last_n_candidate_gate(candidate, state, trades)
    meta.update(ln_meta)
    if not ln_ok:
        return False, ln_reason, meta

    from app.engines.directional_lock import check_directional_side_lock

    sym = candidate.symbol.upper()
    snap = snap_map.get(sym) or candidate.snap
    tier = str(getattr(candidate, "tier", "") or "")

    premium_bypass = False
    explosion_event = getattr(candidate, "explosion_event", None)
    if getattr(candidate, "mode", "") == "explosion" and explosion_event is not None:
        from app.engines.morning_premium_capture import premium_led_explosion_bypass

        premium_bypass = premium_led_explosion_bypass(
            explosion_event,
            snap.spotChart,
            (snap.breadth.bias if snap.breadth else "NEUTRAL"),
        )

    dir_blocked, dir_reason = check_directional_side_lock(
        sym, candidate.side, snap, tier=tier, premium_led_bypass=premium_bypass,
        candidate=candidate,
    )
    if dir_blocked:
        return False, dir_reason, meta

    from app.engines.whipsaw_guards import check_whipsaw_candidate

    if settings.whipsaw_guards_enabled:
        ws_ok, ws_reason, ws_meta = check_whipsaw_candidate(candidate, state, snap_map)
        meta.update(ws_meta)
        if not ws_ok:
            return False, ws_reason, meta

    from app.engines.confidence_hold import high_confidence_reentry_blocked

    hc_blocked, hc_reason = high_confidence_reentry_blocked(
        candidate.symbol,
        candidate.side,
        candidate.strike,
        float(getattr(candidate, "score", 0) or 0),
    )
    if hc_blocked:
        return False, hc_reason, meta

    from app.engines.moneyness import moneyness_allows

    mn_ok, mn_reason, mn_meta = moneyness_allows(
        candidate.side,
        candidate.strike,
        snap,
        mode=str(getattr(candidate, "mode", "scalp")),
        candidate_score=float(getattr(candidate, "score", 0) or 0),
        snapshots=snap_map,
        state=state,
    )
    meta.update(mn_meta)
    if not mn_ok:
        return False, mn_reason, meta

    from app.engines.expiry_day_guards import check_expiry_candidate, expiry_min_rank_score
    from app.engines.bad_day_routing import check_bad_day_candidate

    bd_ok, bd_reason, bd_meta = check_bad_day_candidate(candidate, state, snap_map)
    meta.update(bd_meta)
    if not bd_ok:
        return False, bd_reason, meta

    from app.engines.worst_day_guard import worst_day_allows_candidate

    wd_ok, wd_reason, wd_meta = worst_day_allows_candidate(candidate, state, snap_map)
    meta.update(wd_meta)
    if not wd_ok:
        return False, wd_reason, meta

    ex_ok, ex_reason, ex_meta = check_expiry_candidate(candidate, state, snap_map)
    meta.update(ex_meta)
    if not ex_ok:
        return False, ex_reason, meta

    from app.engines.expiry_day_guards import (
        expiry_pm_itm_quick_active,
        is_symbol_expiry_day,
    )

    expiry_floor = expiry_min_rank_score(state, snap_map)
    min_rank = max(settings.pretrade_min_rank_score, expiry_floor)
    mode = getattr(candidate, "mode", "")
    if mode == "quick_sideways":
        if expiry_pm_itm_quick_active(snap, state, snap_map):
            min_rank = min(min_rank, settings.expiry_pm_itm_min_rank_score)
        elif not is_symbol_expiry_day(snap):
            min_rank = min(min_rank, settings.quick_sideways_min_rank_score)
    elif mode == "slow_bounce":
        min_rank = min(
            min_rank,
            settings.quick_sideways_slow_bounce_min_rank_score,
            settings.expiry_pm_itm_min_rank_score,
        )
    if candidate.score < min_rank:
        return False, f"pretrade_rank_below_{min_rank:.0f}", meta

    side_val = candidate.side.value if isinstance(candidate.side, Side) else str(candidate.side).upper()

    from app.engines.symbol_cooldown import side_aligned_with_breadth

    trade_score = candidate_trade_score(candidate)

    if not premium_bypass:
        explosion_event = getattr(candidate, "explosion_event", None)
        if getattr(candidate, "mode", "") == "explosion" and explosion_event is not None:
            from app.engines.morning_premium_capture import premium_led_explosion_bypass

            premium_bypass = premium_led_explosion_bypass(
                explosion_event,
                snap.spotChart,
                (snap.breadth.bias if snap.breadth else "NEUTRAL"),
            )

    if not side_aligned_with_breadth(side_val, snap.breadth.bias) and not premium_bypass:
        counter_floor = settings.counter_breadth_min_score
        from app.engines.morning_premium_capture import premium_led_entry_allowed

        if premium_led_entry_allowed(candidate.side, snap):
            counter_floor = min(counter_floor, settings.premium_led_counter_breadth_min_score)
        if trade_score < counter_floor:
            return False, "pretrade_counter_breadth", meta

    from app.engines.expiry_day_guards import expiry_pm_itm_chart_bypass_allowed
    from app.engines.aligned_explosion_bypass import expiry_chart_bypass_for_candidate
    from app.engines.spot_direction import chart_blocks_side

    breadth_bypass = expiry_pm_itm_chart_bypass_allowed(
        candidate.side, snap,
        mode=str(getattr(candidate, "mode", "")),
        state=state, snapshots=snap_map,
    )
    expiry_chart_bypass = expiry_chart_bypass_for_candidate(candidate, snap)
    blocked_chart, chart_reason = chart_blocks_side(
        candidate.side,
        snap.spotChart,
        trade_score=trade_score,
        breadth_aligned_bypass=breadth_bypass,
        premium_led_bypass=premium_bypass,
        expiry_explosion_bypass=expiry_chart_bypass,
    )
    if blocked_chart:
        meta["chartDirection"] = snap.spotChart.direction if snap.spotChart else "NEUTRAL"
        return False, f"pretrade_{chart_reason}", meta

    sym_stats = compute_symbol_stats(trades)
    meta["symbolStats"] = {k: asdict(v) for k, v in sym_stats.items()}

    st = sym_stats.get(candidate.symbol.upper())
    if st and st.trades >= settings.pretrade_min_symbol_trades_for_stats:
        meta["symbolPf"] = st.profit_factor
        meta["symbolNetInr"] = st.net_pnl_inr
        if st.profit_factor < settings.pretrade_block_symbol_pf_below:
            return False, f"pretrade_symbol_pf_{st.profit_factor:.2f}", meta
        if st.net_pnl_inr <= settings.pretrade_block_symbol_net_inr_below:
            return False, f"pretrade_symbol_net_{st.net_pnl_inr:.0f}", meta

    similar = [
        t for t in trades
        if t.symbol == candidate.symbol.upper() and t.side == side_val
    ][-settings.pretrade_similar_side_lookback:]
    if len(similar) >= settings.pretrade_similar_side_min_trades:
        sim_pf = round(_profit_factor(similar), 2)
        meta["similarSidePf"] = sim_pf
        meta["similarSideTrades"] = len(similar)
        if sim_pf < settings.pretrade_block_similar_pf_below:
            return False, f"pretrade_similar_pf_{sim_pf:.2f}", meta

    meta["pretradePassed"] = True
    meta["indexRankBonus"] = index_rank_from_backtest(sym_stats).get(candidate.symbol.upper(), 0)
    return True, "ok", meta


def filter_candidates_pretrade(
    candidates: list[Any],
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> list[Any]:
    """Drop candidates that fail session backtest / controlled gates."""
    _ = snapshots
    if not candidates:
        return []
    session_trades = collect_session_trades(state)
    viable: list[Any] = []
    for c in candidates:
        ok, reason, meta = validate_candidate(c, state, session_trades, snapshots)
        if ok:
            c.pretrade_meta = meta
            viable.append(c)
        else:
            c.pretrade_meta = {"pretradePassed": False, "pretradeBlock": reason, **meta}
    return viable


def backtest_session_summary(trades: list[TradeRecord]) -> dict[str, Any]:
    """Summary for CLI / API — which index would be preferred today."""
    stats = compute_symbol_stats(trades)
    ranks = index_rank_from_backtest(stats)
    return {
        "tradeCount": len(trades),
        "symbolStats": {k: asdict(v) for k, v in stats.items()},
        "indexRankAdjustments": ranks,
        "recommendedIndex": max(ranks, key=ranks.get) if ranks else None,
    }
