"""WebSocket-only minimal snapshots when Upstox REST is cooling down."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.auto_trader import get_state
from app.models.schemas import MarketPhase, MultiSnapshot, SymbolSnapshot
from app.services.tick_store import get_index_spot
from app.services.upstox import get_market_phase, rate_limit_active, rate_limit_cooldown_remaining
from app.services.upstox_ws import is_ws_active

IST = ZoneInfo("Asia/Kolkata")


def _atm_strike(spot: float, symbol: str) -> float:
    step = 100
    return round(spot / step) * step


def build_ws_index_snapshot(
    *,
    waiting_prefix: Optional[str] = None,
    max_age_seconds: float = 30.0,
) -> Optional[MultiSnapshot]:
    """Index spot from WS ticks — keeps UI live during REST rate-limit cooldown."""
    if not is_ws_active():
        return None

    settings = get_settings()
    now = datetime.now(IST)
    phase_name = get_market_phase()
    try:
        phase = MarketPhase(phase_name)
    except ValueError:
        phase = MarketPhase.LIVE_MARKET

    snapshots: dict[str, SymbolSnapshot] = {}
    for sym in settings.symbols:
        spot = get_index_spot(sym, max_age_seconds=max_age_seconds)
        if spot is None:
            continue
        snapshots[sym] = SymbolSnapshot(
            symbol=sym,
            timestamp=now,
            marketPhase=phase,
            dataAvailable=True,
            spot=spot,
            atmStrike=_atm_strike(spot, sym),
        )

    if not snapshots:
        return None

    waiting_reason = waiting_prefix
    if rate_limit_active():
        secs = int(rate_limit_cooldown_remaining())
        suffix = f"Upstox cooling down — retry in {secs}s · index LTP from WebSocket"
        waiting_reason = f"{waiting_prefix} · {suffix}" if waiting_prefix else suffix

    return MultiSnapshot(
        timestamp=now,
        dataReady=True,
        waitingReason=waiting_reason,
        snapshots=snapshots,
        autoTrader=get_state(),
    )
