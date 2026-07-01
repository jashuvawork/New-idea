"""Pre-trade validation — session backtest stats, index selection, controlled entry gates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import AutoTraderState, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


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


def _paper_trade_records(state: AutoTraderState) -> list[TradeRecord]:
    out: list[TradeRecord] = []
    for t in state.closedPaperTrades:
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
    records = _paper_trade_records(state)
    seen = {r.trade_id for r in records if r.trade_id}
    today = datetime.now(IST).strftime("%Y-%m-%d")

    try:
        from app.services import trade_store

        day = trade_store.get_day_detail(today)
        for row in day.get("trades", []):
            if row.get("status") != "CLOSED":
                continue
            tid = str(row.get("id", ""))
            if tid and tid in seen:
                continue
            records.append(TradeRecord(
                symbol=str(row.get("symbol", "")).upper(),
                side=str(row.get("side", "")).upper(),
                pnl_inr=float(row.get("pnlInr") or 0),
                exit_reason=str(row.get("exitReason") or ""),
                strike=float(row.get("strike") or 0),
                trade_id=tid,
            ))
    except Exception:
        pass

    return records


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


def check_min_entry_interval(state: AutoTraderState, *, chop: bool = False) -> tuple[bool, str]:
    settings = get_settings()
    last = state.lastExit
    if not last or not last.get("at"):
        return True, "ok"
    try:
        closed = datetime.fromisoformat(str(last["at"]).replace("Z", "+00:00")).astimezone(IST)
    except Exception:
        return True, "ok"

    gap = settings.min_seconds_between_entries
    if chop:
        gap = max(gap, settings.chop_session_entry_interval_seconds)
    gap = max(gap, settings.post_exit_min_seconds)
    pnl = float(last.get("pnlInr", 0) or 0)
    if pnl < 0:
        gap = max(gap, settings.post_loss_exit_min_seconds)

    elapsed = (datetime.now(IST) - closed).total_seconds()
    if elapsed < gap:
        remain = int(gap - elapsed)
        suffix = "after_loss" if pnl < 0 else "after_exit"
        return False, f"pretrade_entry_interval_{suffix}_{remain}s"
    return True, "ok"


def controlled_daily_cap_reached(state: AutoTraderState) -> tuple[bool, str]:
    settings = get_settings()
    if not settings.controlled_trading_enabled:
        return False, "ok"
    cap = settings.controlled_max_trades_per_day
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


def check_last_n_trades_pause(state: AutoTraderState) -> tuple[bool, str, dict[str, Any]]:
    """Session-level pause when last N trades are catastrophic (e.g. 4/5 losses)."""
    settings = get_settings()
    if not settings.last_n_trades_gate_enabled:
        return False, "ok", {}

    trades = collect_session_trades(state)
    if len(trades) < settings.last_n_trades_min_count:
        return False, "ok", last_n_trades_summary(state)

    summary = analyze_last_n_trades(trades, settings.last_n_trades_lookback)
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

    ok, reason = check_min_entry_interval(state, chop=chop)
    if not ok:
        return False, reason, meta

    cap_hit, cap_reason = controlled_daily_cap_reached(state)
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
    dir_blocked, dir_reason = check_directional_side_lock(sym, candidate.side, snap, tier=tier)
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
        candidate.snap,
        mode=str(getattr(candidate, "mode", "scalp")),
        candidate_score=float(getattr(candidate, "score", 0) or 0),
        snapshots=snap_map,
    )
    meta.update(mn_meta)
    if not mn_ok:
        return False, mn_reason, meta

    from app.engines.expiry_day_guards import check_expiry_candidate, expiry_min_rank_score

    ex_ok, ex_reason, ex_meta = check_expiry_candidate(candidate, state, snap_map)
    meta.update(ex_meta)
    if not ex_ok:
        return False, ex_reason, meta

    expiry_floor = expiry_min_rank_score(state, snap_map)
    min_rank = max(settings.pretrade_min_rank_score, expiry_floor)
    if candidate.score < min_rank:
        return False, f"pretrade_rank_below_{min_rank:.0f}", meta

    side_val = candidate.side.value if isinstance(candidate.side, Side) else str(candidate.side).upper()
    snap: SymbolSnapshot = candidate.snap

    from app.engines.symbol_cooldown import side_aligned_with_breadth

    trade_score = max(candidate.tqs or 0, candidate.confidence or 0, candidate.score)

    if not side_aligned_with_breadth(side_val, snap.breadth.bias):
        if trade_score < settings.counter_breadth_min_score:
            return False, "pretrade_counter_breadth", meta

    from app.engines.spot_direction import chart_blocks_side

    blocked_chart, chart_reason = chart_blocks_side(
        candidate.side,
        snap.spotChart,
        trade_score=trade_score,
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
