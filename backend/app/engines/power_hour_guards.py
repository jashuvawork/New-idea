"""Power hour (15:00–15:30 IST) — only top FTV/V/ELITE/EXPLODING entries."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.models.schemas import AutoTraderState, SymbolSnapshot
from app.services.upstox import get_market_phase


def _minutes_now() -> int:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    return now.hour * 60 + now.minute


def in_power_hour_window() -> bool:
    """15:00–15:30 IST — restrict new entries to top moments only."""
    settings = get_settings()
    if not bool(getattr(settings, "power_hour_top_only_enabled", True)):
        return False
    if get_market_phase() != "LIVE_MARKET":
        return False
    current = _minutes_now()
    start = settings.power_hour_start_hour * 60 + settings.power_hour_start_minute
    end = settings.power_hour_end_hour * 60 + settings.power_hour_end_minute
    return start <= current < end


def snapshots_have_power_hour_top_signal(
    snapshots: dict[str, SymbolSnapshot],
) -> bool:
    """Live radar shows a top FTV/V/ELITE/explosive moment — session may enter."""
    from app.engines.expiry_day_guards import (
        snapshots_have_expiry_elite_top,
        snapshots_have_grade_a_ftv_first_lift,
    )
    from app.engines.extreme_explosion_moment import snapshots_have_all_in_explosion
    from app.engines.top_ftv_v_expiry_bypass import snapshots_have_top_ftv_or_v

    return (
        snapshots_have_expiry_elite_top(snapshots)
        or snapshots_have_top_ftv_or_v(snapshots)
        or snapshots_have_grade_a_ftv_first_lift(snapshots)
        or snapshots_have_all_in_explosion(snapshots)
    )


def candidate_qualifies_power_hour_top_trade(candidate: Any) -> bool:
    """Per-candidate check during power hour."""
    from app.engines.top_ftv_v_expiry_bypass import is_top_ftv_or_v_candidate
    from app.engines.top_moment_gate import top_moment_entry_allowed
    from app.engines.trade_ranking import rank_entry_candidate

    if is_top_ftv_or_v_candidate(candidate):
        return True

    ranking = rank_entry_candidate(candidate)
    evidence = ranking.get("evidence") or {}
    settings = get_settings()
    ok, _, _ = top_moment_entry_allowed(
        evidence,
        ranking,
        top_moments_only_enabled=True,
        min_grade=str(getattr(settings, "top_moments_min_grade", "A") or "A"),
    )
    return ok


def check_power_hour_session_allowed(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, str, dict[str, Any]]:
    """Session gate after 15:00 — block unless top radar is live."""
    _ = state
    meta: dict[str, Any] = {}
    if not in_power_hour_window():
        return True, "ok", meta
    if snapshots_have_power_hour_top_signal(snapshots):
        meta["powerHourTopSignal"] = True
        return True, "ok", meta
    return False, "power_hour_top_only", meta
