"""Sep 9–17 legacy book — ATM/ITM only, ₹18–350, no cheap/shallow OTM stack."""

from __future__ import annotations

from typing import Any


def sep917_legacy_profile_active(settings: Any = None) -> bool:
    from app.config import get_settings

    settings = settings or get_settings()
    return bool(getattr(settings, "sep917_legacy_profile_enabled", True))


def legacy_skip_preloss_worst_day_pause_active(settings: Any = None) -> bool:
    """Sep 9–15: chop/worst label before session loss must not full-pause the book."""
    from app.config import get_settings

    settings = settings or get_settings()
    if not bool(getattr(settings, "sep917_legacy_skip_preloss_worst_day_pause", True)):
        return False
    if not sep917_legacy_profile_active(settings):
        return False
    return bool(getattr(settings, "symmetric_best_trade_capture_enabled", True))


def cheap_otm_stack_disabled(settings: Any = None) -> bool:
    """True when cheap-base rank and near-base cheap OTM capture are off."""
    from app.config import get_settings

    settings = settings or get_settings()
    if sep917_legacy_profile_active(settings):
        return True
    return not bool(getattr(settings, "best_trade_cheap_base_rank_priority_enabled", True))


def strict_atm_itm_scan(settings: Any = None) -> bool:
    from app.config import get_settings

    settings = settings or get_settings()
    if not sep917_legacy_profile_active(settings):
        return bool(getattr(settings, "explosion_scan_atm_itm_only", True))
    return True


def sep917_legacy_profile_summary(settings: Any = None) -> dict[str, Any]:
    from app.config import get_settings

    settings = settings or get_settings()
    active = sep917_legacy_profile_active(settings)
    return {
        "enabled": active,
        "premiumBandInr": {
            "min": float(getattr(settings, "min_option_premium_inr", 18.0) or 18.0),
            "max": float(getattr(settings, "max_option_premium_inr", 350.0) or 350.0),
        },
        "atmItmOnly": active
        or bool(getattr(settings, "moneyness_explosion_block_otm", True)),
        "cheapBaseRankPriority": bool(
            getattr(settings, "best_trade_cheap_base_rank_priority_enabled", False)
        ),
        "shallowOtmEntry": bool(
            getattr(settings, "explosion_shallow_otm_entry_enabled", False)
        ),
        "nearBaseCheapOtmCapture": bool(
            getattr(settings, "near_base_session_capture_enabled", False)
        ),
        "ftvEliteTopOnly": bool(getattr(settings, "ftv_elite_top_only_enabled", False)),
        "topMomentsOnly": bool(getattr(settings, "top_moments_only_enabled", False)),
        "putSlideWaiveExpiryOtm": bool(
            getattr(settings, "put_slide_unlock_waive_expiry_otm", False)
        ),
        "skipPrelossWorstDayPause": legacy_skip_preloss_worst_day_pause_active(settings),
    }
