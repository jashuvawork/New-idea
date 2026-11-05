"""Pinned session books: **open** 09:15–09:45, **normal (post-open)** 09:45–15:45.

``post_open_setup_until`` (default 10:30) is only an open-rip fade bypass helper inside
the normal book — not the definition of post-open.

Same entry stack for paper and live; only execution adapter differs.
Production HUD: ``open_setup_policy_status()``; tests pin ``OPEN_SETUP_FROZEN_DEFAULTS``.
"""

from __future__ import annotations

import inspect
from typing import Any

from app.config import get_settings

# Bump when intentionally changing the saved open book (document in PR body).
OPEN_SETUP_POLICY_ID = "2026-11-open-v1"
OPEN_SETUP_POLICY_NOTE = (
    "Open book 09:15–09:45 (caution, lanes, side align, ITM). "
    "Post-open = normal CE/PE book 09:45–15:45; open guards idle after 09:45. "
    "Config post_open_setup_until 10:30 = rip fade bypass only."
)

# User-facing session clocks (IST).
OPEN_BOOK_WINDOW_IST = "09:15–09:45"
NORMAL_BOOK_WINDOW_IST = "09:45–15:45"

# Shared entry stack (no paper/live branch inside open setup engines).
OPEN_SETUP_SHARED_ENTRY_PATHS = (
    "app.engines.trade_selector.filter_daily_entry_candidates",
    "app.engines.pretrade_validator.validate_candidate",
    "app.engines.auto_trader (validate_open_setup_entry before open_side_confirmation)",
)

OPEN_BOOK_FROZEN_DEFAULTS: dict[str, Any] = {
    "open_setup_guards_enabled": True,
    "open_setup_start_hour": 9,
    "open_setup_start_minute": 15,
    "open_caution_until_hour": 9,
    "open_caution_until_minute": 45,
    "open_caution_min_explosion_score": 45,
    "open_caution_min_rank_score": 55.0,
    "open_caution_side_align_index_enabled": True,
    "open_caution_block_puts_enabled": False,
    "open_caution_non_lane_index_blocked": True,
    "open_caution_aligned_side_lane_waiver_enabled": True,
    "open_caution_itm_band_enabled": True,
    "open_caution_sensex_call_max_itm_points": 800.0,
    "open_caution_sensex_put_max_itm_points": 800.0,
    "open_caution_nifty_put_max_itm_points": 400.0,
    "open_caution_premium_fade_fill_enabled": True,
    "open_caution_premium_fade_max_drawdown_pct": -2.8,
    "open_caution_premium_fade_max_local_base_pct": 28.0,
    "open_caution_premium_fade_min_rank_score": 90.0,
    "open_caution_premium_fade_allow_grade_s": True,
    "open_index_lane_enabled": True,
    "open_sensex_call_lane_enabled": True,
    "open_sensex_put_lane_enabled": True,
    "open_nifty_put_lane_enabled": False,
    "open_nifty_call_lane_on_aligned_open_enabled": True,
    "open_nifty_put_lane_on_aligned_open_enabled": True,
    "open_index_lane_require_first_lift": True,
    "open_index_lane_open_rip_first_lift_waiver_enabled": True,
    "open_index_lane_min_elite_score": 90.0,
    "open_index_lane_max_local_base_pct": 15.0,
    "open_session_expiry_lane_enabled": True,
    "open_side_confirmation_enabled": True,
    "open_side_confirmation_start_hour": 9,
    "open_side_confirmation_start_minute": 25,
    "open_side_confirmation_min_index_move_pct": 0.10,
}

# Sub-window inside normal book: shallow MTF fade floor for open-rip continuation.
OPEN_RIP_CONTINUATION_FROZEN_DEFAULTS: dict[str, Any] = {
    "post_open_setup_until_hour": 10,
    "post_open_setup_until_minute": 30,
    "post_open_setup_premium_fade_fill_enabled": True,
}

# Backward-compatible alias (not “post-open day” — see NORMAL_BOOK_WINDOW_IST).
POST_OPEN_BOOK_FROZEN_DEFAULTS = OPEN_RIP_CONTINUATION_FROZEN_DEFAULTS

OPEN_SETUP_FROZEN_DEFAULTS: dict[str, Any] = {
    **OPEN_BOOK_FROZEN_DEFAULTS,
    **OPEN_RIP_CONTINUATION_FROZEN_DEFAULTS,
}


def _open_setup_modules_paper_free() -> bool:
    """Open/post-open engines must not branch on paper vs live."""
    from app.engines import open_index_lane, open_setup_guards
    from app.engines.pad_lane_capture import (
        open_caution_premium_fade_bypass,
        post_open_setup_premium_fade_bypass,
    )

    for mod in (open_index_lane, open_setup_guards):
        src = inspect.getsource(mod)
        if "paper_trading" in src or "enable_live_trading" in src:
            return False
    for fn in (
        open_caution_premium_fade_bypass,
        post_open_setup_premium_fade_bypass,
    ):
        src = inspect.getsource(fn)
        if "paper_trading" in src or "enable_live_trading" in src:
            return False
    return True


