"""Per-instrument (symbol+side+strike) cooldown — stops same-trade churn."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")

_cooldown_until: dict[str, datetime] = {}
_entries_today: dict[str, int] = {}
_session_date: str | None = None

_MICRO_WIN_EXITS = frozenset({
    "simple_micro_profit_lock",
    "simple_trail_profit_lock",
    "explosion_micro_profit_lock",
    "explosion_trail_lock",
})


def _instrument_key(symbol: str, side: Side | str, strike: float) -> str:
    side_val = side.value if isinstance(side, Side) else str(side).upper()
    return f"{symbol.upper()}:{side_val}:{int(strike)}"


def _roll_session() -> None:
    global _session_date
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if _session_date != today:
        _session_date = today
        _entries_today.clear()


def record_instrument_entry(symbol: str, side: Side | str, strike: float) -> None:
    _roll_session()
    key = _instrument_key(symbol, side, strike)
    _entries_today[key] = _entries_today.get(key, 0) + 1


def _is_quick_sideways_exit(exit_reason: str) -> bool:
    return bool(exit_reason) and exit_reason.startswith("quick_sideways")


def record_instrument_close(
    symbol: str,
    side: Side | str,
    strike: float,
    pnl_inr: float,
    exit_reason: str = "",
) -> None:
    settings = get_settings()
    key = _instrument_key(symbol, side, strike)
    now = datetime.now(IST)
    secs = 0
    if _is_quick_sideways_exit(exit_reason):
        secs = settings.quick_sideways_instrument_cooldown_seconds
    elif pnl_inr < 0:
        secs = settings.instrument_loss_cooldown_seconds
    elif pnl_inr > 0 and exit_reason in _MICRO_WIN_EXITS:
        secs = settings.instrument_micro_win_cooldown_seconds
    elif pnl_inr > 0:
        secs = settings.instrument_win_cooldown_seconds
    if secs > 0:
        _cooldown_until[key] = now + timedelta(seconds=secs)


def instrument_in_cooldown(symbol: str, side: Side | str, strike: float) -> tuple[bool, str]:
    key = _instrument_key(symbol, side, strike)
    until = _cooldown_until.get(key)
    if not until:
        return False, "ok"
    now = datetime.now(IST)
    if until.tzinfo is None:
        until = until.replace(tzinfo=IST)
    if now < until.astimezone(IST):
        secs = int((until.astimezone(IST) - now).total_seconds())
        return True, f"instrument_cooldown_{key}_{secs}s"
    return False, "ok"


def instrument_daily_cap_reached(symbol: str, side: Side | str, strike: float) -> bool:
    settings = get_settings()
    cap = settings.instrument_max_entries_per_day
    if cap <= 0:
        return False
    _roll_session()
    return _entries_today.get(_instrument_key(symbol, side, strike), 0) >= cap


def instrument_entries_today(symbol: str, side: Side | str, strike: float) -> int:
    _roll_session()
    return _entries_today.get(_instrument_key(symbol, side, strike), 0)


def reset_instrument_cooldowns() -> None:
    global _session_date
    _cooldown_until.clear()
    _entries_today.clear()
    _session_date = None
