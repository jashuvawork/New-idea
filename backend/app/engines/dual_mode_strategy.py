"""Dual-mode weekly playbook — DEFENSIVE on bad/worst days, AGGRESSIVE on good days."""

from __future__ import annotations

from typing import Any, Literal, Optional

from app.config import get_settings
from app.models.schemas import AutoTraderState, SymbolSnapshot

TradingSessionMode = Literal["DEFENSIVE", "NORMAL", "AGGRESSIVE"]


def _directional_breadth_aligned(snapshots: dict[str, SymbolSnapshot]) -> bool:
    live = [s for s in snapshots.values() if s.dataAvailable and s.breadth]
    if not live:
        return False
    biases = {(s.breadth.bias or "NEUTRAL").upper() for s in live}
    return biases == {"BULLISH"} or biases == {"BEARISH"}


def _avg_tqs(snapshots: dict[str, SymbolSnapshot]) -> float:
    live = [s for s in snapshots.values() if s.dataAvailable]
    if not live:
        return 0.0
    return sum(float(s.tradeQualityScore or 0) for s in live) / len(live)


def good_day_session_active(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
    *,
    day_mode: str = "",
    confidence_tier: str = "",
) -> tuple[bool, list[str]]:
    """
    Trending / high-confidence session — capture max on the weekly good day.
    Requires directional breadth, no bearish sideways chop, decent TQS.
    """
    settings = get_settings()
    if not settings.dual_mode_enabled:
        return False, []

    from app.engines.day_adaptive_engine import classify_day_type
    from app.engines.chop_day_guards import in_momentum_rally_window
    from app.engines.whipsaw_guards import is_bearish_sideways_session

    tier = (confidence_tier or "MEDIUM").upper()
    dm = (day_mode or "").upper()
    day_type = classify_day_type(dm, tier, snapshots, state=state)
    reasons: list[str] = []

    if day_type not in ("GOOD", "ELITE"):
        return False, [f"day_type_{day_type.lower()}"]

    if is_bearish_sideways_session(snapshots):
        return False, ["bearish_sideways"]

    if tier not in ("HIGH", "ELITE") and not in_momentum_rally_window():
        if not _directional_breadth_aligned(snapshots):
            return False, ["breadth_not_directional"]

    reasons.append(f"day_type_{day_type.lower()}")
    if tier in ("HIGH", "ELITE"):
        reasons.append(f"confidence_{tier.lower()}")
    if _directional_breadth_aligned(snapshots):
        reasons.append("directional_breadth")
    if in_momentum_rally_window() or "RALLY" in dm:
        reasons.append("momentum_rally")
    if _avg_tqs(snapshots) >= settings.aggressive_good_day_min_tqs:
        reasons.append(f"tqs_{_avg_tqs(snapshots):.0f}")

    min_reasons = 2 if tier == "ELITE" else 3
    if len(reasons) >= min_reasons:
        return True, reasons
    return False, reasons


def defensive_day_session_active(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
    *,
    day_mode: str = "",
    confidence_tier: str = "",
) -> tuple[bool, list[str]]:
    """Bad/worst week day — small targets (5–10% of cap), ITM fades only."""
    settings = get_settings()
    if not settings.dual_mode_enabled:
        return False, []

    good, _ = good_day_session_active(
        state, snapshots, day_mode=day_mode, confidence_tier=confidence_tier,
    )
    if good:
        return False, ["good_day_override"]

    from app.engines.bad_day_routing import bad_day_session_active
    from app.engines.day_adaptive_engine import classify_day_type
    from app.engines.worst_day_guard import session_entry_policy

    dm = (day_mode or "").upper()
    tier = (confidence_tier or "MEDIUM").upper()
    day_type = classify_day_type(dm, tier, snapshots, state=state)
    reasons: list[str] = []

    if day_type == "WORST":
        reasons.append("day_type_worst")
    bad, bad_reasons = bad_day_session_active(state, snapshots)
    if bad:
        reasons.extend(bad_reasons[:3])
    policy, _ = session_entry_policy(state, snapshots)
    if policy in ("BREAKOUT_ONLY", "PAUSED"):
        reasons.append(f"policy_{policy.lower()}")

    return bool(reasons), reasons