def open_setup_policy_snapshot(settings: Any = None) -> dict[str, Any]:
    """Full open + post-open book for deployment HUD / EOD audit."""
    settings = settings or get_settings()
    from app.engines.open_index_lane import open_index_lane_summary
    from app.engines.open_setup_guards import open_setup_guard_summary

    normal_end = (
        f"{int(getattr(settings, 'power_hour_end_hour', 15)):02d}:"
        f"{int(getattr(settings, 'power_hour_end_minute', 45)):02d}"
    )
    return {
        "policyId": OPEN_SETUP_POLICY_ID,
        "note": OPEN_SETUP_POLICY_NOTE,
        "sessionBooksIst": {
            "openBook": OPEN_BOOK_WINDOW_IST,
            "normalBookPostOpen": NORMAL_BOOK_WINDOW_IST,
            "normalBookEntryEnd": normal_end,
        },
        "windowsIst": {
            "openSetupStart": (
                f"{int(getattr(settings, 'open_setup_start_hour', 9)):02d}:"
                f"{int(getattr(settings, 'open_setup_start_minute', 15)):02d}"
            ),
            "openCautionUntil": (
                f"{int(getattr(settings, 'open_caution_until_hour', 9)):02d}:"
                f"{int(getattr(settings, 'open_caution_until_minute', 45)):02d}"
            ),
            "openRipFadeBypassUntil": (
                f"{int(getattr(settings, 'post_open_setup_until_hour', 10)):02d}:"
                f"{int(getattr(settings, 'post_open_setup_until_minute', 30)):02d}"
            ),
        },
        "guardClock": "open_setup_guard_when (decision now / explicit when=)",
        "openBookFrozen": dict(OPEN_BOOK_FROZEN_DEFAULTS),
        "openRipContinuationFrozen": dict(OPEN_RIP_CONTINUATION_FROZEN_DEFAULTS),
        "openBook": dict(OPEN_BOOK_FROZEN_DEFAULTS),
        "postOpenBook": dict(POST_OPEN_BOOK_FROZEN_DEFAULTS),
        "openIndexLane": open_index_lane_summary(settings),
        "openSetupGuards": open_setup_guard_summary(settings),
        "frozenFields": dict(OPEN_SETUP_FROZEN_DEFAULTS),
    }


def verify_open_setup_policy(settings: Any = None) -> tuple[bool, list[str]]:
    """True when live settings still match the pinned open + post-open defaults."""
    settings = settings or get_settings()
    drift: list[str] = []
    for key, expected in OPEN_SETUP_FROZEN_DEFAULTS.items():
        actual = getattr(settings, key, None)
        if isinstance(expected, float):
            try:
                ok = abs(float(actual) - expected) < 1e-6
            except (TypeError, ValueError):
                ok = False
        else:
            ok = actual == expected
        if not ok:
            drift.append(f"{key}={actual!r} expected {expected!r}")
    return (len(drift) == 0, drift)


def open_setup_policy_status(settings: Any = None) -> dict[str, Any]:
    settings = settings or get_settings()
    ok, drift = verify_open_setup_policy(settings)
    confirmed = str(getattr(settings, "open_setup_policy_confirmed_session", "") or "").strip()
    paper_parity = bool(getattr(settings, "paper_live_parity_enabled", True))
    return {
        "policyId": OPEN_SETUP_POLICY_ID,
        "aligned": ok,
        "drift": drift,
        "confirmedSession": confirmed or None,
        "readyForLiveOpenBook": ok and bool(confirmed),
        "readyForLiveSessionBooks": ok and bool(confirmed),
        "execution": {
            "sharedEntryGates": list(OPEN_SETUP_SHARED_ENTRY_PATHS),
            "liveUsesSameOpenBook": _open_setup_modules_paper_free(),
            "liveUsesSameNormalBook": True,
            "liveMatchesPaperBook": {
                "chopLiveEntryOnlyOnChopDays": True,
                "liveHoldToStructuralSl": bool(
                    getattr(settings, "live_hold_to_structural_sl", False)
                ),
                "useUpstoxCapitalForSizing": bool(
                    getattr(settings, "use_upstox_capital_for_sizing", False)
                ),
            },
            "paperLiveParityEnabled": paper_parity,
            "note": (
                "enable_live_trading = paper book + broker orders. "
                "Chop-live entries only on chop days; size from FALLBACK/MAX_SIZING unless "
                "USE_UPSTOX_CAPITAL_FOR_SIZING=true; same exits as paper unless "
                "LIVE_HOLD_TO_STRUCTURAL_SL=true."
            ),
        },
        "snapshot": open_setup_policy_snapshot(settings),
    }
