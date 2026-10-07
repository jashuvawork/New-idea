"""Frozen October — symmetric CE/PE Oct paper stack (deploy/env.october-frozen.overlay)."""

from __future__ import annotations

from typing import Any


def october_frozen_profile_active(settings: Any | None = None) -> bool:
    from app.config import get_settings

    s = settings or get_settings()
    return bool(getattr(s, "october_frozen_profile_enabled", False))


def october_frozen_profile_summary(settings: Any | None = None) -> dict[str, Any]:
    from app.config import get_settings

    s = settings or get_settings()
    return {
        "active": october_frozen_profile_active(s),
        "symmetricBestTradeCaptureEnabled": bool(
            getattr(s, "symmetric_best_trade_capture_enabled", True)
        ),
        "indexRallySideFlipEnabled": bool(
            getattr(s, "index_rally_side_flip_enabled", True)
        ),
        "directionalSideLockEnabled": bool(
            getattr(s, "directional_side_lock_enabled", True)
        ),
        "sep917LegacyProfileEnabled": bool(getattr(s, "sep917_legacy_profile_enabled", True)),
        "livePaperParityEnabled": bool(
            getattr(s, "live_paper_parity_enabled", False)
            or getattr(s, "live_trade_selection_parity_with_paper", False)
        ),
        "padEntryGuardEnabled": bool(
            getattr(s, "live_paper_parity_pad_entry_guard_enabled", True)
        ),
        "liveBestTradesOnlyEnabled": bool(getattr(s, "live_best_trades_only_enabled", True)),
        "worstDayBlocksLive": bool(getattr(s, "worst_day_blocks_live", True)),
        "chopLiveWaiveNearBaseSep917Shape": bool(
            getattr(s, "chop_live_waive_near_base_sep917_shape", True)
        ),
    }


def october_frozen_profile_ok(settings: Any | None = None) -> tuple[bool, list[str]]:
    """Deploy sign-off: Frozen October rules + CE/PE symmetric capture paths."""
    from app.config import get_settings
    from app.engines.live_paper_parity import live_paper_parity_active

    s = settings or get_settings()
    if not october_frozen_profile_active(s):
        return False, ["october_frozen_profile_disabled"]
    issues: list[str] = []
    if not bool(getattr(s, "symmetric_best_trade_capture_enabled", True)):
        issues.append("symmetric_best_trade_capture_disabled")
    if not bool(getattr(s, "index_rally_side_flip_enabled", True)):
        issues.append("index_rally_side_flip_disabled")
    if not bool(getattr(s, "directional_side_lock_enabled", True)):
        issues.append("directional_side_lock_disabled")
    if not bool(getattr(s, "sep917_legacy_profile_enabled", True)):
        issues.append("sep917_legacy_profile_disabled")
    if not live_paper_parity_active(s):
        issues.append("live_paper_parity_disabled")
    if bool(getattr(s, "live_best_trades_only_enabled", True)):
        issues.append("live_best_trades_only_still_enabled")
    if bool(getattr(s, "worst_day_blocks_live", True)):
        issues.append("worst_day_blocks_live_still_enabled")
    if bool(getattr(s, "live_hold_to_structural_sl", False)):
        issues.append("live_hold_to_structural_sl_still_enabled")
    if bool(getattr(s, "top_moments_only_enabled", False)):
        issues.append("top_moments_only_still_enabled")
    if bool(getattr(s, "sep917_live_checklist_enforcement_enabled", False)):
        issues.append("sep917_live_checklist_enforcement_enabled")
    if not bool(getattr(s, "live_paper_parity_pad_entry_guard_enabled", True)):
        issues.append("pad_entry_guard_disabled")
    return (len(issues) == 0, issues)
