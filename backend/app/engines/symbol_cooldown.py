"""Per-symbol cooldown and re-entry quality after losses."""

from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from app.config import get_settings

IST = ZoneInfo("Asia/Kolkata")

_cooldown_until: dict[str, datetime] = {}
_consecutive_losses: dict[str, int] = {}
_last_win_at: dict[str, Optional[datetime]] = {}

_EMERGENCY_EXITS = frozenset({
    "simple_emergency_inr_stop",
    "explosion_emergency_stop",
    "explosion_stop_loss",
    "simple_stop_loss",
    "adaptive_sl",
})


def record_symbol_result(symbol: str, pnl_inr: float, exit_reason: str = "") -> None:
    """Track wins/losses per symbol for cooldown and re-entry gates."""
    settings = get_settings()
    sym = symbol.upper()
    now = datetime.now(IST)

    if pnl_inr < 0:
        streak = _consecutive_losses.get(sym, 0) + 1
        _consecutive_losses[sym] = streak
        cooldown = settings.symbol_loss_cooldown_seconds
        if exit_reason in _EMERGENCY_EXITS:
            cooldown = max(cooldown, settings.symbol_emergency_cooldown_seconds)
        if streak >= 2:
            cooldown = max(cooldown, settings.symbol_streak_cooldown_seconds)
        _cooldown_until[sym] = now + timedelta(seconds=cooldown)
    elif pnl_inr > 0:
        _consecutive_losses[sym] = 0
        _last_win_at[sym] = now


def symbol_in_cooldown(symbol: str) -> tuple[bool, str]:
    sym = symbol.upper()
    until = _cooldown_until.get(sym)
    if not until:
        return False, "ok"
    now = datetime.now(IST)
    if until.tzinfo is None:
        until = until.replace(tzinfo=IST)
    if now < until.astimezone(IST):
        secs = int((until.astimezone(IST) - now).total_seconds())
        return True, f"symbol_cooldown_{sym}_{secs}s"
    return False, "ok"


def entry_score_penalty(symbol: str) -> int:
    """Extra explosion/TQS points required after recent losses on this symbol."""
    settings = get_settings()
    streak = _consecutive_losses.get(symbol.upper(), 0)
    return streak * settings.reentry_score_penalty_per_loss


def recent_win_rank_bonus(symbol: str) -> float:
    """Prefer symbols that just produced a winner."""
    settings = get_settings()
    won = _last_win_at.get(symbol.upper())
    if not won:
        return 0.0
    if won.tzinfo is None:
        won = won.replace(tzinfo=IST)
    age = (datetime.now(IST) - won.astimezone(IST)).total_seconds()
    if age <= settings.recent_win_window_seconds:
        return settings.recent_win_rank_bonus
    return 0.0


def requires_breadth_alignment(symbol: str) -> bool:
    """After a loss on this symbol, demand breadth alignment before re-entry."""
    return _consecutive_losses.get(symbol.upper(), 0) >= 1


def side_aligned_with_breadth(side: str, breadth_bias: str) -> bool:
    """CALL needs BULLISH/NEUTRAL; PUT needs BEARISH/NEUTRAL."""
    bias = (breadth_bias or "NEUTRAL").upper()
    if bias == "NEUTRAL":
        return True
    if side.upper() == "CALL":
        return bias == "BULLISH"
    return bias == "BEARISH"


def reset_symbol_cooldowns() -> None:
    _cooldown_until.clear()
    _consecutive_losses.clear()
    _last_win_at.clear()
    from app.engines.instrument_cooldown import reset_instrument_cooldowns

    reset_instrument_cooldowns()
