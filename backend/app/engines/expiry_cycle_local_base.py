"""Expiry-cycle local base policy — slow post-expiry week vs fast near-expiry moves.

After an index expires, the new weekly chain grinds out fresh local bases (slow spot).
Near expiry (today/tomorrow), spot and premiums move fast — entries must track the
*current* near-base pad, not stale pre-expiry anchors or the far session low.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")

ExpiryCycleRegime = Literal["NEAR_EXPIRY_FAST", "POST_EXPIRY_SLOW", "MID_CYCLE"]

_symbol_chain_expiry: dict[str, str] = {}


def _today() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def days_until_chain_expiry(snap: SymbolSnapshot | None) -> Optional[int]:
    if snap is None or not getattr(snap, "dataAvailable", False):
        return None
    raw = getattr(snap, "optionExpiry", None)
    if not raw:
        return None
    try:
        expiry = datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
        today = datetime.strptime(_today(), "%Y-%m-%d").date()
        return (expiry - today).days
    except ValueError:
        return None


def days_until_chain_expiry_for_symbol(symbol: str) -> Optional[int]:
    sym = str(symbol or "").strip().upper()
    if not sym:
        return None
    raw = _symbol_chain_expiry.get(sym)
    if not raw:
        return None
    try:
        expiry = datetime.strptime(raw[:10], "%Y-%m-%d").date()
        today = datetime.strptime(_today(), "%Y-%m-%d").date()
        return (expiry - today).days
    except ValueError:
        return None


def expiry_cycle_regime(
    snap: SymbolSnapshot | None = None,
    *,
    symbol: str = "",
    settings: Any | None = None,
) -> ExpiryCycleRegime:
    s = settings or get_settings()
    if not bool(getattr(s, "expiry_cycle_local_base_enabled", True)):
        return "MID_CYCLE"
    days = days_until_chain_expiry(snap) if snap is not None else None
    if days is None and symbol:
        days = days_until_chain_expiry_for_symbol(symbol)
    if days is None:
        return "MID_CYCLE"
    near_max = int(getattr(s, "expiry_cycle_near_expiry_max_days", 2) or 2)
    post_min = int(getattr(s, "expiry_cycle_post_expiry_min_days", 4) or 4)
    if days <= near_max:
        return "NEAR_EXPIRY_FAST"
    if days >= post_min:
        return "POST_EXPIRY_SLOW"
    return "MID_CYCLE"


def refresh_symbol_chain_expiry(symbol: str, option_expiry: Any) -> bool:
    """
    Track weekly chain roll — clear stale local-base history when expiry date changes.

    Returns True when the chain rolled (fresh bases must rebuild).
    """
    sym = str(symbol or "").strip().upper()
    if not sym or not option_expiry:
        return False
    expiry = str(option_expiry)[:10]
    prior = _symbol_chain_expiry.get(sym)
    _symbol_chain_expiry[sym] = expiry
    if prior and prior != expiry:
        from app.engines.explosion_detector import reset_local_base_state_for_symbol

        reset_local_base_state_for_symbol(sym)
        return True
    return False


def regime_local_base_window_seconds(
    regime: ExpiryCycleRegime,
    settings: Any | None = None,
) -> int:
    s = settings or get_settings()
    if regime == "NEAR_EXPIRY_FAST":
        return int(getattr(s, "near_expiry_local_base_window_seconds", 1200) or 1200)
    if regime == "POST_EXPIRY_SLOW":
        return int(getattr(s, "post_expiry_local_base_window_seconds", 900) or 900)
    return int(getattr(s, "mid_cycle_local_base_window_seconds", 1800) or 1800)


def resolve_local_base_window_seconds(
    *,
    snap: SymbolSnapshot | None = None,
    symbol: str = "",
    settings: Any | None = None,
) -> int:
    regime = expiry_cycle_regime(snap, symbol=symbol, settings=settings)
    return regime_local_base_window_seconds(regime, settings)


def regime_near_base_max_pad_pct(
    regime: ExpiryCycleRegime,
    settings: Any | None = None,
) -> float:
    s = settings or get_settings()
    if regime == "NEAR_EXPIRY_FAST":
        return float(getattr(s, "near_expiry_near_base_max_pad_pct", 25.0) or 25.0)
    if regime == "POST_EXPIRY_SLOW":
        return float(getattr(s, "post_expiry_near_base_max_pad_pct", 18.0) or 18.0)
    return float(getattr(s, "fresh_near_local_base_max_pct", 10.0) or 10.0)


def regime_local_base_entry_chase_window(
    regime: ExpiryCycleRegime,
    *,
    entry_min: float,
    chase_max: float,
    settings: Any | None = None,
) -> tuple[float, float]:
    """Apply expiry-cycle overrides on top of tier-adaptive entry/chase windows."""
    s = settings or get_settings()
    if regime == "POST_EXPIRY_SLOW":
        entry_min = float(
            getattr(s, "post_expiry_local_base_entry_min_move_pct", 8.0) or 8.0
        )
        chase_max = min(
            chase_max,
            float(getattr(s, "post_expiry_local_base_chase_max_move_pct", 32.0) or 32.0),
        )
    elif regime == "NEAR_EXPIRY_FAST":
        entry_min = max(
            entry_min,
            float(getattr(s, "near_expiry_local_base_entry_min_move_pct", 12.0) or 12.0),
        )
        chase_max = max(
            chase_max,
            float(getattr(s, "near_expiry_local_base_chase_max_move_pct", 48.0) or 48.0),
        )
    return entry_min, chase_max


def near_current_local_base_pad(
    local_pad_pct: float,
    *,
    snap: SymbolSnapshot | None = None,
    symbol: str = "",
    settings: Any | None = None,
) -> bool:
    """True when price is still at the regime's near-base band (not a late chase)."""
    regime = expiry_cycle_regime(snap, symbol=symbol, settings=settings)
    cap = regime_near_base_max_pad_pct(regime, settings)
    return float(local_pad_pct or 0) <= cap + 1e-6


def post_expiry_slow_cold_velocity_waiver(
    *,
    snap: SymbolSnapshot | None = None,
    symbol: str = "",
    local_pad_pct: float = 0.0,
    volume_awakening: bool = False,
    settings: Any | None = None,
) -> bool:
    """Post-expiry week: cold v3 at a fresh near-base is normal — do not require spike first."""
    s = settings or get_settings()
    if not bool(getattr(s, "post_expiry_first_lift_cold_v3_waiver_enabled", True)):
        return False
    if expiry_cycle_regime(snap, symbol=symbol, settings=s) != "POST_EXPIRY_SLOW":
        return False
    if not volume_awakening:
        return False
    return near_current_local_base_pad(
        local_pad_pct, snap=snap, symbol=symbol, settings=s,
    )
