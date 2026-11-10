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
    """Near-strike expiry book — do not copy SENSEX ₹650; typical NIFTY LTP is <₹200."""
    if snap is None or not nifty_expiry_sensex_parity_enabled(settings):
        return default_max
    from app.engines.expiry_day_guards import is_symbol_expiry_day

    sym = str(getattr(snap, "symbol", "") or "").upper()
    if sym != "NIFTY" or not is_symbol_expiry_day(snap):
        return default_max
    from app.config import get_settings

    settings = settings or get_settings()
    near_cap = float(
        getattr(settings, "nifty_expiry_max_option_premium_inr", 0.0) or 0.0
    )
    if near_cap <= 0:
        near_cap = float(
            getattr(settings, "expiry_near_expiry_premium_max_inr", 300.0) or 300.0
        )
    # Only lift a tight book ceiling (e.g. legacy ₹175 profiles); never chase SENSEX ₹650.
    return max(default_max, near_cap)


def resolve_nifty_expiry_min_premium_inr(
    *,
    default_min: float,
    snap: Any = None,
    settings: Any = None,
) -> float:
    """Allow sub-₹18 coil near base on expiry (e.g. 15→103 CE) when parity replaces cheap OTM."""
    if snap is None or not nifty_expiry_sensex_parity_enabled(settings):
        return default_min
    from app.engines.expiry_day_guards import is_symbol_expiry_day

    sym = str(getattr(snap, "symbol", "") or "").upper()
    if sym != "NIFTY" or not is_symbol_expiry_day(snap):
        return default_min
    from app.config import get_settings

    settings = settings or get_settings()
    floor = float(
        getattr(settings, "nifty_expiry_min_option_premium_inr", 10.0) or 10.0
    )
    expiry_floor = float(
        getattr(settings, "expiry_day_min_option_premium_inr", 15.0) or 15.0
    )
    return min(default_min, floor, expiry_floor)


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
