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
        # Severe daily loss (>= the 10%/day stop) — never overridden.
        meta["pauseReason"] = "worst_day_severe_session_loss"
        return "PAUSED", meta

    # Intraday TREND-OVERRIDE: a stale morning "chop/worst" verdict must not veto a genuine
    # index breakout. When the spot is at/near a fresh session extreme with aligned momentum
    # and a confirmed sustained index thrust, lift the pause to NORMAL so a top ELITE/
    # EXPLODING can trade the real trend. Re-evaluated live, so it reverts when the trend
    # fades; still bounded by the severe-loss pause above and the daily loss stop.
    if bool(getattr(settings, "worst_day_intraday_trend_override_enabled", True)):
        try:
            from app.engines.index_tick_helpers import index_trend_override_active

            trend_ok, trend_meta = index_trend_override_active(snapshots)
            if trend_ok:
                meta["trendOverride"] = trend_meta
                meta["worstDayLiftedByTrend"] = True
                return "NORMAL", meta
        except Exception:
            pass

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

    side_val = _side_val(candidate.side)
    if side_aligned_with_breadth(side_val, snap.breadth.bias):
        return True
    from app.engines.local_base_chart_bypass import local_base_overrides_side_bias

    alert = getattr(candidate, "alert", None)
    if not isinstance(alert, dict):
        alert = None
    return local_base_overrides_side_bias(
        side_val,
        snap,
        event=getattr(candidate, "explosion_event", None),
        alert=alert,
    )


def _allowed_breakout_tiers() -> set[str]:
    settings = get_settings()
    raw = settings.worst_day_breakout_tiers_csv or "ELITE,EXPLODING"
    return {t.strip().upper() for t in raw.split(",") if t.strip()}


def _defensive_base_rip_tiers() -> set[str]:
    settings = get_settings()
    raw = str(
        getattr(settings, "ict_defensive_base_rip_tiers_csv", "ELITE,EXPLODING")
        or "ELITE,EXPLODING"
    )
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


