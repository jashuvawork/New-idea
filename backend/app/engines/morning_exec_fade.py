"""Morning execution fade discipline — two-bar confirm before 10:30 IST."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.config import get_settings
from app.engines.session_timing import in_morning_exec_fade_strict_window
from app.models.schemas import TimeframeChartRead


def premium_live_fade_blocks_now(
    *,
    premium_momentum_3s: float,
    premium_momentum_5s: float,
    min_mom: float,
    when: Optional[datetime] = None,
) -> bool:
    """True when fade is strong enough to block (both legs weak in morning window)."""
    if in_morning_exec_fade_strict_window(when):
        return premium_momentum_5s < min_mom and premium_momentum_3s < min_mom
    return premium_momentum_5s < min_mom and premium_momentum_3s < 0


def premium_mtf_fade_block_reason(
    premium_mtf: dict[str, TimeframeChartRead],
    *,
    fade_check,
    when: Optional[datetime] = None,
) -> tuple[bool, str]:
    """
    Return (block, reason). Morning: block only if both 1m and 5m premium TFs fail fade_check.
    """
    if not premium_mtf:
        return False, ""
    failing: list[str] = []
    for req in ("1m", "5m"):
        pt = premium_mtf.get(req)
        bad, _ = fade_check(req, pt)
        if bad:
            failing.append(req)
    if not failing:
        return False, ""
    if in_morning_exec_fade_strict_window(when) and len(failing) < 2:
        return False, ""
    return True, f"exec_mtf_premium_{failing[0]}_fading"


def morning_fade_meta(when: Optional[datetime] = None) -> dict[str, Any]:
    settings = get_settings()
    return {
        "morningExecFadeTwoBar": in_morning_exec_fade_strict_window(when),
        "morningExecFadeTwoBarEnabled": bool(
            getattr(settings, "morning_exec_fade_two_bar_enabled", True)
        ),
    }