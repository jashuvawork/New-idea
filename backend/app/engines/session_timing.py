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
    """False until configured IST time (default 09:20) during live market — skips open auction."""
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


def explosion_entries_allowed_now() -> tuple[bool, str]:
    """9:15–09:20 IST — explosion-only window before general entries."""
    settings = get_settings()
    if not settings.explosion_open_entry_enabled:
        return False, "explosion_open_entry_disabled"
    if get_market_phase() != "LIVE_MARKET":
        return False, "market_not_live"

    current = _minutes_now()
    explosion_start = settings.explosion_entry_earliest_hour * 60 + settings.explosion_entry_earliest_minute
    general_start = entry_earliest_minutes()
    if explosion_start <= current < general_start:
        label = f"{settings.explosion_entry_earliest_hour:02d}:{settings.explosion_entry_earliest_minute:02d}"
        return True, f"explosion_open_window_{label}_IST"
    return False, "outside_explosion_open_window"


def in_open_caution_window() -> bool:
    """09:20–09:45 IST — stricter rank gates while opening range forms."""
    if get_market_phase() != "LIVE_MARKET":
        return False
    current = _minutes_now()
    return entry_earliest_minutes() <= current < open_caution_until_minutes()


def in_open_premium_window() -> bool:
    """09:15–09:45 IST — session-open premium explosion detection."""
    if get_market_phase() != "LIVE_MARKET":
        return False
    settings = get_settings()
    current = _minutes_now()
    start = settings.explosion_entry_earliest_hour * 60 + settings.explosion_entry_earliest_minute
    end = open_caution_until_minutes()
    return start <= current < end


def effective_entry_scan_interval_ms() -> int:
    """Fastest cadence across all active fast windows (open premium + expiry).

    Composes the minimum so overlapping windows (e.g. expiry-day open) always take the
    tightest interval — an expiry open scans at the expiry cadence even if the open-window
    value is looser. This is the worst gamma window (Jul21), so it must be fast.
    """
    settings = get_settings()
    from app.engines.expiry_day_guards import any_expiry_session_active

    intervals = [settings.entry_scan_interval_ms]
    if in_open_premium_window() and settings.explosion_open_entry_enabled:
        intervals.append(settings.explosion_open_scan_interval_ms)
    if any_expiry_session_active() and settings.expiry_entry_scan_interval_ms > 0:
        intervals.append(settings.expiry_entry_scan_interval_ms)
    return min(i for i in intervals if i > 0)


def min_explosion_score_now() -> int:
    settings = get_settings()
    if in_open_caution_window():
        return max(settings.aggressive_min_explosion_score, settings.open_caution_min_explosion_score)
    return settings.aggressive_min_explosion_score


def in_midday_chop_window() -> bool:
    """11:30–13:30 IST — low-quality range; block scalp entries in sure-shot mode."""
    if get_market_phase() != "LIVE_MARKET":
        return False
    settings = get_settings()
    if not settings.midday_chop_block_scalps:
        return False
    current = _minutes_now()
    start = settings.midday_chop_start_hour * 60 + settings.midday_chop_start_minute
    end = settings.midday_chop_end_hour * 60 + settings.midday_chop_end_minute
    return start <= current < end


def entry_window_label() -> str:
    settings = get_settings()
    return f"{settings.entry_earliest_hour:02d}:{settings.entry_earliest_minute:02d} IST"