def _elite_worst_day_bypass_allowed(
    candidate: Any,
    snapshots: dict[str, SymbolSnapshot],
    meta: dict[str, Any],
) -> tuple[bool, str]:
    """Require chart-align + not cold-base for elite_never_block on worst days."""
    settings = get_settings()
    sym = str(getattr(candidate, "symbol", "") or "").upper()
    snap = snapshots.get(sym) or getattr(candidate, "snap", None)

    if getattr(settings, "worst_day_elite_bypass_require_chart_align", True):
        chart = getattr(snap, "spotChart", None) if snap is not None else None
        if chart is not None:
            from app.engines.spot_direction import side_aligned_with_chart

            side = getattr(candidate, "side", None)
            if not side_aligned_with_chart(side, chart):
                meta["eliteBypassChartMisaligned"] = True
                return False, "elite_bypass_chart_misaligned"

    if getattr(settings, "worst_day_elite_bypass_block_cold_base", True):
        timing = None
        event = getattr(candidate, "explosion_event", None)
        if event is not None and snap is not None:
            try:
                from app.engines.entry_timing import assess_timing_for_event
                from app.engines.morning_premium_capture import is_premium_capture_event

                timing = assess_timing_for_event(
                    event,
                    snap=snap,
                    premium_capture=is_premium_capture_event(
                        event, chart=getattr(snap, "spotChart", None),
                    ),
                )
            except Exception:
                timing = None
        if timing:
            assessment = str(timing.get("assessment") or "").upper()
            if (
                timing.get("structuredColdBase")
                or assessment in ("COLD_BASE", "COLD")
            ):
                meta["eliteBypassColdBase"] = True
                meta["eliteBypassTiming"] = assessment or "COLD_BASE"
                return False, "elite_bypass_cold_base"

    return True, "ok"


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

    from app.engines.elite_never_block import elite_never_block_active

    # ELITE explosions may bypass worst-day / BREAKOUT_ONLY / pause gates — but only
    # when chart-aligned and not a cold-base print (Aug6 PUT into bullish chop).
    if (
        str(getattr(candidate, "mode", "") or "") == "explosion"
        and elite_never_block_active(candidate=candidate)
    ):
        elite_ok, elite_deny = _elite_worst_day_bypass_allowed(candidate, snapshots, meta)
        if elite_ok:
            meta["worstDayBypass"] = "elite_never_block"
            return True, "ok", meta
        meta["eliteNeverBlockDenied"] = elite_deny

    if policy == "PAUSED":
        # Never miss a confirmed TOP explosion off a local base — even a paused
        # worst day yields to the best ELITE/EXPLODING base rips (bounded predicate).
        if getattr(settings, "top_explosion_local_base_bypass_enabled", True):
            from app.engines.local_base_chart_bypass import (
                is_top_explosion_local_base_bypass,
            )

            if is_top_explosion_local_base_bypass(candidate):
                meta["worstDayBypass"] = "local_base_top_explosion"
                return True, "ok", meta
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

    # Jul20: block quick_sideways only — scalp/momentum remain tradeable.
    if getattr(settings, "worst_day_block_quick_trades", True) and mode == "quick_sideways":
        return False, "worst_day_blocks_quick_sideways", meta

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

    # Scalp / slow-bounce momentum — allowed on worst days (quick_sideways still blocked).
    if getattr(settings, "worst_day_allow_scalp_momentum", True) and mode in (
        "scalp", "slow_bounce",
    ):
        scalp_floor = float(getattr(settings, "worst_day_scalp_min_rank", 68.0) or 68.0)
        if score < scalp_floor:
            return False, f"worst_day_scalp_rank_below_{scalp_floor:.0f}", meta
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
        meta["worstDayScalpMomentum"] = True
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
            # Aug10: do not let extreme bypass re-admit BUILDING on worst days.
            allow_building_extreme = (
                tier == "BUILDING"
                and not bool(getattr(settings, "worst_day_block_building_ict", True))
            )
            if tier in _allowed_breakout_tiers() or allow_building_extreme:
                min_rank = max(settings.all_day_explosion_min_score - 5, settings.worst_day_breakout_min_rank - 15)
                if score >= min_rank:
                    meta["extremeMoveBypass"] = True
                    return True, "ok", meta

        # Flat→vertical base rip on worst days — ELITE/EXPLODING at local-base pad.
        # Aug10 BUILDING CE (v3 spike, cold v9, mid-pad) must not use this path.
        if (
            tier == "BUILDING"
            and bool(getattr(settings, "worst_day_block_building_ict", True))
        ):
            pass  # fall through to tier block below
        else:
            alert = getattr(candidate, "alert", None) or {}
            event = getattr(candidate, "explosion_event", None)
            ict_flat = bool(alert.get("ictFlatThenVertical"))
            ict_vol = bool(
                alert.get("volumeAwaken")
                or alert.get("volumeAwakening")
                or alert.get("ictVolumeAwakening")
            )
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
            early_max = float(
                getattr(settings, "ict_defensive_base_rip_max_move_pct", 55.0) or 55.0
            )
            # ELITE local-base gate: pad % (not day/peak %). Day% can read 50+ while
            # the print is still ~28% off the pad — those must still take.
            elite_pad_ok = True
            if tier in ("ELITE", "EXPLODING"):
                elite_hi = float(
                    getattr(settings, "elite_local_base_max_move_pct", 40.0) or 40.0
                )
                from app.engines.elite_never_block import top_explosion_must_take_active

                if not top_explosion_must_take_active(candidate=candidate, snap=snap):
                    pad = 0.0
                    for key in (
                        "localBaseMovePct",
                        "ictBaseRelativeMovePct",
                        "baseRelativeMovePct",
                    ):
                        try:
                            pad = float(alert.get(key) or 0)
                        except (TypeError, ValueError):
                            pad = 0.0
                        if pad > 0:
                            break
                    if pad <= 0 and event is not None:
                        try:
                            from app.engines.explosion_entry_guards import (
                                effective_local_base_move_pct,
                            )
                            from app.engines.ict_breakout_monitor import (
                                analyze_explosion_event_ict,
                            )

                            ict_pad = analyze_explosion_event_ict(event, snap)
                            pad = float(
                                effective_local_base_move_pct(event, ict_pad) or 0
                            )
                        except Exception:
                            pad = 0.0
                    timing_move = pad if pad > 0 else move
                    elite_pad_ok = timing_move <= elite_hi
            rip_tiers = _defensive_base_rip_tiers()
            # Legacy BUILDING path only when worst_day_block_building_ict is off.
            building_elite_ok = True
            if tier == "BUILDING":
                min_build = float(
                    getattr(settings, "explosion_building_elite_min_score", 62.0) or 62.0
                )
                min_v3 = float(
                    getattr(settings, "explosion_building_elite_min_velocity_3s", 2.5)
                    or 2.5
                )
                min_v9 = float(
                    getattr(settings, "explosion_building_elite_min_velocity_9s", 2.5)
                    or 2.5
                )
                v3 = float(getattr(event, "velocity_3s", 0) or 0) if event is not None else 0.0
                v9 = float(getattr(event, "velocity_9s", 0) or 0) if event is not None else 0.0
                if v3 <= 0:
                    v3 = float(alert.get("velocity3s") or alert.get("velocity_3s") or 0)
                if v9 <= 0:
                    v9 = float(alert.get("velocity9s") or alert.get("velocity_9s") or 0)
                building_elite_ok = (
                    score >= min_build and v3 >= min_v3 and v9 >= min_v9
                )
            if (
                getattr(settings, "ict_defensive_base_rip_enabled", True)
                and tier in rip_tiers
                and ict_flat
                and ict_vol
                and move <= early_max
                and elite_pad_ok
                and score >= settings.all_day_explosion_min_score - 8
                and building_elite_ok
            ):
                from app.engines.ict_breakout_monitor import (
                    _defensive_base_rip_top_allowed,
                    _expiry_worst_defensive_rip_allowed,
                    _expiry_worst_session,
                )

                quality = 0.0
                v3 = 0.0
                ict_local = None
                if event is not None:
                    v3 = float(getattr(event, "velocity_3s", 0) or 0)
                    try:
                        from app.engines.ict_breakout_monitor import (
                            analyze_explosion_event_ict,
                        )

                        ict_local = analyze_explosion_event_ict(event, snap)
                    except Exception:
                        ict_local = None
                if ict_local is not None:
                    quality = float(getattr(ict_local, "flat_vertical_quality", 0) or 0)
                    if v3 <= 0:
                        v3 = float(getattr(ict_local, "velocity_3s", 0) or 0)
                for key in ("flatVerticalQuality", "ictFlatVerticalQuality"):
                    if quality <= 0:
                        try:
                            quality = float(alert.get(key) or 0)
                        except (TypeError, ValueError):
                            quality = 0.0
                if v3 <= 0:
                    v3 = float(alert.get("velocity3s") or alert.get("velocity_3s") or 0)
                ok_top, deny_top = _defensive_base_rip_top_allowed(
                    tier=tier,
                    quality=quality,
                    score=score,
                    velocity_3s=v3,
                    settings=settings,
                    base_move_pct=float(move or 0),
                    volume_awake=bool(
                        alert.get("ictVolumeAwakening") or alert.get("volumeAwaken")
                    ),
                    v_rip_ready=bool(
                        alert.get("ictVRipReady")
                        or "v_rip"
                        in str(alert.get("momentType") or alert.get("reason") or "").lower()
                    ),
                    armed_base_launch=bool(
                        alert.get("ictArmedBaseLaunch")
                        or str(alert.get("momentType") or "") == "armed_base_launch"
                    ),
                    first_lift=bool(alert.get("ictFirstLift")),
                )
                day_mode = ""
                try:
                    from app.engines.daily_18pct_strategy import get_session_limits

                    limits = get_session_limits()
                    day_mode = str(getattr(limits, "dayMode", "") or "") if limits else ""
                except Exception:
                    day_mode = ""
                if not day_mode:
                    day_mode = str(
                        (getattr(state, "dailyStrategy", None) or {}).get("dayMode")
                        or ""
                    )
                if _expiry_worst_session(day_mode=day_mode, state=state, meta=meta):
                    ok, deny = _expiry_worst_defensive_rip_allowed(
                        tier=tier,
                        quality=quality,
                        score=score,
                        velocity_3s=v3,
                        settings=settings,
                    )
                    if not ok:
                        return False, deny, meta
                elif not ok_top:
                    return False, deny_top, meta
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

    min_vel = float(settings.worst_day_breakout_min_velocity_3s)
    alert = getattr(candidate, "alert", None)
    if not isinstance(alert, dict):
        alert = None
    from app.engines.explosion_entry_guards import structured_near_atm
    from app.engines.ict_breakout_monitor import analyze_explosion_event_ict

    ict_obj = analyze_explosion_event_ict(event, snap) if event is not None else None
    strike = float(
        getattr(candidate, "strike", 0)
        or (getattr(event, "strike", 0) if event is not None else 0)
        or 0
    )
    if structured_near_atm(
        candidate.side,
        strike,
        snap,
        ict=ict_obj,
        event=event,
        alert=alert,
        candidate=candidate,
    ):
        soft = float(
            getattr(settings, "worst_day_structured_ce_min_velocity_3s", 1.5) or 1.5
        )
        min_vel = min(min_vel, soft)
        meta["structuredNearAtm"] = True
        meta["structuredNearAtmCe"] = True  # compat alias
        # Peak-velocity carry when live cooled (structured near-ATM CE/PE).
        if vel3 < min_vel and event is not None:
            from app.engines.explosion_detector import retained_peak_velocity_3s

            peak_v3 = float(
                retained_peak_velocity_3s(
                    str(getattr(event, "symbol", "") or snap.symbol),
                    float(getattr(event, "strike", 0) or strike),
                    getattr(event, "side", candidate.side),
                )
                or 0
            )
            if peak_v3 >= soft:
                vel3 = max(vel3, peak_v3)
                vel9 = max(vel9, peak_v3 * 1.1)
                meta["structuredCePeakVelocity"] = True
                meta["peakVelocity3s"] = peak_v3

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
            from app.engines.local_base_chart_bypass import local_base_overrides_side_bias

            alert = getattr(candidate, "alert", None)
            if not isinstance(alert, dict):
                alert = None
            if local_base_overrides_side_bias(side, snap, event=event, alert=alert):
                meta["localBaseBypass"] = True
            elif not (event is not None and qualifies_for_vertical_rip_bypass(event, snap=snap)):
                return False, "worst_day_breakout_chart_misaligned", meta
            else:
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
