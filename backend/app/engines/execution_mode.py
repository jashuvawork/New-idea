"""Live vs paper execution flags.

Daily loss stop and risk safe mode pause **new entries** only. They must not
flip the broker execution mode back to paper while live remains armed on EC2.
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings


def live_broker_execution_enabled(settings=None) -> bool:
    s = settings if settings is not None else get_settings()
    return bool(getattr(s, "enable_live_trading", False)) and bool(
        getattr(s, "auto_trading_enabled", True)
    )


def paper_execution_active(settings=None) -> bool:
    if live_broker_execution_enabled(settings):
        return False
    s = settings if settings is not None else get_settings()
    return bool(getattr(s, "paper_trading", True))


def execution_mode_label(settings=None) -> str:
    if live_broker_execution_enabled(settings):
        return "LIVE"
    s = settings if settings is not None else get_settings()
    if getattr(s, "paper_live_parity_enabled", False):
        return "PAPER_LIVE_PARITY"
    return "PAPER"


def sync_autotrader_execution_flags(state: Any, settings=None) -> None:
    """Keep HUD/API honest when ENABLE_LIVE_TRADING=true but PAPER_TRADING drifted."""
    s = settings if settings is not None else get_settings()
    live = bool(getattr(s, "enable_live_trading", False))
    auto = bool(getattr(s, "auto_trading_enabled", True))
    state.liveTradingEnabled = live
    state.autoTradingEnabled = auto
    if live and auto:
        state.paperTrading = False
    else:
        state.paperTrading = bool(getattr(s, "paper_trading", True))
