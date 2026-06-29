"""Chop-day guardrails — Jun 25 playbook for RANGE_BOUND / NEUTRAL sessions."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import AutoTraderState, SymbolSnapshot
from app.services.upstox import get_market_phase

IST = ZoneInfo("Asia/Kolkata")

_session_loss_streak: int = 0
_pause_until: Optional[datetime] = None
_session_date: Optional[str] = None


def _reset_session_if_new_day() -> None:
    global _session_loss_streak, _pause_until, _session_date
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if _session_date != today:
        _session_date = today
        _session_loss_streak = 0
        _pause_until = None


def record_session_trade_close(pnl_inr: float) -> None:
    """Global loss streak — pause new entries after N consecutive losses."""
    global _session_loss_streak, _pause_until
    settings = get_settings()
    if not settings.chop_day_guards_enabled:
        return
    _reset_session_if_new_day()
    if pnl_inr < -50:
        _session_loss_streak += 1
        if _session_loss_streak >= settings.loss_streak_pause_count:
            _pause_until = datetime.now(IST) + timedelta(seconds=settings.loss_streak_pause_seconds)
    elif pnl_inr > 50:
        _session_loss_streak = 0


def session_pause_active() -> tuple[bool, str]:
    settings = get_settings()
    if not settings.chop_day_guards_enabled:
        return False, "ok"
    _reset_session_if_new_day()
    if _pause_until is None:
        return False, "ok"
    now = datetime.now(IST)
    until = _pause_until if _pause_until.tzinfo else _pause_until.replace(tzinfo=IST)
    if now < until.astimezone(IST):
        secs = int((until.astimezone(IST) - now).total_seconds())
        return True, f"loss_streak_pause_{secs}s"
    return False, "ok"


def reset_session_guards() -> None:
    global _session_loss_streak, _pause_until, _session_date
    _session_loss_streak = 0
    _pause_until = None
    _session_date = None


def is_chop_session(snapshots: dict[str, SymbolSnapshot]) -> bool:
    """Majority NEUTRAL breadth or RANGE_BOUND regime → chop day rules."""
    settings = get_settings()
    if not settings.chop_day_guards_enabled:
        return False
    live = [s for s in snapshots.values() if s.dataAvailable]
    if not live:
        return False
    neutral = sum(1 for s in live if (s.breadth.bias or "NEUTRAL").upper() == "NEUTRAL")
    range_bound = sum(
        1 for s in live
        if str(s.regime.value if hasattr(s.regime, "value") else s.regime) == "RANGE_BOUND"
    )
    n = len(live)
    return neutral >= max(1, n // 2) or range_bound >= max(1, (2 * n) // 3)


def _minutes_now() -> int:
    now = datetime.now(IST)
    return now.hour * 60 + now.minute


def before_primary_window() -> bool:
    settings = get_settings()
    start = settings.primary_window_start_hour * 60 + settings.primary_window_start_minute
    return _minutes_now() < start


def daily_trade_cap(state: AutoTraderState, snapshots: dict[str, SymbolSnapshot]) -> tuple[int, str]:
    """Max closed trades allowed today under chop rules."""
    settings = get_settings()
    if not settings.chop_day_guards_enabled or not is_chop_session(snapshots):
        return 999, "normal"
    if before_primary_window():
        return settings.daily_max_trades_pre10_chop, "pre10_chop"
    return settings.daily_max_trades_chop, "chop_day"


def trades_cap_reached(state: AutoTraderState, snapshots: dict[str, SymbolSnapshot]) -> tuple[bool, str]:
    cap, label = daily_trade_cap(state, snapshots)
    closed = len(state.closedPaperTrades)
    if closed >= cap:
        return True, f"daily_trade_cap_{closed}>={cap}_{label}"
    return False, "ok"


def neutral_breadth_blocks_entry(
    breadth_bias: str,
    trade_score: float,
    velocity_pct: float = 0.0,
    *,
    explosion: bool = False,
) -> tuple[bool, str]:
    """Block NEUTRAL chop unless score/velocity prove edge."""
    settings = get_settings()
    if not settings.chop_day_guards_enabled:
        return False, "ok"
    if (breadth_bias or "NEUTRAL").upper() != "NEUTRAL":
        return False, "ok"
    min_score = settings.neutral_breadth_min_score
    if explosion and velocity_pct >= settings.explosion_early_velocity_3s:
        min_score = min(min_score, settings.neutral_breadth_explosion_min_score)
    if trade_score >= min_score:
        return False, "ok"
    return True, f"neutral_breadth_score_below_{min_score}"


def symbol_rank_adjustment(symbol: str, chop: bool) -> float:
    settings = get_settings()
    if not settings.chop_day_guards_enabled or not chop:
        return 0.0
    sym = symbol.upper()
    if sym == "SENSEX":
        return settings.sensex_rank_bonus
    if sym == "NIFTY":
        return -settings.nifty_rank_penalty_chop
    return 0.0


def min_rank_for_entry(chop: bool) -> float:
    settings = get_settings()
    from app.engines.session_timing import in_open_caution_window

    if in_open_caution_window():
        return settings.open_caution_min_rank_score
    if chop and before_primary_window():
        return settings.pre10_chop_min_rank_score
    return 0.0


def apply_tiered_lot_cap(
    lots: int,
    rank_score: float,
    breadth_aligned: bool,
    symbol: str,
) -> int:
    """40 lots high conviction; 20 mid; skip handled upstream via rank gate."""
    settings = get_settings()
    if not settings.chop_day_guards_enabled:
        return lots
    from app.engines.session_timing import in_midday_chop_window

    high = settings.chop_lots_high
    mid = settings.chop_lots_mid
    min_rank = settings.chop_lots_min_rank

    cap = high
    if rank_score < settings.chop_lots_high_min_rank or not breadth_aligned:
        cap = mid
    if rank_score < min_rank:
        cap = 0
    if in_midday_chop_window() and rank_score < settings.chop_lots_high_min_rank:
        cap = min(cap, mid)

    if cap <= 0:
        return 0
    return min(lots, cap)


def chop_guard_summary(state: AutoTraderState, snapshots: dict[str, SymbolSnapshot]) -> dict:
    chop = is_chop_session(snapshots)
    cap, cap_label = daily_trade_cap(state, snapshots)
    paused, pause_reason = session_pause_active()
    cap_hit, cap_msg = trades_cap_reached(state, snapshots)
    return {
        "chopSession": chop,
        "dailyTradeCap": cap,
        "dailyTradeCapLabel": cap_label,
        "closedTrades": len(state.closedPaperTrades),
        "tradeCapReached": cap_hit,
        "lossStreak": _session_loss_streak,
        "sessionPaused": paused,
        "pauseReason": pause_reason if paused else None,
        "beforePrimaryWindow": before_primary_window(),
    }
