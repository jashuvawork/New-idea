"""IST session entry window — avoid first-minute open chaos."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.services.upstox import get_market_phase

IST = ZoneInfo("Asia/Kolkata")


def entry_earliest_minutes() -> int:
    settings = get_settings()
    return settings.entry_earliest_hour * 60 + settings.entry_earliest_minute


def entries_allowed_now() -> tuple[bool, str]:
    """False until configured IST time (default 09:16) during live market."""
    phase = get_market_phase()
    if phase != "LIVE_MARKET":
        return False, "market_not_live"

    now = datetime.now(IST)
    current = now.hour * 60 + now.minute
    earliest = entry_earliest_minutes()
    if current < earliest:
        settings = get_settings()
        label = f"{settings.entry_earliest_hour:02d}:{settings.entry_earliest_minute:02d}"
        return False, f"before_entry_window_{label}_IST"
    return True, "ok"


def entry_window_label() -> str:
    settings = get_settings()
    return f"{settings.entry_earliest_hour:02d}:{settings.entry_earliest_minute:02d} IST"
