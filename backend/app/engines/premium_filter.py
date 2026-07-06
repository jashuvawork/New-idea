"""Option premium (LTP) band filter for tradeable analysis range."""

from app.config import get_settings


def premium_in_band(premium: float | None, *, mode: str = "default") -> bool:
    """True when option LTP is within configured tradeable band."""
    if premium is None or premium <= 0:
        return False
    settings = get_settings()
    max_prem = settings.max_option_premium_inr
    if mode == "explosion" and settings.explosion_max_premium_inr > 0:
        max_prem = max(max_prem, settings.explosion_max_premium_inr)
    return settings.min_option_premium_inr <= premium <= max_prem


def premium_band_label() -> str:
    settings = get_settings()
    return f"₹{settings.min_option_premium_inr:.0f}–₹{settings.max_option_premium_inr:.0f}"


def premium_reject_reason(premium: float | None, *, mode: str = "default") -> str:
    if premium is None or premium <= 0:
        return "missing_premium"
    settings = get_settings()
    max_prem = settings.max_option_premium_inr
    if mode == "explosion" and settings.explosion_max_premium_inr > 0:
        max_prem = max(max_prem, settings.explosion_max_premium_inr)
    if premium < settings.min_option_premium_inr:
        return f"premium_below_{settings.min_option_premium_inr:.0f}"
    if premium > max_prem:
        return f"premium_above_{max_prem:.0f}"
    return "passed"
