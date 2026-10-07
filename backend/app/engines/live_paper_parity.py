"""When armed for ₹2L live, match paper trading rules — only execution differs (real broker)."""

from __future__ import annotations

from typing import Any


def _strict_bool(value: Any, default: bool = False) -> bool:
    """Only real bools count — MagicMock attrs must not flip parity on in tests."""
    if isinstance(value, bool):
        return value
    return default


def live_paper_parity_active(settings: Any | None = None) -> bool:
    from app.config import get_settings

    s = settings or get_settings()
    return _strict_bool(getattr(s, "live_paper_parity_enabled", False)) or _strict_bool(
        getattr(s, "live_trade_selection_parity_with_paper", False)
    )


def live_paper_profile_summary(settings: Any | None = None) -> dict[str, Any]:
    """HUD / readiness: Oct 1 / 5 paper stack when live is armed with parity."""
    from app.config import get_settings

    s = settings or get_settings()
    parity = live_paper_parity_active(s)
    return {
        "active": parity,
        "liveBestTradesOnlyEnabled": bool(getattr(s, "live_best_trades_only_enabled", True)),
        "worstDayBlocksLive": bool(getattr(s, "worst_day_blocks_live", True)),
        "liveHoldToStructuralSl": bool(getattr(s, "live_hold_to_structural_sl", False)),
        "useUpstoxCapitalForSizing": bool(getattr(s, "use_upstox_capital_for_sizing", False)),
        "sizesFromPaperBook": parity and not should_use_live_broker_capital_for_summary(s),
        "sep917LegacyProfileEnabled": bool(getattr(s, "sep917_legacy_profile_enabled", True)),
        "topMomentsOnlyEnabled": bool(getattr(s, "top_moments_only_enabled", False)),
        "paperSimpleProfitMode": bool(getattr(s, "paper_simple_profit_mode", False)),
        "fallbackCapitalInr": float(getattr(s, "fallback_capital_inr", 0) or 0),
        "maxSizingCapitalInr": float(getattr(s, "max_sizing_capital_inr", 0) or 0),
    }


def should_use_live_broker_capital_for_summary(settings: Any) -> bool:
    """Avoid import cycle with capital_allocator in summary-only callers."""
    from app.engines.capital_allocator import should_use_live_broker_capital

    if not live_paper_parity_active(settings):
        return bool(
            getattr(settings, "use_upstox_capital_for_sizing", False)
            and getattr(settings, "enable_live_trading", False)
        )
    return should_use_live_broker_capital()


def live_paper_profile_ok(settings: Any | None = None) -> tuple[bool, list[str]]:
    """True when env matches deploy/env.live-200k.overlay (Oct paper go-live profile)."""
    from app.config import get_settings

    s = settings or get_settings()
    if not live_paper_parity_active(s):
        return False, ["live_paper_parity_disabled"]
    issues: list[str] = []
    if bool(getattr(s, "live_best_trades_only_enabled", True)):
        issues.append("live_best_trades_only_still_enabled")
    if bool(getattr(s, "worst_day_blocks_live", True)):
        issues.append("worst_day_blocks_live_still_enabled")
    if bool(getattr(s, "live_hold_to_structural_sl", False)):
        issues.append("live_hold_to_structural_sl_still_enabled")
    if bool(getattr(s, "sep917_live_checklist_enforcement_enabled", False)):
        issues.append("sep917_live_checklist_enforcement_enabled")
    if not bool(getattr(s, "sep917_legacy_profile_enabled", True)):
        issues.append("sep917_legacy_profile_disabled")
    cap = float(getattr(s, "fallback_capital_inr", 0) or 0)
    if cap < 199_000:
        issues.append("fallback_capital_below_200k")
    if should_use_live_broker_capital_for_summary(s):
        issues.append("sizing_from_upstox_margin_not_paper_book")
    return (len(issues) == 0, issues)
