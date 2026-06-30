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


def check_min_entry_interval(state: AutoTraderState) -> tuple[bool, str]:
    settings = get_settings()
    gap = settings.min_seconds_between_entries
    if gap <= 0:
        return True, "ok"
    elapsed = seconds_since_last_exit(state)
    if elapsed < gap:
        remain = int(gap - elapsed)
        return False, f"pretrade_entry_interval_{remain}s"
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


def validate_candidate(
    candidate: Any,
    state: AutoTraderState,
    session_trades: Optional[list[TradeRecord]] = None,
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

    ok, reason = check_min_entry_interval(state)
    if not ok:
        return False, reason, meta

    cap_hit, cap_reason = controlled_daily_cap_reached(state)
    if cap_hit:
        return False, cap_reason, meta

    if candidate.score < settings.pretrade_min_rank_score:
        return False, f"pretrade_rank_below_{settings.pretrade_min_rank_score}", meta

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
        ok, reason, meta = validate_candidate(c, state, session_trades)
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
