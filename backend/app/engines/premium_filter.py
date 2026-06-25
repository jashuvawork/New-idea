"""Option premium (LTP) band filter for tradeable analysis range."""

from app.config import get_settings


def premium_in_band(premium: float | None) -> bool:
    """True when option LTP is within configured tradeable band (default ₹25–175)."""
    if premium is None or premium <= 0:
        return False
    settings = get_settings()
    return settings.min_option_premium_inr <= premium <= settings.max_option_premium_inr


def premium_band_label() -> str:
    settings = get_settings()
    return f"₹{settings.min_option_premium_inr:.0f}–₹{settings.max_option_premium_inr:.0f}"


def premium_reject_reason(premium: float | None) -> str:
    if premium is None or premium <= 0:
        return "missing_premium"
    settings = get_settings()
    if premium < settings.min_option_premium_inr:
        return f"premium_below_{settings.min_option_premium_inr:.0f}"
    if premium > settings.max_option_premium_inr:
        return f"premium_above_{settings.max_option_premium_inr:.0f}"
    return "passed"
