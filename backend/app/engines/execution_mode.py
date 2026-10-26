"""Live vs paper execution flags.

Daily loss stop and risk safe mode pause **new entries** only. They must not
flip the broker execution mode back to paper while live remains armed on EC2.
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings


def live_broker_armed(settings=None) -> bool:
    """Live broker env is armed (ENABLE_LIVE_TRADING). Independent of entry pause."""
    s = settings if settings is not None else get_settings()
    return bool(getattr(s, "enable_live_trading", False))


def live_broker_execution_enabled(settings=None) -> bool:
    """Live broker may place new orders (armed + auto-trader loop enabled)."""
    s = settings if settings is not None else get_settings()
    return live_broker_armed(s) and bool(getattr(s, "auto_trading_enabled", True))


def paper_execution_active(settings=None) -> bool:
    if live_broker_armed(settings):
        return False
    s = settings if settings is not None else get_settings()
    return bool(getattr(s, "paper_trading", True))


def paper_live_parity_active(settings=None) -> bool:
    """Paper book uses simulated broker flow — same entry path as live, not legacy shadow fills."""
    s = settings if settings is not None else get_settings()
    if live_broker_armed(s):
        return False
    return (
        bool(getattr(s, "paper_live_parity_enabled", True))
        and bool(getattr(s, "paper_simulate_broker_orders", True))
        and bool(getattr(s, "paper_trading", True))
    )


def live_entry_gates_active(settings=None) -> bool:
    """Entry gates that must match between live and paper-live-parity rehearsal."""
    s = settings if settings is not None else get_settings()
    if live_broker_execution_enabled(s):
        return True
    if not bool(getattr(s, "paper_mirror_live_entry_gates", True)):
        return False
    return paper_live_parity_active(s)


def execution_mode_label(settings=None) -> str:
    if live_broker_armed(settings):
        return "LIVE"
    s = settings if settings is not None else get_settings()
    if getattr(s, "paper_live_parity_enabled", False):
        return "PAPER_LIVE_PARITY"
    return "PAPER"


def sync_autotrader_execution_flags(state: Any, settings=None) -> None:
    """Keep HUD/API honest when ENABLE_LIVE_TRADING=true but PAPER_TRADING drifted."""
    s = settings if settings is not None else get_settings()
    live = live_broker_armed(s)
    auto = bool(getattr(s, "auto_trading_enabled", True))
    state.liveTradingEnabled = live
    state.autoTradingEnabled = auto
    if live:
        state.paperTrading = False
    else:
        state.paperTrading = bool(getattr(s, "paper_trading", True))
