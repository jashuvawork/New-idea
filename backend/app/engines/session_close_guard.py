"""Force-flat open auto-trader legs at live_session_close (default 15:35 IST)."""

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
    return (
        int(getattr(settings, "live_session_close_force_exit_hour", 15)) * 60
        + int(getattr(settings, "live_session_close_force_exit_minute", 35))
    )


def _minutes_now() -> int:
    from app.engines.replay_clock import ist_minutes_now

    return ist_minutes_now()


def _trade_ist_session_date(trade: Any) -> Optional[str]:
    raw = getattr(trade, "sessionDate", None)
    if raw:
        return str(raw)[:10]
    opened = getattr(trade, "openedAt", None)
    if opened is None:
        return None
    if isinstance(opened, datetime):
        dt = opened.astimezone(IST) if opened.tzinfo else opened.replace(tzinfo=IST)
        return dt.strftime("%Y-%m-%d")
    try:
        return datetime.fromisoformat(str(opened)).astimezone(IST).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _phase_allows_session_close(phase: str, trade: Any | None, now: datetime) -> bool:
    if phase in ("LIVE_MARKET", "POST_MARKET"):
        return True
    if phase != "CLOSED" or trade is None:
        return False
    # Same-day recovery after 16:00 when flatten was missed (undeployed guard, stale feed, etc.).
    sess = _trade_ist_session_date(trade)
    return bool(sess and sess == now.strftime("%Y-%m-%d"))


def live_session_close_force_exit_applies(
    settings: Settings | None = None,
    trade: Any | None = None,
) -> bool:
    """True when auto-trader must flatten at the session-close cutoff."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "live_session_close_force_exit_enabled", True)):
        return False
    if not bool(getattr(settings, "auto_trading_enabled", True)):
        return False
    is_live = bool(getattr(settings, "enable_live_trading", False))
    parity = bool(getattr(settings, "paper_live_parity_enabled", True))
    paper = bool(getattr(settings, "paper_trading", False))
    if not is_live and not parity and not paper:
        return False
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return False
    if _minutes_now() < _session_close_minute(settings):
        return False
    phase = get_market_phase()
    return _phase_allows_session_close(phase, trade, now)


def live_session_close_force_exit(
    trade: Any,
    exit_premium: float,
    lot_mult: int | None = None,
) -> Optional[tuple[str, float]]:
    """Return (exit_reason, pnl_inr) when the trade must flat at session close."""
    settings = get_settings()
    if not live_session_close_force_exit_applies(settings, trade=trade):
        return None
    mult = lot_mult if lot_mult is not None else lot_multiplier(trade.symbol)
    _pts, pnl_inr = mark_to_market(
        float(trade.entryPremium or 0),
        float(exit_premium),
        int(trade.lots or 0),
        mult,
    )
    return "live_session_market_close", pnl_inr
