"""09:15–09:45 open book: selector + funnel proof without live orders.

When ``entry_earliest`` is 09:45, the normal entry loop is idle during open caution.
This module runs the same SELECT path, records funnel events, and assesses whether
preorder would pass if the clock allowed entries — evidence for a future 09:15 book.
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import AutoTraderState, SymbolSnapshot
from app.services.upstox import get_market_phase


def open_setup_shadow_select_active() -> tuple[bool, str]:
    """True during open caution while live entry clock is still before entry_earliest."""
    settings = get_settings()
    from app.engines.open_setup_policy import is_open_setup_book_enabled

    if not is_open_setup_book_enabled(settings):
        return False, "open_setup_book_disabled"
    if not bool(getattr(settings, "open_setup_shadow_record_enabled", True)):
        return False, "open_setup_shadow_disabled"
    if get_market_phase() != "LIVE_MARKET":
        return False, "market_not_live"
    from app.engines.session_timing import (
        entries_allowed_now,
        in_open_caution_window,
    )

    if not in_open_caution_window():
        return False, "outside_open_book"
    if entries_allowed_now()[0]:
        return False, "past_entry_earliest"
    return True, "open_setup_shadow_active"


def assess_open_setup_shadow_preorder(
    candidate: Any,
    state: AutoTraderState,
    *,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Preorder stack for shadow proof (no broker). Open setup + side confirm
    must already have passed in the auto-trader loop.
    """
    settings = get_settings()
    meta: dict[str, Any] = {
        "openSetupShadow": True,
        "openBookWindowIst": "09:15–09:45",
    }
    from app.engines.session_timing import entries_allowed_now, entry_window_label

    live_ok, live_reason = entries_allowed_now()
    meta["liveClockWouldBlock"] = not live_ok
    meta["liveClockReason"] = live_reason if not live_ok else None
    meta["entryEarliestIst"] = entry_window_label()

    if bool(getattr(settings, "open_setup_shadow_pretrade_enabled", True)):
        from app.engines.pretrade_validator import validate_candidate

        vt_ok, vt_reason, vt_meta = validate_candidate(
            candidate, state, snapshots=snapshots,
        )
        if isinstance(vt_meta, dict):
            meta["pretrade"] = vt_meta
        if not vt_ok:
            meta["wouldEnterAt915"] = False
            return False, vt_reason, meta

    meta["wouldEnterAt915"] = True
    if not live_ok:
        return False, f"open_setup_shadow_ok_except_{live_reason}", meta
    return True, "open_setup_shadow_would_enter", meta


def open_setup_shadow_summary(settings: Any = None) -> dict[str, Any]:
    settings = settings or get_settings()
    from app.engines.open_setup_policy import is_open_setup_book_enabled

    active, reason = open_setup_shadow_select_active()
    return {
        "openBookEnabled": is_open_setup_book_enabled(settings),
        "enabled": bool(getattr(settings, "open_setup_shadow_record_enabled", True)),
        "pretradeInShadow": bool(
            getattr(settings, "open_setup_shadow_pretrade_enabled", True)
        ),
        "activeNow": active,
        "activeReason": reason,
        "purpose": "Funnel SELECT + preorder proof during 09:15–09:45 (no orders)",
    }


def build_open_setup_shadow_events(
    candidate: Any,
    *,
    cycle_id: str,
    radar_key: str,
    would_ok: bool,
    would_reason: str,
    shadow_meta: dict[str, Any],
    selected_ranking: dict[str, Any],
) -> list[dict[str, Any]]:
    """Funnel rows to persist for one shadow cycle."""
    base = {
        "key": radar_key,
        "symbol": str(candidate.symbol or "").upper(),
        "side": candidate.side.value if hasattr(candidate.side, "value") else str(candidate.side),
        "strike": candidate.strike,
        "cycleId": cycle_id,
        "selectionMode": candidate.mode,
        "selectionScore": candidate.score,
        "tier": getattr(candidate, "tier", None),
        "openSetupShadow": True,
        "stage": "open_setup_shadow",
        "causalGrade": selected_ranking.get("grade"),
        "causalRankScore": selected_ranking.get("rankScore"),
    }
    select_evt = {
        **base,
        "event": "SELECTED",
        "openBookShadowSelect": True,
    }
    proof_evt = {
        **base,
        "event": "OPEN_SETUP_SHADOW_PREORDER",
        "wouldEnter": would_ok,
        "reason": would_reason,
        **{k: v for k, v in shadow_meta.items() if k not in base},
    }
    if would_ok:
        proof_evt["shadowVerdict"] = "would_enter_at_915"
    else:
        proof_evt["shadowVerdict"] = "blocked_before_preorder"
    return [select_evt, proof_evt]