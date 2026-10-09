"""When armed for live paper parity (₹1.5L / ₹2L book), match paper rules — only execution differs."""

from __future__ import annotations

from typing import Any, Mapping

_OCT_FIRST_LIFT_SMALL_LIFT_MOMENTS = frozenset(
    {
        "armed_base_launch",
        "v_rip_session_low",
        "v_rip_session_high",
        "first_lift_local_base",
        "ict_base_armed",
    }
)


def _parity_number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def oct_paper_first_lift_small_lift_context(
    evidence: Mapping[str, Any] | None,
    *,
    settings: Any = None,
    readiness_reason: str = "",
) -> bool:
    """
    Oct 1 paper: symmetric CE/PE early armed-base / v-rip / first-lift at pad (small lift).

    When true under trading_rules_match_paper, chase-style selector/elite blocks are waived.
    negative_velocity and deep cold-tick rejects are not waived here.
    """
    from app.config import get_settings

    s = settings or get_settings()
    if not trading_rules_match_paper(s):
        return False
    if not bool(getattr(s, "oct_paper_first_lift_small_lift_waiver_enabled", True)):
        return False
    if not isinstance(evidence, dict):
        return False

    tier = str(evidence.get("tier") or evidence.get("signalTier") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False

    moment = str(evidence.get("momentType") or "")
    rr = str(
        readiness_reason
        or evidence.get("firstLiftReadinessReason")
        or evidence.get("ictBaseReadinessReason")
        or ""
    ).lower()
    launch = (
        bool(evidence.get("firstLift") or evidence.get("ictFirstLift"))
        or bool(evidence.get("armedBaseLaunch") or evidence.get("ictArmedBaseLaunch"))
        or bool(evidence.get("vRipReady"))
        or moment in _OCT_FIRST_LIFT_SMALL_LIFT_MOMENTS
        or rr.startswith(
            (
                "armed_base",
                "v_rip_session_low",
                "v_rip_session_high",
                "first_lift",
                "ict_base",
            )
        )
    )
    if not launch:
        return False

    side = str(evidence.get("side") or "").upper()
    local = max(
        _parity_number(evidence.get("localBaseMovePct")),
        _parity_number(evidence.get("ictBaseRelativeMovePct")),
    )
    min_move = float(
        getattr(s, "oct_paper_first_lift_small_lift_min_local_pct", 2.0) or 2.0
    )
    max_move = float(
        getattr(s, "oct_paper_first_lift_small_lift_max_local_pct", 40.0) or 40.0
    )
    max_move = max(
        max_move,
        float(getattr(s, "first_lift_trade_max_move_pct", 40.0) or 40.0),
    )

    session_pad = False
    if side == "CALL":
        off_low = _parity_number(evidence.get("offLowMovePct"))
        min_off = float(
            getattr(s, "live_paper_parity_min_off_session_low_pct", 6.0) or 6.0
        )
        session_pad = off_low >= min_off - 1e-6
    elif side == "PUT":
        from app.engines.put_slide_ce_mirror import put_slide_pad_context

        session_pad = put_slide_pad_context(evidence, settings=s)

    if local <= 0 and session_pad:
        local = min_move

    if local > 0 and local < min_move - 1e-6:
        return False
    if local > max_move + 1e-6 and not session_pad:
        return False
    if local > max_move + 1e-6 and session_pad:
        session_cap = float(
            getattr(s, "oct_paper_first_lift_small_lift_session_expansion_max_local_pct", 55.0)
            or 55.0
        )
        if local > session_cap + 1e-6:
            return False

    if str(evidence.get("moneyness") or "").upper() == "OTM":
        steps = _parity_number(evidence.get("strikeStepsFromAtm"))
        max_steps = int(
            getattr(s, "oct_paper_first_lift_small_lift_max_strike_steps", 3) or 3
        )
        if steps <= 0 or steps > max_steps + 1e-6:
            return False

    return True


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


def entry_gates_match_paper(settings: Any | None = None) -> bool:
    """True when live entry/selection gates should match paper (parity flags or Frozen Oct live)."""
    from app.config import get_settings

    s = settings or get_settings()
    if live_paper_parity_active(s):
        return True
    return (
        _strict_bool(getattr(s, "october_frozen_profile_enabled", False))
        and _strict_bool(getattr(s, "enable_live_trading", False))
        and _strict_bool(getattr(s, "auto_trading_enabled", False))
    )


def trading_rules_match_paper(settings: Any | None = None) -> bool:
    """
    Frozen Oct / parity rule stack — live with entry_gates_match_paper, or paper with same profile.

    Use for sizing book, selection helpers, and live-only exit narrowings that paper skips.
    Also skips live-only entry/session narrowings (chop-live wire, whipsaw pause, power-hour
    top-only session block, expiry worst-day declining halt) so live matches Oct 1 paper.
    Does not simulate broker fills (execution still differs on live).
    """
    from app.config import get_settings

    s = settings or get_settings()
    if not _strict_bool(getattr(s, "enable_live_trading", False)):
        return live_paper_parity_active(s) or _strict_bool(
            getattr(s, "october_frozen_profile_enabled", False)
        )
    return entry_gates_match_paper(s)


def legacy_live_narrow_stack_active(settings: Any | None = None) -> bool:
    """
    Old ₹10k-style live-only stack (best-trades-only, structural hold, chop-live wire).

    Hard-disabled when Frozen October or paper-mirror rules are active. Opt-in only via
    legacy_live_narrow_stack_enabled (deploy/env.live-10k.overlay).
    """
    from app.config import get_settings

    s = settings or get_settings()
    if not _strict_bool(getattr(s, "enable_live_trading", False)):
        return False
    if trading_rules_match_paper(s):
        return False
    if _strict_bool(getattr(s, "october_frozen_profile_enabled", False)):
        return False
    return _strict_bool(getattr(s, "legacy_live_narrow_stack_enabled", False))


def live_paper_profile_summary(settings: Any | None = None) -> dict[str, Any]:
    """HUD / readiness: Oct 1 / 5 paper stack when live is armed with parity."""
    from app.config import get_settings

    s = settings or get_settings()
    parity = live_paper_parity_active(s)
    gates = entry_gates_match_paper(s)
    return {
        "active": parity,
        "entryGatesMatchPaper": gates,
        "tradingRulesMatchPaper": trading_rules_match_paper(s),
        "legacyLiveNarrowStackActive": legacy_live_narrow_stack_active(s),
        "liveBestTradesOnlyEnabled": bool(getattr(s, "live_best_trades_only_enabled", True)),
        "worstDayBlocksLive": bool(getattr(s, "worst_day_blocks_live", True)),
        "liveHoldToStructuralSl": bool(getattr(s, "live_hold_to_structural_sl", False)),
        "useUpstoxCapitalForSizing": bool(getattr(s, "use_upstox_capital_for_sizing", False)),
        "sizesFromPaperBook": gates and not should_use_live_broker_capital_for_summary(s),
        "sep917LegacyProfileEnabled": bool(getattr(s, "sep917_legacy_profile_enabled", True)),
        "topMomentsOnlyEnabled": bool(getattr(s, "top_moments_only_enabled", False)),
        "paperSimpleProfitMode": bool(getattr(s, "paper_simple_profit_mode", False)),
        "adaptiveExitsEnabled": bool(getattr(s, "adaptive_exits_enabled", True)),
        "executedEntrySlOnlyLossExits": bool(
            getattr(s, "executed_entry_sl_only_loss_exits", True)
        ),
        "fallbackCapitalInr": float(getattr(s, "fallback_capital_inr", 0) or 0),
        "maxSizingCapitalInr": float(getattr(s, "max_sizing_capital_inr", 0) or 0),
        "padEntryGuardEnabled": bool(
            getattr(s, "live_paper_parity_pad_entry_guard_enabled", True)
        ),
        "padEntryMaxSessionRangePosition": float(
            getattr(s, "live_paper_parity_max_session_range_position", 0.52) or 0.52
        ),
    }


def should_use_live_broker_capital_for_summary(settings: Any) -> bool:
    """Avoid import cycle with capital_allocator in summary-only callers."""
    from app.engines.capital_allocator import should_use_live_broker_capital

    if entry_gates_match_paper(settings):
        return should_use_live_broker_capital()
    if not _strict_bool(getattr(settings, "enable_live_trading", False)):
        return False
    return bool(
        getattr(settings, "use_upstox_capital_for_sizing", False)
        and getattr(settings, "enable_live_trading", False)
    )


# Minimum sizing book for parity go-live (deploy/env.live-150k.overlay and env.live-200k.overlay).
_LIVE_PAPER_PROFILE_MIN_CAPITAL_INR = 149_000.0
# Frozen October small live book (deploy/env.live-50k.overlay).
_FROZEN_OCT_SMALL_BOOK_MIN_CAPITAL_INR = 45_000.0


def live_paper_profile_ok(settings: Any | None = None) -> tuple[bool, list[str]]:
    """True when env matches deploy/env.live-150k or env.live-200k overlay (Oct paper profile)."""
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
    min_cap = _LIVE_PAPER_PROFILE_MIN_CAPITAL_INR
    if _strict_bool(getattr(s, "october_frozen_profile_enabled", False)):
        min_cap = _FROZEN_OCT_SMALL_BOOK_MIN_CAPITAL_INR
    if cap < min_cap:
        issues.append("fallback_capital_below_parity_min")
    if should_use_live_broker_capital_for_summary(s):
        issues.append("sizing_from_upstox_margin_not_paper_book")
    return (len(issues) == 0, issues)
