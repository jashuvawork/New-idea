"""#816 mega exit pack for the current paper book.

Oct 22 SENSEX 73200 PE peaked +76pt and sold on a between-rung fade at +39pt.
PR #816 holds that shape for the 75% ladder, the rung floor, or the mega hole,
and the stage lock uses booked profit rather than an open mark.

The paper #676 session runs this pack even when env still has the old
2-point between-rung fade or a ladder that has been turned off. Live trading
does not use the overlay.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings

# Exact #816 pack. Numeric fields replace weaker paper env; they are not scaled.
PAPER_816_EXIT_PACK: dict[str, Any] = {
    "tp_rung_ladder_exit_enabled": True,
    "unified_profit_ladder_enabled": True,
    "daily_profit_stage_locks_enabled": True,
    "stage_runner_mega_hole_exit_enabled": True,
    "stage_runner_mega_red_giveback_enabled": True,
    "tp_rung_ladder_mega_fade_min_giveback_points": 12.0,
    "tp_rung_ladder_mega_hot_defer_velocity_3s": 4.0,
    "tp_rung_ladder_mega_approach_buffer_points": 7.0,
    "tp_rung_ladder_mega_fall_min_seconds_after_peak": 75.0,
    "tp_rung_ladder_mega_disable_between_fade_min_best_points": 55.0,
    "tp_rung_ladder_mega_ladder_first_min_best_points": 55.0,
}


def _strict_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    return default


def paper_816_exit_pack_active(settings: Any | None = None) -> bool:
    """True on the disarmed paper book (the #676 choke, or the explicit flag)."""
    s = settings or get_settings()
    if _strict_bool(getattr(s, "enable_live_trading", False)):
        return False
    if not _strict_bool(getattr(s, "paper_trading", True), True):
        return False
    if _strict_bool(getattr(s, "paper_816_exit_pack_enabled", False)):
        return True
    from app.engines.live_paper_parity import paper_676_entry_choke_active

    return paper_676_entry_choke_active(s)


def settings_for_paper_exit(settings: Settings | None = None) -> Settings:
    """Return settings with the #816 pack applied when this paper session is on."""
    s = settings or get_settings()
    if not paper_816_exit_pack_active(s):
        return s
    return s.model_copy(update=dict(PAPER_816_EXIT_PACK))
