"""IST session entry window — avoid first-minute open chaos."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.services.upstox import get_market_phase

IST = ZoneInfo("Asia/Kolkata")


def _minutes_now() -> int:
    now = datetime.now(IST)
    return now.hour * 60 + now.minute


def entry_earliest_minutes() -> int:
    settings = get_settings()
    return settings.entry_earliest_hour * 60 + settings.entry_earliest_minute


def open_caution_until_minutes() -> int:
    settings = get_settings()
    return settings.open_caution_until_hour * 60 + settings.open_caution_until_minute


def entries_allowed_now() -> tuple[bool, str]:
    """False until configured IST time (default 09:20) during live market."""
    phase = get_market_phase()
    if phase != "LIVE_MARKET":
        return False, "market_not_live"

    current = _minutes_now()
    earliest = entry_earliest_minutes()
    if current < earliest:
        settings = get_settings()
        label = f"{settings.entry_earliest_hour:02d}:{settings.entry_earliest_minute:02d}"
        return False, f"before_entry_window_{label}_IST"
    return True, "ok"


def in_open_caution_window() -> bool:
    """09:20–09:30 IST — stricter explosion gates while opening range forms."""
    if get_market_phase() != "LIVE_MARKET":
        return False
    current = _minutes_now()
    return entry_earliest_minutes() <= current < open_caution_until_minutes()


def min_explosion_score_now() -> int:
    settings = get_settings()
    if in_open_caution_window():
        return max(settings.aggressive_min_explosion_score, settings.open_caution_min_explosion_score)
    return settings.aggressive_min_explosion_score


def entry_window_label() -> str:
    settings = get_settings()
    return f"{settings.entry_earliest_hour:02d}:{settings.entry_earliest_minute:02d} IST"
