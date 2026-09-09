"""Tunable structural guard parameters — Sep08 fixes and related entry/exit gates.

Every guard exposes a master enable flag plus thresholds so production can be
tuned without code changes when a rule fires too often or not enough.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings


def _f(settings: Settings, name: str, default: float) -> float:
    v = getattr(settings, name, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _b(settings: Settings, name: str, default: bool = True) -> bool:
    return bool(getattr(settings, name, default))


def _i(settings: Settings, name: str, default: int) -> int:
    v = getattr(settings, name, default)
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def chopish_active(
    snap: Any,
    *,
    settings: Settings | None = None,
) -> tuple[bool, bool, bool]:
    """Return (chopish, chop_regime, midday_chop) using tunable regime thresholds."""
    from app.engines.explosion_entry_guards import _midday_chop_active, _regime_chopish

    s = settings or get_settings()
    chop_regime = _regime_chopish(snap, settings=s) if _b(s, "chopish_regime_detection_enabled") else False
    midday = _midday_chop_active() if _b(s, "chopish_midday_union_enabled") else False
    if _b(s, "chopish_midday_union_enabled", True):
        chopish = chop_regime or midday
    else:
        chopish = chop_regime and midday
    return chopish, chop_regime, midday


def structural_guard_summary(settings: Settings | None = None) -> dict[str, Any]:
    """Deployment HUD snapshot of structural guard knobs (read-only observability)."""
    s = settings or get_settings()
    return {
        "chopArmedBaseBlock": {
            "enabled": _b(s, "chop_live_block_armed_base_launch"),
            "maxLocalPadPct": _f(s, "chop_live_armed_base_max_local_pad_pct", 20.0),
            "minSessionMovePct": _f(s, "armed_base_shallow_min_session_move_pct", 28.0),
        },
        "fakeTrapChopEliteArmedBase": {
            "enabled": _b(s, "fake_explosion_trap_block_chop_elite_armed_base"),
            "minSessionMovePct": _f(s, "fake_explosion_trap_min_session_move_pct", 28.0),
            "chopEliteLotCap": _i(s, "fake_explosion_trap_chop_elite_lot_cap", 6),
        },
        "sessionSameStrikeLossReentry": {
            "enabled": _b(s, "session_same_strike_loss_reentry_enabled"),
            "minLossInr": _f(s, "session_same_strike_loss_reentry_min_loss_inr", 500.0),
            "cooldownSeconds": _i(s, "session_same_strike_loss_reentry_cooldown_seconds", 0),
        },
        "sessionNearStrikeLossReentry": {
            "enabled": _b(s, "session_near_strike_loss_reentry_enabled"),
            "minLossInr": _f(s, "session_near_strike_loss_reentry_min_loss_inr", 500.0),
            "maxSteps": _i(s, "session_near_strike_loss_reentry_max_steps", 3),
        },
        "explosionInstrumentLossCooldown": {
            "enabled": _b(s, "explosion_instrument_loss_cooldown_enabled"),
            "seconds": _i(s, "explosion_instrument_loss_cooldown_seconds", 14_400),
        },
        "peakVelocityReversalKeep": {
            "enabled": _b(s, "peak_velocity_reversal_keep_enabled"),
            "keepRatio": _f(s, "peak_velocity_reversal_keep_ratio", 0.75),
            "minBestPoints": _f(s, "peak_velocity_reversal_min_best_points", 8.0),
            "minReversalVelocity3s": _f(s, "peak_velocity_reversal_min_velocity_3s", 2.0),
            "slowBleedEnabled": _b(s, "peak_velocity_reversal_slow_bleed_enabled"),
            "slowBleedMinGivebackPoints": _f(
                s, "peak_velocity_reversal_slow_bleed_min_giveback_points", 5.0
            ),
            "deferEliteRunner": _b(s, "peak_velocity_reversal_defer_elite_runner_enabled"),
            "deferEliteRunnerMinGainPct": _f(
                s, "peak_velocity_reversal_defer_elite_runner_min_gain_pct", 8.0
            ),
            "deferEliteRunnerMinRankScore": _f(
                s, "peak_velocity_reversal_defer_elite_runner_min_rank_score", 85.0
            ),
            "requireRolloverConfirm": _b(
                s, "peak_velocity_reversal_require_rollover_confirm"
            ),
        },
        "deepItmSubstituteBlock": {
            "enabled": _b(s, "explosion_deep_itm_substitute_block_enabled"),
            "minItmSteps": _i(s, "explosion_deep_itm_substitute_min_itm_steps", 1),
            "nearStrikeMaxSteps": _i(s, "explosion_deep_itm_substitute_near_strike_max_steps", 2),
        },
        "deepItmAtmRadarAdvantageBlock": {
            "enabled": _b(s, "explosion_deep_itm_block_atm_radar_advantage_enabled"),
            "minScoreAdvantage": _f(s, "explosion_deep_itm_block_atm_min_score_advantage", 20.0),
            "maxItmStepsWhenAtmOnRadar": _i(
                s, "explosion_deep_itm_block_max_itm_steps_when_atm_on_radar", 1
            ),
        },
        "chopishRegime": {
            "regimeDetectionEnabled": _b(s, "chopish_regime_detection_enabled"),
            "middayUnionEnabled": _b(s, "chopish_midday_union_enabled"),
            "mom5MaxPct": _f(s, "chopish_regime_mom5_max_pct", 0.25),
            "strengthMax": _f(s, "chopish_regime_strength_max", 45.0),
        },
    }
