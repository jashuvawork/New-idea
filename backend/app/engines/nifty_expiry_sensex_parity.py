"""NIFTY weekly/monthly expiry — mirror SENSEX expiry book (ATM/ITM, band, scan, stops)."""

from __future__ import annotations

from typing import Any


def _strict_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    return default


def nifty_expiry_sensex_parity_enabled(settings: Any = None) -> bool:
    from app.config import get_settings

    settings = settings or get_settings()
    return _strict_bool(
        getattr(settings, "nifty_expiry_sensex_parity_enabled", False),
        default=False,
    )


def nifty_expiry_itm_atm_only(symbol: str, *, settings: Any = None) -> bool:
    """True when NIFTY should use SENSEX-style all-OTM block on expiry (not ₹18–80 band only)."""
    if str(symbol or "").upper() != "NIFTY":
        return False
    if not nifty_expiry_sensex_parity_enabled(settings):
        return False
    return bool(getattr(settings, "nifty_expiry_itm_atm_only_enabled", True))


def resolve_nifty_expiry_max_premium_inr(
    *,
    default_max: float,
    snap: Any = None,
    settings: Any = None,
) -> float:
    if snap is None or not nifty_expiry_sensex_parity_enabled(settings):
        return default_max
    from app.engines.expiry_day_guards import is_symbol_expiry_day

    sym = str(getattr(snap, "symbol", "") or "").upper()
    if sym != "NIFTY" or not is_symbol_expiry_day(snap):
        return default_max
    from app.config import get_settings

    settings = settings or get_settings()
    return float(
        getattr(settings, "nifty_expiry_max_option_premium_inr", 650.0) or 650.0
    )


def resolve_nifty_expiry_itm_scan_range(
    symbol: str,
    *,
    settings: Any = None,
) -> float | None:
    if str(symbol or "").upper() != "NIFTY" or not nifty_expiry_sensex_parity_enabled(settings):
        return None
    from app.config import get_settings

    settings = settings or get_settings()
    return float(getattr(settings, "expiry_nifty_itm_scan_range", 1200.0) or 1200.0)


def resolve_nifty_expiry_stop_abs_max_points(
    symbol: str,
    snap: Any = None,
    *,
    settings: Any = None,
) -> float | None:
    """SENSEX 40pt × 20 lots ≈ ₹800; NIFTY parity uses ~12pt × 65 ≈ ₹780 on expiry."""
    if str(symbol or "").upper() != "NIFTY" or not nifty_expiry_sensex_parity_enabled(settings):
        return None
    from app.engines.expiry_day_guards import is_symbol_expiry_day

    if snap is None or not is_symbol_expiry_day(snap):
        return None
    from app.config import get_settings

    settings = settings or get_settings()
    return float(getattr(settings, "nifty_expiry_stop_abs_max_points", 12.0) or 12.0)
