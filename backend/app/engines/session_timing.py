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


def open_setup_start_minutes() -> int:
    settings = get_settings()
    h = int(getattr(settings, "open_setup_start_hour", settings.entry_earliest_hour))
    m = int(getattr(settings, "open_setup_start_minute", settings.entry_earliest_minute))
    return h * 60 + m


def _commodity_session_start_minutes() -> int:
    settings = get_settings()
    return int(settings.commodity_session_start_hour) * 60 + int(
        settings.commodity_session_start_minute
    )


def any_configured_commodity_live() -> bool:
    from app.services.instrument_registry import is_commodity
    from app.services.upstox import get_market_phase_for_symbol

    settings = get_settings()
    for sym in settings.symbols or []:
        sym_u = str(sym or "").strip().upper()
        if is_commodity(sym_u) and get_market_phase_for_symbol(sym_u) == "LIVE_MARKET":
            return True
    return False


def commodity_paper_evening_active() -> bool:
    """True when paper may enter on MCX only — equity session is closed."""
    settings = get_settings()
    if not bool(getattr(settings, "commodity_paper_entries_enabled", True)):
        return False
    if not bool(settings.paper_trading):
        return False
    if get_market_phase() == "LIVE_MARKET":
        return False
    return any_configured_commodity_live()


def symbol_entry_market_live(symbol: str) -> bool:
    """Per-symbol session clock — MCX commodities vs equity indices."""
    from app.services.instrument_registry import is_commodity
    from app.services.upstox import get_market_phase_for_symbol

    sym_u = str(symbol or "").strip().upper()
    if is_commodity(sym_u):
        return get_market_phase_for_symbol(sym_u) == "LIVE_MARKET"
    return get_market_phase() == "LIVE_MARKET"


def entries_allowed_now() -> tuple[bool, str]:
    """False until configured IST time (default 09:45) during live market."""
    phase = get_market_phase()
    if phase == "LIVE_MARKET":
        current = _minutes_now()
        earliest = entry_earliest_minutes()
        if current < earliest:
            settings = get_settings()
            label = f"{settings.entry_earliest_hour:02d}:{settings.entry_earliest_minute:02d}"
            return False, f"before_entry_window_{label}_IST"
        return True, "ok"

    if commodity_paper_evening_active():
        current = _minutes_now()
        start = _commodity_session_start_minutes()
        if current < start:
            return False, "before_commodity_session_IST"
        return True, "commodity_paper_evening"

    return False, "market_not_live"


def explosion_entries_allowed_now() -> tuple[bool, str]:
    """Explosion orders before the general clock. Empty when both clocks are 09:15."""
    settings = get_settings()
    if not settings.explosion_open_entry_enabled:
        if commodity_paper_evening_active():
            return True, "commodity_paper_explosion"
        return False, "explosion_open_entry_disabled"
    if commodity_paper_evening_active():
        return True, "commodity_paper_explosion"
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
    """Open setup entry window (default 09:15–09:45 IST); stricter rank gates while range forms."""
    if commodity_paper_evening_active():
        return False
    if get_market_phase() != "LIVE_MARKET":
        return False
    current = _minutes_now()
    return open_setup_start_minutes() <= current < open_caution_until_minutes()


def _minutes_at(dt: datetime) -> int:
    local = dt.astimezone(IST)
    return local.hour * 60 + local.minute


def in_open_premium_window_at(when: datetime) -> bool:
    """09:15–09:45 IST at a specific clock (replay / entry stamp)."""
    settings = get_settings()
    current = _minutes_at(when)
    start = settings.explosion_entry_earliest_hour * 60 + settings.explosion_entry_earliest_minute
    end = open_caution_until_minutes()
    return start <= current < end


def in_open_premium_window() -> bool:
    """09:15–09:45 IST — session-open premium explosion detection."""
    if commodity_paper_evening_active():
        return False
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
    if commodity_paper_evening_active():
        return False
    if get_market_phase() != "LIVE_MARKET":
        return False
    settings = get_settings()
    if not settings.midday_chop_block_scalps:
        return False
    current = _minutes_now()
    start = settings.midday_chop_start_hour * 60 + settings.midday_chop_start_minute
    end = settings.midday_chop_end_hour * 60 + settings.midday_chop_end_minute
    return start <= current < end


def in_regular_explosion_session_window() -> bool:
    """From entry_earliest through 15:30 IST — standard intraday explosion entry window."""
    allowed, _ = entries_allowed_now()
    if not allowed:
        return False
    if commodity_paper_evening_active():
        return True
    return _minutes_now() < 15 * 60 + 30


def entry_window_label() -> str:
    settings = get_settings()
    return f"{settings.entry_earliest_hour:02d}:{settings.entry_earliest_minute:02d} IST"


def in_morning_exec_fade_strict_window(when: datetime | None = None) -> bool:
    """09:45–10:30 IST — require premium fade on both 1m-scale and 5m before blocking (PDF)."""
    settings = get_settings()
    if not bool(getattr(settings, "morning_exec_fade_two_bar_enabled", True)):
        return False
    if commodity_paper_evening_active():
        return False
    if when is None:
        if get_market_phase() != "LIVE_MARKET":
            return False
        current = _minutes_now()
    else:
        current = _minutes_at(when)
    start = entry_earliest_minutes()
    end_h = int(getattr(settings, "morning_exec_fade_strict_until_hour", 10) or 10)
    end_m = int(getattr(settings, "morning_exec_fade_strict_until_minute", 30) or 30)
    end = end_h * 60 + end_m
    return start <= current < end