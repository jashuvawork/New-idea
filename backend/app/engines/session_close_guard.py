"""Force-flat open live / live-parity legs at the 15:30 IST session close."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import Settings, get_settings
from app.engines.capital_allocator import lot_multiplier
from app.engines.paper_slippage import mark_to_market
from app.services.upstox import get_market_phase

IST = ZoneInfo("Asia/Kolkata")


def _session_close_minute(settings: Settings) -> int:
    return int(settings.power_hour_end_hour) * 60 + int(settings.power_hour_end_minute)


def _minutes_now() -> int:
    from app.engines.replay_clock import ist_minutes_now

    return ist_minutes_now()


def live_session_close_force_exit_applies(settings: Settings | None = None) -> bool:
    """True when auto-trader must flatten at calendar close (live or paper-live parity)."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "live_session_close_force_exit_enabled", True)):
        return False
    if not bool(getattr(settings, "auto_trading_enabled", True)):
        return False
    is_live = bool(getattr(settings, "enable_live_trading", False))
    parity = bool(getattr(settings, "paper_live_parity_enabled", True))
    if not is_live and not parity:
        return False
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    if get_market_phase() not in ("LIVE_MARKET", "POST_MARKET"):
        return False
    return _minutes_now() >= _session_close_minute(settings)


def live_session_close_force_exit(
    trade: Any,
    exit_premium: float,
    lot_mult: int | None = None,
) -> Optional[tuple[str, float]]:
    """Return (exit_reason, pnl_inr) when the trade must flat at session close."""
    settings = get_settings()
    if not live_session_close_force_exit_applies(settings):
        return None
    mult = lot_mult if lot_mult is not None else lot_multiplier(trade.symbol)
    _pts, pnl_inr = mark_to_market(
        float(trade.entryPremium or 0),
        float(exit_premium),
        int(trade.lots or 0),
        mult,
    )
    return "live_session_market_close", pnl_inr