def resolve_trading_session_mode(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
    *,
    day_mode: str = "",
    confidence_tier: str = "",
) -> tuple[TradingSessionMode, dict[str, Any]]:
    settings = get_settings()
    meta: dict[str, Any] = {"enabled": settings.dual_mode_enabled}

    if not settings.dual_mode_enabled:
        return "NORMAL", meta

    from app.engines.day_adaptive_engine import classify_day_type

    tier = confidence_tier or "MEDIUM"
    dm = day_mode or "NORMAL"
    day_type = classify_day_type(dm, tier, snapshots, state=state)
    meta["dayType"] = day_type
    meta["dayMode"] = dm
    meta["confidenceTier"] = tier

    good, good_reasons = good_day_session_active(
        state, snapshots, day_mode=dm, confidence_tier=tier,
    )
    meta["goodDayActive"] = good
    meta["goodDayReasons"] = good_reasons

    defensive, def_reasons = defensive_day_session_active(
        state, snapshots, day_mode=dm, confidence_tier=tier,
    )
    meta["defensiveDayActive"] = defensive
    meta["defensiveDayReasons"] = def_reasons

    if good:
        meta["mode"] = "AGGRESSIVE"
        meta["playbook"] = [
            "Good day — catch all aligned signals, relaxed rank gates",
            "Higher trade cap, full explosions + scalps, let runners run",
        ]
        return "AGGRESSIVE", meta

    if defensive:
        meta["mode"] = "DEFENSIVE"
        meta["playbook"] = [
            f"Defensive day — target {settings.defensive_daily_target_pct_min:.0%}–"
            f"{settings.defensive_daily_target_pct_max:.0%} of capital",
            "Worst day — ITM fade / elite explosions only; no quick sideways or scalps",
        ]
        meta["defensiveTargetPct"] = settings.defensive_daily_target_pct_min
        return "DEFENSIVE", meta

    meta["mode"] = "NORMAL"
    meta["playbook"] = ["Normal session — standard gates"]
    return "NORMAL", meta


def aggressive_rank_relief(mode: TradingSessionMode) -> float:
    settings = get_settings()
    if mode == "AGGRESSIVE":
        return settings.aggressive_good_day_rank_relief
    return 0.0


def aggressive_min_rank_floor(mode: TradingSessionMode) -> float:
    settings = get_settings()
    if mode == "AGGRESSIVE":
        return settings.aggressive_good_day_min_rank
    return 0.0


def skip_best_trades_only_filter(mode: TradingSessionMode) -> bool:
    settings = get_settings()
    return (
        settings.dual_mode_enabled
        and mode == "AGGRESSIVE"
        and settings.aggressive_good_day_skip_best_trades_only
    )


def skip_bad_day_rank_floor(mode: TradingSessionMode) -> bool:
    settings = get_settings()
    return settings.dual_mode_enabled and mode == "AGGRESSIVE"


def skip_worst_day_breakout_only(mode: TradingSessionMode) -> bool:
    settings = get_settings()
    return (
        settings.dual_mode_enabled
        and mode == "AGGRESSIVE"
        and settings.aggressive_good_day_skip_worst_day_policy
    )


def skip_last_n_session_pause(
    mode: TradingSessionMode,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
) -> bool:
    settings = get_settings()
    if not settings.dual_mode_enabled or mode != "AGGRESSIVE":
        return False
    if not settings.aggressive_good_day_bypass_last_n_pause:
        return False
    if snapshots and _directional_breadth_aligned(snapshots):
        return True
    from app.engines.chop_day_guards import in_momentum_rally_window
    return in_momentum_rally_window()


def aggressive_trade_cap_bonus(mode: TradingSessionMode) -> int:
    settings = get_settings()
    if mode == "AGGRESSIVE":
        return settings.aggressive_good_day_trade_cap_bonus
    return 0


def defensive_daily_target_inr(capital_inr: float, mode: TradingSessionMode) -> Optional[float]:
    settings = get_settings()
    if mode != "DEFENSIVE":
        return None
    pct = (settings.defensive_daily_target_pct_min + settings.defensive_daily_target_pct_max) / 2
    return round(capital_inr * pct, 2)


def apply_aggressive_profile_boost(profile: Any, mode: TradingSessionMode) -> None:
    """Extra lot boost and rank relief on confirmed good days."""
    if mode != "AGGRESSIVE":
        return
    settings = get_settings()
    profile.min_rank_relief += settings.aggressive_good_day_rank_relief - settings.day_adaptive_good_day_rank_relief
    profile.lot_scale_boost = max(profile.lot_scale_boost, settings.aggressive_good_day_lot_scale)
    profile.allow_explosion = True
    profile.pause_regular_scalps = False
    profile.playbook.append(
        f"Aggressive capture — rank floor {settings.aggressive_good_day_min_rank:.0f}, "
        f"cap +{settings.aggressive_good_day_trade_cap_bonus} trades",
    )


def dual_mode_summary(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
    *,
    day_mode: str = "",
    confidence_tier: str = "",
    capital_inr: float = 200_000.0,
) -> dict[str, Any]:
    mode, meta = resolve_trading_session_mode(
        state, snapshots, day_mode=day_mode, confidence_tier=confidence_tier,
    )
    target = defensive_daily_target_inr(capital_inr, mode)
    return {
        **meta,
        "tradingMode": mode,
        "defensiveTargetInr": target,
        "aggressiveRankRelief": aggressive_rank_relief(mode),
        "aggressiveMinRank": aggressive_min_rank_floor(mode) if mode == "AGGRESSIVE" else None,
        "tradeCapBonus": aggressive_trade_cap_bonus(mode),
        "skipBestTradesOnly": skip_best_trades_only_filter(mode),
    }
