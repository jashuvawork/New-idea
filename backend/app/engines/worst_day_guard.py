"""Worst-day guard — identify early, pause regular trading, breakout-only entries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.config import get_settings
from app.engines.capital_allocator import compute_session_pnl
from app.models.schemas import AutoTraderState, SymbolSnapshot

EntryPolicy = Literal["NORMAL", "BREAKOUT_ONLY", "PAUSED"]


@dataclass
class WorstDayVerdict:
    is_worst: bool
    score: float
    reasons: list[str]
    early_prediction: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "isWorst": self.is_worst,
            "score": self.score,
            "reasons": self.reasons,
            "earlyPrediction": self.early_prediction,
        }


def identify_worst_day(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> WorstDayVerdict:
    """Detect worst chop/expiry day — early (pre-loss) or confirmed."""
    settings = get_settings()
    if not settings.worst_day_pause_enabled:
        return WorstDayVerdict(False, 0.0, [])

    from app.engines.chop_day_guards import is_chop_session
    from app.engines.expiry_day_guards import is_expiry_session, predict_worst_expiry_day
    from app.engines.whipsaw_guards import is_bearish_sideways_session

    reasons: list[str] = []
    score = 0.0
    early = False

    if is_expiry_session(snapshots):
        predicted, pred_score, pred_reasons = predict_worst_expiry_day(state, snapshots)
        if predicted:
            return WorstDayVerdict(True, pred_score, pred_reasons, early_prediction=False)

        if settings.worst_day_early_chop_pause:
            if is_chop_session(snapshots) and is_bearish_sideways_session(snapshots):
                reasons = ["early_expiry_chop_bearish"]
                return WorstDayVerdict(True, 50.0, reasons, early_prediction=True)

        score = pred_score
        reasons = list(pred_reasons)

    if is_bearish_sideways_session(snapshots):
        score += 25
        reasons.append("bearish_sideways")
    if is_chop_session(snapshots):
        score += 20
        reasons.append("chop_regime")

    session_pnl = compute_session_pnl(state)
    if session_pnl <= settings.worst_day_full_pause_loss_inr:
        reasons.append(f"session_loss_{session_pnl:.0f}")
        return WorstDayVerdict(True, max(score, 80.0), reasons, early_prediction=False)

    is_worst = score >= settings.worst_day_pause_score_threshold
    return WorstDayVerdict(is_worst, round(score, 1), reasons, early_prediction=early)


def session_entry_policy(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[EntryPolicy, dict[str, Any]]:
    """
    NORMAL — standard gates
    BREAKOUT_ONLY — worst day; only elite/high-velocity explosions
    PAUSED — no new entries (severe loss or full-pause mode)
    """
    settings = get_settings()
    verdict = identify_worst_day(state, snapshots)
    meta: dict[str, Any] = {
        "worstDay": verdict.to_dict(),
        "breakoutMinRank": settings.worst_day_breakout_min_rank,
        "breakoutMinVelocity3s": settings.worst_day_breakout_min_velocity_3s,
    }

    if not verdict.is_worst:
        return "NORMAL", meta

    session_pnl = compute_session_pnl(state)
    if session_pnl <= settings.worst_day_full_pause_loss_inr:
        meta["pauseReason"] = "worst_day_severe_session_loss"
        return "PAUSED", meta

    if settings.worst_day_breakout_only_enabled:
        meta["pauseReason"] = "worst_day_breakout_only"
        return "BREAKOUT_ONLY", meta

    meta["pauseReason"] = "worst_day_full_pause"
    return "PAUSED", meta


def _side_val(side) -> str:
    from app.models.schemas import Side
    return side.value if isinstance(side, Side) else str(side).upper()


def _breadth_aligned(candidate: Any, snap: SymbolSnapshot) -> bool:
    from app.engines.symbol_cooldown import side_aligned_with_breadth
    return side_aligned_with_breadth(_side_val(candidate.side), snap.breadth.bias)


def _allowed_breakout_tiers() -> set[str]:
    settings = get_settings()
    raw = settings.worst_day_breakout_tiers_csv or "ELITE,EXPLODING"
    return {t.strip().upper() for t in raw.split(",") if t.strip()}


def worst_day_blocks_call_scalp(
    candidate: Any,
    snapshots: dict[str, SymbolSnapshot],
    *,
    policy: EntryPolicy,
) -> tuple[bool, str]:
    """Block CALL scalps on configured symbols when EMA bearish + breadth not bullish."""
    settings = get_settings()
    if not settings.worst_day_call_block_enabled or policy == "NORMAL":
        return False, "ok"

    mode = str(getattr(candidate, "mode", "") or "")
    if mode not in ("scalp", "quick_sideways"):
        return False, "ok"

    if _side_val(candidate.side) != "CALL":
        return False, "ok"

    sym = candidate.symbol.upper()
    blocked_symbols = {
        s.strip().upper()
        for s in (settings.worst_day_call_block_symbols_csv or "").split(",")
        if s.strip()
    }
    if sym not in blocked_symbols:
        return False, "ok"

    snap = snapshots.get(sym) or candidate.snap
    chart = snap.spotChart
    breadth_bias = (snap.breadth.bias or "NEUTRAL").upper()
    ema_bearish = bool(chart and (chart.emaBias or "NEUTRAL").upper() == "BEARISH")
    breadth_not_bullish = breadth_bias in ("BEARISH", "NEUTRAL")

    if ema_bearish and breadth_not_bullish:
        return True, "worst_day_call_blocked_bearish_context"
    return False, "ok"


def worst_day_allows_candidate(
    candidate: Any,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
    *,
    policy: EntryPolicy | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    settings = get_settings()
    meta: dict[str, Any] = {}
    if policy is None:
        policy, policy_meta = session_entry_policy(state, snapshots)
        meta.update(policy_meta)
    else:
        _, policy_meta = session_entry_policy(state, snapshots)
        meta.update(policy_meta)

    if policy == "NORMAL":
        return True, "ok", meta

    if policy == "PAUSED":
        return False, meta.get("pauseReason", "worst_day_paused"), meta

    mode = str(getattr(candidate, "mode", "") or "")
    tier = str(getattr(candidate, "tier", "") or "").upper()
    score = float(getattr(candidate, "score", 0) or 0)
    sym = candidate.symbol.upper()
    snap = snapshots.get(sym) or candidate.snap
    meta["entryPolicy"] = policy

    blocked_call, call_reason = worst_day_blocks_call_scalp(candidate, snapshots, policy=policy)
    if blocked_call:
        return False, call_reason, meta

    if mode == "slow_bounce":
        from app.engines.expiry_day_guards import slow_bounce_session_active
        from app.engines.quick_sideways import detect_slow_bounce_signal

        if not slow_bounce_session_active(snap, state, snapshots):
            return False, "worst_day_slow_bounce_requires_pm_itm", meta
        sig_ok, sig_reason, sb_meta = detect_slow_bounce_signal(
            snap,
            candidate.side,
            float(candidate.strike),
            float(candidate.premium),
        )
        meta["slowBounce"] = sb_meta
        if not sig_ok:
            return False, sig_reason, meta
        min_rank = settings.worst_day_slow_bounce_min_rank
        if score < min_rank:
            return False, f"worst_day_slow_bounce_rank_below_{min_rank:.0f}", meta
        return True, "ok", meta

    if mode == "worst_day_itm_fade":
        from app.engines.worst_day_itm_fade import check_worst_day_itm_fade_entry

        ok, reason, fade_meta = check_worst_day_itm_fade_entry(
            snap,
            candidate.side,
            float(candidate.strike),
            float(candidate.premium),
            velocity_pct=float((getattr(candidate, "pretrade_meta", None) or {}).get("velocityPct") or 0),
            state=state,
            snapshots=snapshots,
        )
        meta["worstDayItmFade"] = fade_meta
        if not ok:
            return False, reason, meta
        if score < settings.worst_day_itm_fade_min_rank:
            return False, f"worst_day_itm_fade_rank_below_{settings.worst_day_itm_fade_min_rank:.0f}", meta
        return True, "ok", meta

    if mode == "quick_sideways":
        from app.engines.worst_day_itm_fade import (
            worst_day_defensive_session_active,
            worst_day_quick_trade_allowed,
        )

        quick_ok, quick_reason = worst_day_quick_trade_allowed(candidate, state, snapshots)
        if quick_ok:
            meta["worstDayQuick"] = True
            return True, "ok", meta
        if worst_day_defensive_session_active(state, snapshots):
            return False, quick_reason, meta

    if mode == "explosion":
        from app.engines.bad_day_routing import _extreme_explosion_bypass

        if _extreme_explosion_bypass(candidate):
            if tier in _allowed_breakout_tiers() or tier == "BUILDING":
                min_rank = max(settings.all_day_explosion_min_score - 5, settings.worst_day_breakout_min_rank - 15)
                if score >= min_rank:
                    meta["extremeMoveBypass"] = True
                    return True, "ok", meta

        # Flat→vertical base rip on worst days (12→392 PE) — allow BUILDING ICT early.
        alert = getattr(candidate, "alert", None) or {}
        event = getattr(candidate, "explosion_event", None)
        ict_flat = bool(alert.get("ictFlatThenVertical"))
        ict_vol = bool(alert.get("volumeAwaken") or alert.get("ictVolumeAwakening"))
        move = 0.0
        if event is not None:
            move = max(
                float(getattr(event, "daily_move_pct", 0) or 0),
                float(getattr(event, "peak_move_pct", 0) or 0),
            )
            ict_flat = ict_flat or bool(getattr(event, "ict_flat_then_vertical", False))
        if not ict_flat and event is not None:
            from app.engines.ict_breakout_monitor import analyze_explosion_event_ict

            ict = analyze_explosion_event_ict(event, snap)
            ict_flat = bool(ict.flat_then_vertical and ict.active)
            ict_vol = ict_vol or bool(ict.volume_awakening or ict.displacement)
            move = max(move, float(ict.session_move_pct or 0))
        early_max = float(getattr(settings, "ict_defensive_base_rip_max_move_pct", 55.0) or 55.0)
        if (
            getattr(settings, "ict_defensive_base_rip_enabled", True)
            and ict_flat
            and ict_vol
            and move <= early_max
            and score >= settings.all_day_explosion_min_score - 8
        ):
            meta["defensiveBaseRip"] = True
            meta["worstDayIctBaseRip"] = True
            return True, "ok", meta

    if mode != "explosion":
        return False, "worst_day_breakout_only", meta

    if tier not in _allowed_breakout_tiers():
        # BUILDING + ICT flat→vertical already handled above; block other BUILDING.
        return False, f"worst_day_tier_{tier.lower()}_blocked", meta

    if score < settings.worst_day_breakout_min_rank:
        return False, f"worst_day_breakout_rank_below_{settings.worst_day_breakout_min_rank:.0f}", meta

    if not _breadth_aligned(candidate, snap):
        from app.engines.vertical_rip_bypass import qualifies_for_vertical_rip_bypass

        event = getattr(candidate, "explosion_event", None)
        if not (event is not None and qualifies_for_vertical_rip_bypass(event, snap=snap)):
            return False, "worst_day_breakout_requires_alignment", meta
        meta["verticalRipBypass"] = True

    if float(snap.tradeQualityScore or 0) < settings.worst_day_breakout_min_symbol_tqs:
        return False, f"worst_day_breakout_tqs_below_{settings.worst_day_breakout_min_symbol_tqs:.0f}", meta

    event = getattr(candidate, "explosion_event", None)
    from app.engines.explosion_detector import effective_breakout_velocities

    vel3, vel9, vel_meta = effective_breakout_velocities(event)
    meta.update(vel_meta)
    meta["velocity3s"] = vel3
    meta["velocity9s"] = vel9

    min_vel = settings.worst_day_breakout_min_velocity_3s
    tier_upper = tier.upper()
    if tier_upper != "ELITE" and vel3 < min_vel and vel9 < min_vel * 1.2:
        return False, f"worst_day_breakout_velocity_below_{min_vel}", meta

    chart = snap.spotChart
    if chart and settings.worst_day_breakout_require_chart_align:
        from app.engines.spot_direction import side_aligned_with_chart
        from app.engines.vertical_rip_bypass import qualifies_for_vertical_rip_bypass
        from app.models.schemas import Side

        event = getattr(candidate, "explosion_event", None)
        side = candidate.side if hasattr(candidate.side, "value") else Side(candidate.side)
        if not side_aligned_with_chart(side, chart):
            if not (event is not None and qualifies_for_vertical_rip_bypass(event, snap=snap)):
                return False, "worst_day_breakout_chart_misaligned", meta
            meta["verticalRipBypass"] = True

    return True, "ok", meta


def filter_worst_day_candidates(
    candidates: list[Any],
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> list[Any]:
    settings = get_settings()
    if settings.dual_mode_enabled:
        from app.engines.daily_18pct_strategy import get_session_limits
        from app.engines.dual_mode_strategy import (
            resolve_trading_session_mode,
            skip_worst_day_breakout_only,
        )

        limits = get_session_limits()
        day_mode = str(getattr(limits, "dayMode", "") or "") if limits else ""
        tier = str(getattr(limits, "confidenceTier", "") or "MEDIUM") if limits else "MEDIUM"
        mode, _ = resolve_trading_session_mode(
            state, snapshots, day_mode=day_mode, confidence_tier=tier,
        )
        if skip_worst_day_breakout_only(mode):
            return candidates

    policy, _ = session_entry_policy(state, snapshots)
    if policy == "NORMAL":
        return candidates
    if policy == "PAUSED":
        return []
    out: list[Any] = []
    for c in candidates:
        ok, _, _ = worst_day_allows_candidate(c, state, snapshots, policy=policy)
        if ok:
            out.append(c)
    return out


def worst_day_blocks_live(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, str, dict[str, Any]]:
    settings = get_settings()
    verdict = identify_worst_day(state, snapshots)
    meta = {"worstDay": verdict.to_dict()}
    if not settings.worst_day_blocks_live or not settings.enable_live_trading:
        return False, "ok", meta
    if verdict.is_worst:
        return True, "worst_day_blocks_live_trading", meta
    return False, "ok", meta


def worst_day_guard_summary(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> dict[str, Any]:
    settings = get_settings()
    verdict = identify_worst_day(state, snapshots)
    policy, policy_meta = session_entry_policy(state, snapshots)
    live_blocked, live_reason, _ = worst_day_blocks_live(state, snapshots)
    return {
        "enabled": settings.worst_day_pause_enabled,
        "worstDay": verdict.to_dict(),
        "entryPolicy": policy,
        "entriesPaused": policy == "PAUSED",
        "breakoutOnly": policy == "BREAKOUT_ONLY",
        "policyMeta": policy_meta,
        "blocksLiveTrading": live_blocked,
        "liveBlockReason": live_reason if live_blocked else None,
        "sessionPnlInr": round(compute_session_pnl(state), 2),
    }
