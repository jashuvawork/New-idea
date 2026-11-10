"""Option premium (LTP) band filter for tradeable analysis range."""

from typing import Any

from app.config import get_settings


def _symbol_from_context(snap: Any = None, symbol: str | None = None) -> str:
    if symbol:
        return str(symbol).strip().upper()
    if snap is not None:
        return str(getattr(snap, "symbol", "") or "").strip().upper()
    return ""


def resolve_premium_band_limits(
    *,
    mode: str = "default",
    peak_move_pct: float = 0.0,
    snap: Any = None,
    symbol: str | None = None,
    settings: Any = None,
) -> tuple[float, float]:
    """Return (min_premium_inr, max_premium_inr) for symbol and mode."""
    settings = settings or get_settings()
    sym = _symbol_from_context(snap, symbol)
    if sym == "SENSEX":
        min_prem = float(getattr(settings, "sensex_min_option_premium_inr", 18.0) or 18.0)
        max_prem = float(getattr(settings, "sensex_max_option_premium_inr", 650.0) or 650.0)
        sensex_fixed_cap = True
    else:
        min_prem = float(getattr(settings, "min_option_premium_inr", 18.0) or 18.0)
        max_prem = float(getattr(settings, "max_option_premium_inr", 350.0) or 350.0)
        from app.engines.nifty_expiry_sensex_parity import (
            resolve_nifty_expiry_max_premium_inr,
            resolve_nifty_expiry_min_premium_inr,
        )

        max_prem = resolve_nifty_expiry_max_premium_inr(
            default_max=max_prem, snap=snap, settings=settings
        )
        min_prem = resolve_nifty_expiry_min_premium_inr(
            default_min=min_prem, snap=snap, settings=settings
        )
        sensex_fixed_cap = False
        if mode == "explosion" and float(getattr(settings, "explosion_max_premium_inr", 0) or 0) > 0:
            max_prem = max(
                max_prem,
                float(getattr(settings, "explosion_max_premium_inr", 0) or 0),
            )

    if snap is not None and mode == "explosion":
        try:
            from app.engines.expiry_day_guards import is_symbol_expiry_day

            if is_symbol_expiry_day(snap):
                expiry_floor = float(
                    getattr(settings, "expiry_day_min_option_premium_inr", 15.0) or 15.0
                )
                min_prem = min(min_prem, expiry_floor)
                min_prem = resolve_nifty_expiry_min_premium_inr(
                    default_min=min_prem, snap=snap, settings=settings
                )
        except Exception:
            pass

    if mode == "explosion":
        cheap_min = float(getattr(settings, "explosion_cheap_rip_min_premium_inr", 12.0) or 12.0)
        cheap_peak = float(getattr(settings, "explosion_cheap_rip_min_peak_pct", 28.0) or 28.0)
        try:
            from app.engines.session_timing import in_open_premium_window

            if in_open_premium_window():
                cheap_min = min(
                    cheap_min,
                    float(
                        getattr(settings, "expiry_open_cheap_premium_min_inr", 10.0) or 10.0
                    ),
                    float(
                        getattr(settings, "explosion_open_cheap_rip_min_premium_inr", 10.0)
                        or 10.0
                    ),
                )
                cheap_peak = min(
                    cheap_peak,
                    float(
                        getattr(settings, "expiry_open_cheap_rip_min_peak_pct", 15.0) or 15.0
                    ),
                )
        except Exception:
            pass
        if peak_move_pct >= cheap_peak:
            min_prem = min(min_prem, cheap_min)
        if not sensex_fixed_cap:
            ict_ceil = float(getattr(settings, "explosion_ict_max_premium_inr", 0) or 0)
            if ict_ceil > max_prem and peak_move_pct >= 28.0:
                max_prem = max(max_prem, ict_ceil)

    return min_prem, max_prem


def premium_in_band(
    premium: float | None,
    *,
    mode: str = "default",
    peak_move_pct: float = 0.0,
    snap: Any = None,
    symbol: str | None = None,
    settings: Any = None,
) -> bool:
    """True when option LTP is within configured tradeable band."""
    if premium is None or premium <= 0:
        return False
    min_prem, max_prem = resolve_premium_band_limits(
        mode=mode,
        peak_move_pct=peak_move_pct,
        snap=snap,
        symbol=symbol,
        settings=settings,
    )
    return min_prem <= premium <= max_prem


def premium_band_label() -> str:
    settings = get_settings()
    return f"₹{settings.min_option_premium_inr:.0f}–₹{settings.max_option_premium_inr:.0f}"


def premium_reject_reason(
    premium: float | None,
    *,
    mode: str = "default",
    peak_move_pct: float = 0.0,
    snap: Any = None,
    symbol: str | None = None,
) -> str:
    if premium is None or premium <= 0:
        return "missing_premium"
    min_prem, max_prem = resolve_premium_band_limits(
        mode=mode,
        peak_move_pct=peak_move_pct,
        snap=snap,
        symbol=symbol,
    )
    if premium < min_prem:
        return f"premium_below_{min_prem:.0f}"
    if premium > max_prem:
        return f"premium_above_{max_prem:.0f}"
    return "passed"
