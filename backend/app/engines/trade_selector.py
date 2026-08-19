"""Pick the single best paper entry when running aggressive max-lot mode."""

from dataclasses import dataclass
from typing import Any, Optional

from app.config import get_settings
from app.engines.premium_filter import premium_in_band
from app.engines.market_momentum import (
    index_moment_active,
    index_moment_rank_bonus,
    side_aligned_with_index_moment,
)
from app.engines.explosion_profit import check_explosion_entry
from app.engines.instrument_cooldown import (
    instrument_daily_cap_reached,
    instrument_in_cooldown,
)
from app.engines.preorder_rejection_suppression import (
    candidate_preorder_rejection_suppressed,
)
from app.engines.pretrade_validator import (
    collect_session_trades,
    compute_symbol_stats,
    filter_candidates_pretrade,
    index_rank_from_backtest,
    last_n_elevated_min_rank,
    last_n_trades_summary,
)
from app.engines.edge_engine import compute_entry_edge, edge_rank_bonus, session_pf_feedback
from app.engines.day_adaptive_engine import (
    apply_rank_floor_adaptive,
    mode_rank_bonus,
    resolve_day_adaptive,
    should_pause_regular_scalps,
)
from app.engines.simple_profit import check_entry_gate
from app.engines.spot_direction import chart_rank_adjustment
from app.engines.moneyness import (
    classify_moneyness,
    heatmap_moneyness_candidates,
    moneyness_rank_adjustment,
)
from app.engines.symbol_cooldown import (
    entry_score_penalty,
    requires_breadth_alignment,
    side_aligned_with_breadth,
    symbol_in_cooldown,
)
from app.engines.quick_sideways import (
    check_quick_sideways_entry,
    is_sideways_session,
    quick_sideways_enabled,
    scan_quick_sideways_setups,
    scan_slow_bounce_setups,
)
from app.engines.worst_day_itm_fade import (
    scan_worst_day_itm_fade_setups,
    scan_worst_day_quick_setups,
    worst_day_defensive_session_active,
)
from app.engines.swing_engine import SwingSetup
from app.models.schemas import (
    AutoTraderState,
    Side,
    StrategyType,
    SuggestedTrade,
    SymbolSnapshot,
)


@dataclass
class EntryCandidate:
    symbol: str
    snap: SymbolSnapshot
    mode: str  # explosion | scalp | swing
    score: float
    side: Side
    strike: float
    premium: float
    strategy_type: StrategyType
    confidence: float
    tqs: float
    tier: Optional[str] = None
    explosion_event: Any = None
    swing_setup: Any = None
    suggestion: Any = None
    alert: Optional[dict] = None
    pretrade_meta: Optional[dict] = None


def rank_candidates_for_selection(
    candidates: list[EntryCandidate],
    legacy_score,
) -> list[EntryCandidate]:
    """Final causal-first ordering after every pretrade mutation."""
    from app.engines.trade_ranking import ranking_sort_key

    return sorted(
        candidates,
        key=lambda candidate: (
            *ranking_sort_key(
                (candidate.pretrade_meta or {}).get("causalRanking", {})
            ),
            legacy_score(candidate),
            candidate.symbol.upper(),
            candidate.side.value,
            float(candidate.strike),
        ),
        reverse=True,
    )


def _exclude_preorder_rejected_candidates(
    candidates: list[EntryCandidate],
) -> list[EntryCandidate]:
    """Keep a rejected leg out of ranking without bypassing fresh selector guards."""
    return [
        candidate
        for candidate in candidates
        if not candidate_preorder_rejection_suppressed(candidate)
    ]


def _building_aligned_ict_alert_ok(
    alert: dict[str, Any],
    snap: SymbolSnapshot,
    tier_u: str,
    *,
    state: Any = None,
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
) -> bool:
    """Allow BUILDING only as elite-build: ICT flat→vertical + chart + hot score/v3/v9.

    On WORST / BREAKOUT_ONLY / DEFENSIVE sessions, BUILDING ICT is blocked entirely
    (Aug10 fake elite-build CE) — ELITE/EXPLODING take at local-base pad instead.
    """
    settings = get_settings()
    if not bool(getattr(settings, "explosion_building_aligned_ict_enabled", True)):
        return False
    if tier_u != "BUILDING":
        return False
    if bool(getattr(settings, "worst_day_block_building_ict", True)):
        # Fail closed on DEFENSIVE / BREAKOUT_ONLY / PAUSED — missing state or
        # policy errors must not re-admit Aug10-style BUILDING ICT.
        try:
            from app.engines.worst_day_itm_fade import worst_day_defensive_session_active
            from app.engines.worst_day_guard import session_entry_policy
            from app.engines.dual_mode_strategy import resolve_trading_session_mode
            from app.models.schemas import AutoTraderState as _ATS

            snaps = snapshots or ({snap.symbol: snap} if snap is not None else {})
            st = state if state is not None else _ATS()
            if snaps:
                if worst_day_defensive_session_active(st, snaps):
                    return False
                policy, _ = session_entry_policy(st, snaps)
                if policy in ("BREAKOUT_ONLY", "PAUSED"):
                    return False
                mode, _ = resolve_trading_session_mode(st, snaps)
                if mode == "DEFENSIVE":
                    return False
        except Exception:
            return False
    if not bool(alert.get("ictFlatThenVertical") or alert.get("ictBreakout")):
        return False
    min_ict = float(getattr(settings, "explosion_building_elite_min_ict_score", 35.0) or 35.0)
    if float(alert.get("ictScore") or 0) < min_ict and not bool(alert.get("ictFlatThenVertical")):
        return False
    # Elite-build bars — soft/cold BUILDING (Aug7 score 56 / v3 1.7) must wait.
    min_score = float(getattr(settings, "explosion_building_elite_min_score", 62.0) or 62.0)
    score = float(
        alert.get("explosionScore")
        or alert.get("score")
        or 0
    )
    if score < min_score:
        return False
    min_v3 = float(
        getattr(settings, "explosion_building_elite_min_velocity_3s", 2.5) or 2.5
    )
    v3 = float(alert.get("velocity3s") or alert.get("velocity_3s") or 0)
    if v3 < min_v3:
        return False
    min_v9 = float(
        getattr(settings, "explosion_building_elite_min_velocity_9s", 2.5) or 2.5
    )
    v9 = float(alert.get("velocity9s") or alert.get("velocity_9s") or 0)
    if v9 < min_v9:
        return False
    side_raw = str(alert.get("side") or "").upper()
    if side_raw not in ("CALL", "PUT"):
        return False
    from app.engines.spot_direction import side_aligned_with_chart

    if snap.spotChart is None:
        return False
    if not side_aligned_with_chart(Side(side_raw), snap.spotChart):
        return False
    # Prefer heat — volume / displacement / early break flags on the alert.
    heat = (
        bool(alert.get("ictVolumeAwakening") or alert.get("volumeAwakening"))
        or bool(alert.get("ictDisplacement") or alert.get("displacement"))
        or bool(alert.get("ictPremiumFvg") or alert.get("premiumFvg"))
        or v3 >= min_v3
    )
    if not (heat or bool(alert.get("ictFlatThenVertical"))):
        return False
    # GainzAlgo-style Smart Ichimoku break-P on index chart.
    from app.engines.smart_ichimoku import ichimoku_break_supports_side

    ok, _ = ichimoku_break_supports_side(Side(side_raw), snap, require_confirmed=True)
    return ok


def _reentry_blocked(
    symbol: str,
    side: Side,
    strike: float,
    snap: SymbolSnapshot,
    *,
    explosion_event: Any = None,
    mode: str = "",
) -> tuple[bool, str]:
    blocked, reason = symbol_in_cooldown(symbol)
    if blocked:
        return True, reason
    blocked, reason = instrument_in_cooldown(symbol, side, strike)
    if blocked and explosion_event is not None:
        from app.engines.extreme_explosion_moment import is_high_mover_elite_bypass

        if is_high_mover_elite_bypass(event=explosion_event):
            blocked = False
    if blocked:
        return True, reason
    if explosion_event is not None:
        from app.engines.aligned_side_guard import breadth_hard_blocks_side
        from app.engines.morning_premium_capture import counter_trend_entry_allowed

        bias = (snap.breadth.bias if snap.breadth else "NEUTRAL") or "NEUTRAL"
        hard_blocked, hard_reason = breadth_hard_blocks_side(
            side, bias, event=explosion_event, snap=snap,
        )
        if hard_blocked:
            return True, hard_reason
        if not counter_trend_entry_allowed(side, snap, explosion_event=explosion_event):
            return True, "counter_trend_requires_elite"
    from app.engines.directional_lock import check_directional_side_lock
    from app.engines.morning_premium_capture import premium_led_bypass_for_snap
    from types import SimpleNamespace

    premium_bypass = premium_led_bypass_for_snap(side, snap, explosion_event=explosion_event)
    tier = str(getattr(explosion_event, "tier", "") or "")
    resolved_mode = (mode or ("explosion" if explosion_event is not None else "")).lower()
    lock_candidate = None
    if explosion_event is not None:
        lock_candidate = SimpleNamespace(
            mode="explosion",
            symbol=symbol,
            side=side,
            strike=strike,
            score=float(getattr(explosion_event, "explosion_score", 0) or 0),
            tier=tier,
            explosion_event=explosion_event,
        )
    blocked, reason = check_directional_side_lock(
        symbol, side, snap, tier=tier, premium_led_bypass=premium_bypass,
        candidate=lock_candidate,
    )
    if blocked:
        return True, reason
    if instrument_daily_cap_reached(symbol, side, strike, mode=resolved_mode):
        return True, f"instrument_daily_cap_{symbol}_{side.value}_{int(strike)}"
    if requires_breadth_alignment(symbol) and not side_aligned_with_breadth(
        side.value, snap.breadth.bias,
    ):
        return True, "symbol_requires_breadth_alignment"
    return False, "ok"


def _explosion_candidates(
    symbol: str,
    snap: SymbolSnapshot,
    state: AutoTraderState,
    settings,
) -> list[EntryCandidate]:
    from app.engines.explosion_detector import ExplosionEvent, effective_explosion_min_score

    out: list[EntryCandidate] = []
    for alert in snap.explosionAlerts or []:
        if not alert.get("tradeable"):
            continue
        if not premium_in_band(
            alert.get("premium"),
            mode="explosion",
            peak_move_pct=float(alert.get("peakMovePct") or 0),
            snap=snap,
        ):
            continue
        from app.engines.ict_breakout_monitor import first_lift_entry_readiness

        first_lift_ready, first_lift_readiness_reason = first_lift_entry_readiness(
            snap=snap,
            alert=alert,
            state=state,
        )
        side_v = str(alert.get("side") or "").upper()
        try:
            strike_v = float(alert.get("strike") or 0)
        except (TypeError, ValueError):
            strike_v = 0.0
        spot_v = float(snap.spot or 0)
        atm_v = float(snap.atmStrike or 0)
        if side_v in ("CALL", "PUT") and strike_v > 0 and spot_v > 0:
            money = classify_moneyness(
                Side(side_v),
                strike_v,
                spot_v,
                symbol=symbol,
                atm=atm_v if atm_v > 0 else None,
            )
            if money == "OTM":
                continue
        tier_u = str(alert.get("tier") or "").upper()
        elite_only = bool(getattr(settings, "explosion_elite_exploding_only", True))
        if elite_only:
            if tier_u not in ("ELITE", "EXPLODING"):
                # Early BUILDING flat→vertical when chart-aligned — catch the base
                # before ELITE prints (multiple flat→vertical moments per week).
                if not first_lift_ready and not _building_aligned_ict_alert_ok(
                    alert, snap, tier_u, state=state, snapshots={symbol: snap},
                ):
                    continue
        elif tier_u not in ("ELITE", "EXPLODING"):
            from app.engines.morning_premium_capture import is_premium_capture_alert

            ict_ok = bool(alert.get("ictBreakout")) and float(alert.get("ictScore") or 0) >= 28
            if not is_premium_capture_alert(alert, snap.spotChart) and not ict_ok:
                continue
        # Only when chart aligns — drop counter-trend explosions at selection.
        if bool(getattr(settings, "explosion_require_chart_align_enabled", True)):
            from app.engines.spot_direction import side_aligned_with_chart
            from app.models.schemas import Side as _Side

            side_raw = str(alert.get("side") or "").upper()
            side_v = None
            if side_raw in ("CALL", "PUT"):
                try:
                    side_v = _Side(side_raw)
                except Exception:
                    side_v = None
            if (
                side_v is not None
                and snap.spotChart is not None
                and not side_aligned_with_chart(side_v, snap.spotChart)
                and not first_lift_ready
            ):
                # A confirmed local base off which the side is breaking may survive the
                # chart-align drop — mirror check_explosion_entry so a genuine base rip
                # (e.g. SENSEX PE off a tight base while the 5m spot chart hasn't flipped
                # yet) is not silently dropped here before the downstream local-base
                # bypass runs. local_base_ichimoku_chart_bypass still requires a confirmed
                # base AND non-adverse live momentum, so this cannot admit chop FOMO.
                local_base_ok = False
                if bool(
                    getattr(
                        settings,
                        "explosion_selector_local_base_chart_bypass_enabled",
                        True,
                    )
                ):
                    from app.engines.local_base_chart_bypass import (
                        local_base_ichimoku_chart_bypass,
                    )

                    local_base_ok = local_base_ichimoku_chart_bypass(
                        side_v, snap, alert=alert,
                    )
                if not local_base_ok:
                    continue
        score_val = float(alert.get("explosionScore", 0))
        daily_move = float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0)
        peak_move = float(alert.get("peakMovePct") or 0)
        tier_str = str(alert.get("tier") or "WATCH")
        min_explosion_score = effective_explosion_min_score(
            tier=tier_str,
            peak_move_pct=peak_move,
            daily_move_pct=daily_move,
        )
        if first_lift_ready:
            min_explosion_score = min(
                min_explosion_score,
                float(
                    getattr(settings, "first_lift_trade_min_score", 45.0)
                    or 45.0
                ),
            )
        if score_val < min_explosion_score:
            continue
        # Explosion score is primary quality — don't block on low symbol TQS alone
        if (
            not first_lift_ready
            and snap.tradeQualityScore < 25
            and score_val < settings.aggressive_min_explosion_score + 10
        ):
            continue

        event = ExplosionEvent(
            symbol=symbol,
            side=Side(alert["side"]),
            strike=alert["strike"],
            premium=alert["premium"],
            velocity_3s=alert.get("velocity3s", 0),
            velocity_9s=alert.get("velocity9s", 0),
            velocity_15s=alert.get("velocity15s", 0),
            volume_surge=alert.get("volumeSurge", 1),
            explosion_score=score_val,
            tier=alert.get("tier", "WATCH"),
            reason=alert.get("reason", ""),
            daily_move_pct=daily_move,
            peak_move_pct=peak_move,
            volume=float(alert.get("volume") or 0),
        )
        from app.engines.morning_premium_capture import counter_trend_entry_allowed

        if not counter_trend_entry_allowed(event.side, snap, explosion_event=event):
            continue
        from app.engines.winner_entry_guards import chop_weak_explosion_blocks_entry

        cand_probe = EntryCandidate(
            symbol=symbol, snap=snap, mode="explosion", score=score_val,
            side=event.side, strike=event.strike, premium=event.premium,
            strategy_type=StrategyType.EXPLOSIVE, confidence=score_val,
            tqs=snap.tradeQualityScore,
            tier=event.tier, explosion_event=event, alert=alert,
        )
        chop_blocked, _ = chop_weak_explosion_blocks_entry(cand_probe, snap)
        if chop_blocked:
            continue
        suggestion = SuggestedTrade(
            id=alert.get("id", "x"),
            symbol=symbol,
            side=event.side,
            strike=event.strike,
            lastPremium=event.premium,
            tqs=snap.tradeQualityScore,
            strategyType=StrategyType.EXPLOSIVE,
            confidence=score_val,
        )
        blocked = state.calibrationBlocks.get(event.side.value, False)
        moment, _ = index_moment_active(snap)
        moment_surge = moment and side_aligned_with_index_moment(event.side, snap)
        passed, _ = check_explosion_entry(
            event, suggestion, snap.breadth, blocked,
            index_moment=moment_surge,
            chart=snap.spotChart,
            snap=snap,
            alert=alert if isinstance(alert, dict) else None,
        )
        if not passed:
            continue

        from app.engines.rally_capture import cross_side_chase_blocked

        blocked_x, _ = cross_side_chase_blocked(event, snap)
        if blocked_x:
            continue

        blocked, reason = _reentry_blocked(
            symbol, event.side, event.strike, snap, explosion_event=event,
        )
        if blocked:
            continue

        rank = score_val * 0.55 + snap.tradeQualityScore * 0.25
        if first_lift_readiness_reason == "first_lift_option_led_ready":
            rank += float(
                getattr(settings, "first_lift_option_led_rank_bonus", 12.0) or 12.0
            )
        if event.tier == "ELITE":
            rank += 15
        rank += min(15, event.velocity_3s * 2)
        rank += min(10, event.velocity_9s)
        rank += index_moment_rank_bonus(snap, event.side)
        rank += chart_rank_adjustment(event.side, snap.spotChart)
        rank += moneyness_rank_adjustment(
            event.side, event.strike, snap, mode="explosion", candidate_score=rank,
            snapshots={symbol: snap},
        )
        from app.engines.rally_capture import atm_proximity_rank_bonus, runner_strike_rank_bonus

        rank += runner_strike_rank_bonus(event, snap)
        rank += atm_proximity_rank_bonus(event, snap)
        from app.engines.dual_mode_strategy import resolve_trading_session_mode
        from app.engines.ict_breakout_monitor import (
            analyze_explosion_event_ict,
            ict_explosion_rank_bonus,
            late_fade_chase_blocked,
        )

        trading_mode, _ = resolve_trading_session_mode(state, {symbol: snap})
        ict = analyze_explosion_event_ict(event, snap)
        if not ict.active and alert.get("ictBreakout"):
            from app.engines.ict_breakout_monitor import ICTBreakoutSignal

            ict = ICTBreakoutSignal(
                active=bool(alert.get("ictBreakout")),
                pattern=str(alert.get("ictPattern") or "watch"),
                score=float(alert.get("ictScore") or 0),
                reasons=list(alert.get("ictReasons") or []),
                premium_fvg=bool(alert.get("ictPremiumFvg")),
                flat_then_vertical=bool(alert.get("ictFlatThenVertical")),
                mega_rip=bool(alert.get("ictMegaRip")),
                volume_awakening=bool(alert.get("volumeAwaken") or alert.get("ictVolumeAwakening")),
                displacement=bool(alert.get("ictDisplacement")),
                session_move_pct=max(daily_move, peak_move),
                velocity_3s=float(alert.get("velocity3s") or 0),
                volume_surge=float(alert.get("volumeSurge") or 0),
                base_relative_move_pct=float(alert.get("ictBaseRelativeMovePct") or 0),
                base_premium=float(alert.get("ictBasePremium") or 0),
                local_swing_base=bool(alert.get("ictLocalSwingBase")),
                flat_vertical_quality=float(alert.get("flatVerticalQuality") or 0),
                flat_vertical_grade=str(alert.get("flatVerticalGrade") or ""),
                first_lift=bool(alert.get("ictFirstLift")),
                base_armed=bool(alert.get("ictBaseArmed")),
                elite_base_ready=bool(alert.get("ictEliteBaseReady")),
                v_rip_ready=bool(alert.get("ictVRipReady")),
                building_rip_ready=bool(alert.get("ictBuildingRipReady")),
                armed_base_launch=bool(alert.get("ictArmedBaseLaunch")),
                armed_base_samples=int(alert.get("ictArmedBaseSamples") or 0),
                armed_base_span_seconds=float(
                    alert.get("ictArmedBaseSpanSeconds") or 0
                ),
                armed_base_range_pct=float(
                    alert.get("ictArmedBaseRangePct") or 0
                ),
                armed_at=str(alert.get("ictBaseArmedAt") or ""),
                armed_base_expires_at=str(alert.get("ictBaseExpiresAt") or ""),
            )
        from app.engines.elite_never_block import elite_never_block_active

        must_take = elite_never_block_active(
            event=event, candidate=cand_probe, alert=alert, snap=snap, ict=ict,
        )
        from app.engines.bullish_local_base import bullish_local_base_prediction

        bullish_base = bullish_local_base_prediction(
            snap, event, ict, alert=alert,
        )
        late_blocked, _late_reason = late_fade_chase_blocked(event, ict, snap=snap)
        if late_blocked:
            continue
        from app.engines.explosion_entry_guards import (
            detect_fake_explosion_trap,
            explosion_entry_window_blocked,
            extended_session_chase_blocked,
            immature_explosion_blocked,
            live_explosion_confirmation_blocked,
        )

        immature_blocked, _immature_reason = immature_explosion_blocked(
            event,
            ict=ict,
            bullish_local_base=bool(bullish_base.get("active")),
        )
        if immature_blocked and not must_take and not first_lift_ready:
            continue
        # Must-take already proved the 10–65% near-base band; pass that so the
        # hard window does not re-raise the unstructured 28% floor.
        from app.engines.advanced_indicators import squeeze_early_base_active

        window_blocked, _window_reason = explosion_entry_window_blocked(
            event, ict=ict, top_must_take=must_take,
            squeeze_early_base=squeeze_early_base_active(event, snap),
            bullish_local_base=bool(bullish_base.get("active")),
        )
        if window_blocked and not first_lift_ready:
            continue
        from app.engines.morning_premium_capture import is_premium_capture_event

        live_blocked, _live_reason = live_explosion_confirmation_blocked(
            event,
            ict=ict,
            premium_capture=is_premium_capture_event(event, chart=snap.spotChart),
            snap=snap,
        )
        if live_blocked and not must_take:
            continue
        from app.engines.entry_timing import assess_entry_timing, timing_blocks_entry

        timing = assess_entry_timing(
            event,
            ict=ict,
            snap=snap,
            premium_capture=is_premium_capture_event(event, chart=snap.spotChart),
        )
        timing_blocked, _timing_reason = timing_blocks_entry(timing)
        if (
            timing_blocked
            and not must_take
            and not (
                first_lift_ready
                and bool(
                    getattr(
                        settings,
                        "first_lift_bypasses_cold_timing_enabled",
                        True,
                    )
                )
            )
        ):
            continue
        ext_blocked, _ext_reason = extended_session_chase_blocked(event, ict=ict)
        building_rip_ready_take = first_lift_readiness_reason in (
            "building_rip_bullish_ready",
            "building_local_base_lift_ready",
        )
        from app.engines.building_ftv_gates import (
            building_rip_bypasses_extended_chase,
            building_rip_bypasses_fake_trap,
        )

        if (
            ext_blocked
            and not must_take
            and not building_rip_bypasses_extended_chase(
                alert=alert if isinstance(alert, dict) else None,
                readiness_reason=first_lift_readiness_reason,
            )
        ):
            continue
        trap_block, _trap_reason, trap_meta = detect_fake_explosion_trap(
            cand_probe, snap, state=state, ict=ict,
        )
        if (
            (trap_block or trap_meta.get("action") == "block")
            and not building_rip_bypasses_fake_trap(
                alert=alert if isinstance(alert, dict) else None,
                readiness_reason=first_lift_readiness_reason,
            )
        ):
            continue
        # Displacement-only without flat base / FVG / real rip — skip (Jul20 noise).
        # Raised floor to early-window min (28%) so ~22% displacement spikes stay out.
        if (
            ict.active
            and ict.displacement
            and not ict.flat_then_vertical
            and not ict.premium_fvg
            and not ict.mega_rip
            and not ict.volume_awakening
            and max(daily_move, peak_move) < float(
                getattr(settings, "explosion_early_window_min_move_pct", 28.0) or 28.0
            )
        ):
            continue
        rank += ict_explosion_rank_bonus(ict, trading_mode)
        if first_lift_readiness_reason in (
            "armed_base_option_led_ready",
            "elite_base_ready_s_preauthorized",
            "v_rip_session_low_ready",
            "building_rip_bullish_ready",
            "building_local_base_lift_ready",
        ):
            rank += float(
                getattr(settings, "ict_armed_base_launch_rank_bonus", 16.0) or 16.0
            )
            if first_lift_readiness_reason in (
                "building_rip_bullish_ready",
                "building_local_base_lift_ready",
            ):
                rank += float(
                    getattr(settings, "building_rip_rank_bonus", 14.0) or 14.0
                )
        # Early flat→vertical breakouts (26→45 CE / 12→40 PE) jump the queue —
        # including DEFENSIVE days when volume/displacement confirms the base break.
        if ict.flat_then_vertical and ict.active:
            if trading_mode != "DEFENSIVE":
                rank += 12.0 if ict.volume_awakening or ict.displacement else 8.0
            elif ict.volume_awakening or ict.displacement:
                rank += 16.0  # rare clean base rip on bad day — prioritize
            # Grade the flat→vertical: a tight, long, heated coil (A/A+) jumps the queue.
            if bool(getattr(settings, "flat_vertical_quality_rank_enabled", True)):
                fvq = float(getattr(ict, "flat_vertical_quality", 0) or 0)
                if fvq > 0:
                    rank += float(
                        getattr(settings, "flat_vertical_quality_rank_max", 12.0) or 12.0
                    ) * (fvq / 100.0)
        # Prefer early expansion window; demote already-extended rips in ranking.
        early_min = float(getattr(settings, "explosion_early_window_min_move_pct", 28.0) or 28.0)
        early_max = float(getattr(settings, "explosion_early_window_max_move_pct", 55.0) or 55.0)
        move_for_rank = max(daily_move, peak_move)
        if early_min <= move_for_rank <= early_max and (ict.flat_then_vertical or ict.displacement):
            rank += 14.0
        elif move_for_rank > early_max and not (ict.flat_then_vertical and ict.volume_awakening):
            rank -= min(35.0, (move_for_rank - early_max) * 0.6)
        # Squeeze (Bollinger-in-Keltner) release toward this side = fresh base->explosion.
        # Weighted UP when it fires AT a confirmed local base, so the top-ranked signal is
        # "squeeze releasing at the base" — exactly catch-it-at-the-base.
        if bool(getattr(settings, "squeeze_rank_bonus_enabled", True)):
            from app.engines.advanced_indicators import index_squeeze_confirms_side

            if index_squeeze_confirms_side(event.side, snap):
                sq_bonus = float(getattr(settings, "squeeze_rank_bonus", 10.0) or 10.0)
                at_local_base = bool(
                    ict.flat_then_vertical
                    or getattr(ict, "local_swing_base", False)
                    or float(getattr(ict, "base_relative_move_pct", 0) or 0) > 0
                )
                rank += sq_bonus * (1.5 if at_local_base else 1.0)

        # ADX regime + VWAP reclaim — selection-quality nudges (additive, never a gate).
        from app.engines.advanced_indicators import (
            index_adx_rank_adjust,
            index_vwap_confirms_side,
        )

        rank += index_adx_rank_adjust(event.side, snap)
        if index_vwap_confirms_side(event.side, snap):
            rank += float(getattr(settings, "vwap_reclaim_rank_bonus", 6.0) or 6.0)

        # CVD authenticity + acceleration — additive only, never an entry bypass.
        from app.engines.advanced_indicators import (
            option_cvd_acceleration_confirms_buying,
            option_cvd_confirms_buying,
        )

        if bool(getattr(settings, "cvd_confirm_enabled", True)):
            if option_cvd_confirms_buying(snap, event.strike, event.side):
                rank += float(getattr(settings, "cvd_rank_bonus", 5.0) or 5.0)
        if bool(getattr(settings, "cvd_acceleration_enabled", True)):
            if option_cvd_acceleration_confirms_buying(
                snap, event.strike, event.side,
            ):
                rank += float(
                    getattr(settings, "cvd_acceleration_rank_bonus", 4.0) or 4.0
                )
        # Directional prediction at the local bottom is symmetric for CE and PE and
        # additive. It helps the confirmed reversal leg win selection; no safety gate is
        # bypassed, and execution-time premium validation still has the final word.
        rank += float(bullish_base.get("rankBonus") or 0.0)

        out.append(EntryCandidate(
            symbol=symbol,
            snap=snap,
            mode="explosion",
            score=rank,
            side=event.side,
            strike=event.strike,
            premium=event.premium,
            strategy_type=StrategyType.EXPLOSIVE,
            confidence=score_val,
            tqs=snap.tradeQualityScore,
            tier=event.tier,
            explosion_event=event,
            alert=alert,
            pretrade_meta={
                "localBaseReversalPrediction": bullish_base,
                "bullishLocalBasePrediction": bullish_base,
                "timingAssessment": timing,
                "ictBaseArmed": bool(alert.get("ictBaseArmed")),
                "ictEliteBaseReady": bool(alert.get("ictEliteBaseReady")),
                "ictArmedBaseLaunch": bool(alert.get("ictArmedBaseLaunch")),
                "ictBasePremium": float(alert.get("ictBasePremium") or 0),
                "ictBaseRelativeMovePct": float(
                    alert.get("ictBaseRelativeMovePct") or 0
                ),
                "ictBaseArmedAt": alert.get("ictBaseArmedAt"),
            },
        ))
    return out


def _matching_radar_alert(
    snap: SymbolSnapshot,
    side: Side | str,
    strike: float,
) -> Optional[dict]:
    """Nearest explosionAlerts row for this scalp leg (same side, strike within 0.5)."""
    side_v = side.value if isinstance(side, Side) else str(side).upper()
    strike_f = float(strike or 0)
    for alert in snap.explosionAlerts or []:
        if not isinstance(alert, dict):
            continue
        if str(alert.get("side") or "").upper() != side_v:
            continue
        if abs(float(alert.get("strike") or 0) - strike_f) > 0.5:
            continue
        return alert
    top = snap.topExplosion or {}
    if (
        isinstance(top, dict)
        and str(top.get("side") or "").upper() == side_v
        and abs(float(top.get("strike") or 0) - strike_f) <= 0.5
    ):
        return top
    return None


def _tradeable_explosion_on_side(snap: SymbolSnapshot, side: Side | str) -> bool:
    """True when radar already has a tradeable EXPLODING/ELITE on this side."""
    side_v = side.value if isinstance(side, Side) else str(side).upper()
    for alert in snap.explosionAlerts or []:
        if str(alert.get("side") or "").upper() != side_v:
            continue
        if not alert.get("tradeable"):
            continue
        tier = str(alert.get("tier") or "").upper()
        if tier in ("ELITE", "EXPLODING"):
            return True
    top = snap.topExplosion or {}
    if (
        str(top.get("side") or "").upper() == side_v
        and str(top.get("tier") or "").upper() in ("ELITE", "EXPLODING")
        and top.get("tradeable", True)
    ):
        return True
    return False


def _scalp_local_base_active(
    candidate: "EntryCandidate",
    snap: SymbolSnapshot,
    settings,
) -> tuple[bool, Optional[dict]]:
    """Confirmed local-base structure for this scalp strike (from radar alert)."""
    if not getattr(settings, "scalp_local_base_enabled", True):
        return False, None
    alert = getattr(candidate, "alert", None)
    if not isinstance(alert, dict):
        alert = _matching_radar_alert(snap, candidate.side, float(candidate.strike))
    if alert is None:
        return False, None
    from app.engines.local_base_chart_bypass import local_base_structure_active

    if local_base_structure_active(candidate.side, snap, alert=alert):
        return True, alert
    return False, alert


def _scalp_best_quality_ok(
    candidate: "EntryCandidate",
    snap: SymbolSnapshot,
    settings,
) -> tuple[bool, str]:
    """Only allow strong scalps; local-base structure softens floors (not alignment FOMO)."""
    if not getattr(settings, "scalp_best_only_enabled", True):
        return True, "ok"

    local_ok, alert = _scalp_local_base_active(candidate, snap, settings)
    min_rank = float(getattr(settings, "scalp_best_min_rank_score", 84.0) or 84.0)
    min_conf = float(getattr(settings, "scalp_best_min_chart_confidence", 68.0) or 68.0)
    min_vel = float(getattr(settings, "scalp_best_min_velocity_pct", 1.0) or 1.0)
    if local_ok:
        min_rank = min(
            min_rank,
            float(getattr(settings, "scalp_local_base_min_rank_score", 80.0) or 80.0),
        )
        min_conf = min(
            min_conf,
            float(getattr(settings, "scalp_local_base_min_chart_confidence", 62.0) or 62.0),
        )
        min_vel = min(
            min_vel,
            float(getattr(settings, "scalp_local_base_min_velocity_pct", 0.8) or 0.8),
        )

    if float(candidate.score or 0) < min_rank:
        return False, f"scalp_best_rank_below_{min_rank:.0f}"

    if getattr(settings, "scalp_best_require_breadth_aligned", True) and not local_ok:
        bias = (snap.breadth.bias if snap.breadth else "NEUTRAL") or "NEUTRAL"
        side_v = candidate.side.value if isinstance(candidate.side, Side) else str(candidate.side).upper()
        want = "BULLISH" if side_v == "CALL" else "BEARISH"
        if bias != want:
            return False, "scalp_best_breadth_not_aligned"

    if getattr(settings, "scalp_best_require_chart_aligned", True) and not local_ok:
        from app.engines.spot_direction import side_aligned_with_chart

        if not side_aligned_with_chart(candidate.side, snap.spotChart):
            return False, "scalp_best_chart_not_aligned"

    if getattr(settings, "scalp_best_atm_itm_only", True):
        from app.engines.moneyness import classify_moneyness, _depth_steps

        money = classify_moneyness(
            candidate.side,
            float(candidate.strike),
            float(snap.spot or 0),
            symbol=snap.symbol,
            atm=float(snap.atmStrike or 0) or None,
        )
        if money not in ("ATM", "ITM"):
            if local_ok and money == "OTM":
                max_steps = int(
                    getattr(settings, "scalp_local_base_max_otm_steps", 3) or 3
                )
                atm = float(snap.atmStrike or 0) or float(snap.spot or 0)
                depth = _depth_steps(
                    candidate.side,
                    float(candidate.strike),
                    float(snap.spot or 0),
                    snap.symbol,
                    atm,
                )
                if depth > max_steps:
                    return False, f"scalp_local_base_otm_too_deep_{depth}"
            else:
                return False, f"scalp_best_requires_atm_itm_{money.lower()}"

    if min_conf > 0:
        from app.engines.chart_exit_levels import chart_trade_confidence

        conf, _ = chart_trade_confidence(snap, candidate.side)
        if conf < min_conf:
            return False, f"scalp_best_chart_conf_below_{min_conf:.0f}"

    vel = 0.0
    sug = candidate.suggestion
    if sug is not None and getattr(sug, "runnerSignal", None) is not None:
        vel = float(sug.runnerSignal.premiumVelocityPct or 0)
    if alert is not None:
        vel = max(vel, float(alert.get("velocity3s") or 0))
    if vel < min_vel:
        # Heatmap rows may lack runnerSignal — allow if confidence clears rank floor.
        if float(candidate.confidence or 0) < min_rank:
            return False, f"scalp_best_velocity_below_{min_vel}"

    if getattr(settings, "scalp_best_defer_to_explosion", True) and not local_ok:
        if _tradeable_explosion_on_side(snap, candidate.side):
            return False, "scalp_best_defer_to_explosion"

    return True, "ok"


def _scalp_candidates(
    symbol: str,
    snap: SymbolSnapshot,
    state: AutoTraderState,
    settings,
) -> list[EntryCandidate]:
    out: list[EntryCandidate] = []
    for suggestion in snap.suggestedTrades or []:
        if suggestion.strategyType == StrategyType.EXPLOSIVE:
            continue
        if not premium_in_band(suggestion.lastPremium):
            continue
        if not suggestion.lastPremium or suggestion.lastPremium <= 0:
            continue
        trade_score = max(suggestion.tqs, suggestion.confidence or 0)
        if trade_score < settings.aggressive_min_tqs:
            continue

        blocked = state.calibrationBlocks.get(suggestion.side.value, False)
        moment, _ = index_moment_active(snap)
        moment_surge = moment and side_aligned_with_index_moment(suggestion.side, snap)
        momentum = (snap.orderflow.volumeAcceleration or 0) > 65 or moment_surge
        override = snap.explosiveRunner.candidate and (snap.explosiveRunner.score or 0) >= 82
        vel = suggestion.runnerSignal.premiumVelocityPct if suggestion.runnerSignal else 0

        passed, _ = check_entry_gate(
            suggestion, snap.breadth, max(snap.tradeQualityScore, trade_score), vel,
            blocked, momentum_surge=momentum, alignment_override=override,
            chart=snap.spotChart, snap=snap,
        )
        if not passed:
            continue

        blocked, reason = _reentry_blocked(
            symbol, suggestion.side, suggestion.strike, snap, mode="scalp",
        )
        if blocked:
            continue

        rank = suggestion.tqs * 0.5 + suggestion.confidence * 0.3 + snap.tradeQualityScore * 0.2
        if snap.breadth.aligned:
            rank += 8
        if momentum:
            rank += 5
        rank += index_moment_rank_bonus(snap, suggestion.side)
        rank += chart_rank_adjustment(suggestion.side, snap.spotChart)
        rank += moneyness_rank_adjustment(
            suggestion.side, suggestion.strike, snap, mode="scalp", candidate_score=rank,
            snapshots={symbol: snap},
        )

        alert = _matching_radar_alert(snap, suggestion.side, float(suggestion.strike))
        out.append(EntryCandidate(
            symbol=symbol,
            snap=snap,
            mode="scalp",
            score=rank,
            side=suggestion.side,
            strike=suggestion.strike,
            premium=suggestion.lastPremium,
            strategy_type=suggestion.strategyType,
            confidence=suggestion.confidence,
            tqs=suggestion.tqs,
            suggestion=suggestion,
            alert=alert,
        ))

    for row in heatmap_moneyness_candidates(symbol, snap, snapshots={symbol: snap}):
        suggestion = row["suggestion"]
        blocked, reason = _reentry_blocked(
            symbol, suggestion.side, suggestion.strike, snap, mode="scalp",
        )
        if blocked:
            continue
        rank = float(row["score"]) + snap.tradeQualityScore * 0.2
        rank += moneyness_rank_adjustment(
            suggestion.side, suggestion.strike, snap, mode="scalp", candidate_score=rank,
            snapshots={symbol: snap},
        )
        alert = _matching_radar_alert(snap, suggestion.side, float(suggestion.strike))
        out.append(EntryCandidate(
            symbol=symbol,
            snap=snap,
            mode="scalp",
            score=rank,
            side=suggestion.side,
            strike=suggestion.strike,
            premium=row["premium"],
            strategy_type=StrategyType.SCALP,
            confidence=suggestion.confidence,
            tqs=suggestion.tqs,
            suggestion=suggestion,
            alert=alert,
        ))
    if getattr(settings, "scalp_best_only_enabled", True):
        kept: list[EntryCandidate] = []
        for c in out:
            ok, _ = _scalp_best_quality_ok(c, snap, settings)
            if ok:
                kept.append(c)
        return kept
    return out


def _worst_day_candidates(
    symbol: str,
    snap: SymbolSnapshot,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> list[EntryCandidate]:
    if not worst_day_defensive_session_active(state, snapshots):
        return []
    out: list[EntryCandidate] = []
    for setup in scan_worst_day_itm_fade_setups(symbol, snap, state, snapshots):
        side = setup["side"]
        strike = float(setup["strike"])
        premium = float(setup["premium"])
        blocked, _ = _reentry_blocked(symbol, side, strike, snap)
        if blocked:
            continue
        out.append(EntryCandidate(
            symbol=symbol,
            snap=snap,
            mode="worst_day_itm_fade",
            score=float(setup["score"]),
            side=side,
            strike=strike,
            premium=premium,
            strategy_type=StrategyType.SCALP,
            confidence=float(setup["score"]),
            tqs=snap.tradeQualityScore,
            pretrade_meta={
                "worstDayItmFade": True,
                "velocityPct": setup.get("velocityPct"),
                "worstDayFadeMeta": setup.get("worstDayFadeMeta"),
            },
        ))

    settings = get_settings()
    if (
        settings.worst_day_quick_enabled
        and not getattr(settings, "worst_day_block_quick_trades", True)
    ):
        for setup in scan_worst_day_quick_setups(symbol, snap, state, snapshots):
            side = setup["side"]
            strike = float(setup["strike"])
            premium = float(setup["premium"])
            blocked, _ = _reentry_blocked(symbol, side, strike, snap)
            if blocked:
                continue
            out.append(EntryCandidate(
                symbol=symbol,
                snap=snap,
                mode="quick_sideways",
                score=float(setup["score"]),
                side=side,
                strike=strike,
                premium=premium,
                strategy_type=StrategyType.SCALP,
                confidence=float(setup["score"]),
                tqs=snap.tradeQualityScore,
                pretrade_meta={
                    "quickSideways": True,
                    "worstDayQuick": True,
                    "velocityPct": setup.get("velocityPct"),
                },
            ))
    return out


def _quick_sideways_candidates(
    symbol: str,
    snap: SymbolSnapshot,
    state: AutoTraderState,
    settings,
    snapshots: dict[str, SymbolSnapshot],
) -> list[EntryCandidate]:
    if not quick_sideways_enabled():
        return []
    out: list[EntryCandidate] = []
    from app.engines.expiry_day_guards import expiry_pm_itm_quick_active

    for setup in scan_quick_sideways_setups(symbol, snap, state, snapshots):
        side = setup["side"]
        strike = float(setup["strike"])
        premium = float(setup["premium"])
        blocked, reason = _reentry_blocked(symbol, side, strike, snap)
        if blocked:
            continue

        out.append(EntryCandidate(
            symbol=symbol,
            snap=snap,
            mode="quick_sideways",
            score=float(setup["score"]),
            side=side,
            strike=strike,
            premium=premium,
            strategy_type=StrategyType.SCALP,
            confidence=float(setup["score"]),
            tqs=snap.tradeQualityScore,
            pretrade_meta={
                "quickSideways": True,
                "velocityPct": setup.get("velocityPct"),
                "expiryPmItmQuick": expiry_pm_itm_quick_active(snap, state, snapshots),
            },
        ))

    for setup in scan_slow_bounce_setups(symbol, snap, state, snapshots):
        side = setup["side"]
        strike = float(setup["strike"])
        premium = float(setup["premium"])
        blocked, reason = _reentry_blocked(symbol, side, strike, snap)
        if blocked:
            continue

        out.append(EntryCandidate(
            symbol=symbol,
            snap=snap,
            mode="slow_bounce",
            score=float(setup["score"]),
            side=side,
            strike=strike,
            premium=premium,
            strategy_type=StrategyType.SCALP,
            confidence=float(setup["score"]),
            tqs=snap.tradeQualityScore,
            pretrade_meta={
                "slowBounce": True,
                "velocityPct": setup.get("velocityPct"),
                "slowBounceMeta": setup.get("slowBounceMeta"),
                "expiryPmItmQuick": expiry_pm_itm_quick_active(snap, state, snapshots),
            },
        ))
    return out


def _swing_candidates(
    symbol: str,
    snap: SymbolSnapshot,
    state: AutoTraderState,
    settings,
) -> list[EntryCandidate]:
    if not settings.swing_trading_enabled:
        return []
    out: list[EntryCandidate] = []
    swing_open_keys = {
        (t.symbol, t.side.value)
        for t in state.openPaperTrades
        if t.strategyType == StrategyType.SWING
    }
    for alert in snap.swingAlerts or []:
        if not alert.get("tradeable"):
            continue
        if not premium_in_band(alert.get("premium")):
            continue
        if alert.get("confidence", 0) < settings.aggressive_min_swing_confidence:
            continue

        setup = SwingSetup(
            symbol=symbol,
            side=Side(alert["side"]),
            strike=alert["strike"],
            premium=alert["premium"],
            swingType=alert.get("swingType", "swing"),
            confidence=alert.get("confidence", 0),
            reason=alert.get("reason", ""),
            metadata=alert.get("metadata", {}),
        )
        blocked = state.calibrationBlocks.get(setup.side.value, False)
        passed, _ = check_swing_entry(setup, swing_open_keys, blocked)
        if not passed:
            continue

        rank = setup.confidence * 0.7 + snap.tradeQualityScore * 0.3
        out.append(EntryCandidate(
            symbol=symbol,
            snap=snap,
            mode="swing",
            score=rank,
            side=setup.side,
            strike=setup.strike,
            premium=setup.premium,
            strategy_type=StrategyType.SWING,
            confidence=setup.confidence,
            tqs=snap.tradeQualityScore,
            swing_setup=setup,
            alert=alert,
        ))
    return out


def find_best_entry(
    snapshots: dict[str, SymbolSnapshot],
    state: AutoTraderState,
    limits: Optional[Any] = None,
    excluded_keys: Optional[set[str]] = None,
) -> Optional[EntryCandidate]:
    """Return the highest-ranked setup not already selected in this radar cycle."""
    settings = get_settings()
    from app.engines.chop_day_guards import (
        is_chop_session,
        min_rank_for_entry,
        symbol_rank_adjustment,
    )
    from app.engines.daily_18pct_strategy import entries_allowed_by_limits
    from app.engines.pretrade_validator import collect_session_trades

    trades_today = len(collect_session_trades(state))

    scalp_open = sum(1 for t in state.openPaperTrades if t.strategyType != StrategyType.SWING)
    swing_open = sum(1 for t in state.openPaperTrades if t.strategyType == StrategyType.SWING)
    chop = is_chop_session(snapshots)
    max_scalp_slots = int(settings.aggressive_max_open_scalps)
    if getattr(settings, "ftv_ranked_allocation_enabled", True):
        max_scalp_slots = max(
            max_scalp_slots,
            int(getattr(settings, "ftv_allocation_max_positions", 3) or 3),
        )

    candidates: list[EntryCandidate] = []
    # ELITE/EXPLODING explosions; scalps off by default (Jul29 scalp sleeve bled).
    explosion_only = bool(getattr(settings, "explosion_only_trading_enabled", True))
    allow_guarded_scalp = bool(getattr(settings, "explosion_only_allow_guarded_scalp", False))
    scalp_entries = bool(getattr(settings, "scalp_entries_enabled", False))

    for symbol, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        if settings.explosion_capture_mode and scalp_open < max_scalp_slots:
            if not limits or getattr(limits, "allowExplosion", True):
                candidates.extend(_explosion_candidates(symbol, snap, state, settings))
        if (
            scalp_entries
            and (not explosion_only or allow_guarded_scalp)
            and settings.paper_simple_profit_mode
            and scalp_open < max_scalp_slots
        ):
            candidates.extend(_scalp_candidates(symbol, snap, state, settings))
        if (
            not explosion_only
            and quick_sideways_enabled()
            and scalp_open < max_scalp_slots
        ):
            candidates.extend(_quick_sideways_candidates(symbol, snap, state, settings, snapshots))
            candidates.extend(_worst_day_candidates(symbol, snap, state, snapshots))
        if not explosion_only and swing_open < settings.swing_max_open:
            candidates.extend(_swing_candidates(symbol, snap, state, settings))

    # A live premium fade is exact-leg and transient. Apply after fresh candidate
    # generation, before every promotion/risk-quality filter and final ranking.
    # Unlike the established loss cooldown, ELITE/high-mover paths cannot bypass it.
    candidates = _exclude_preorder_rejected_candidates(candidates)
    if excluded_keys:
        candidates = [
            candidate
            for candidate in candidates
            if (
                f"{candidate.symbol.upper()}:{candidate.side.value}:"
                f"{float(candidate.strike):g}"
            )
            not in excluded_keys
        ]
    if not candidates:
        return None

    # BUILDING LTP scoreboard: among X monitored BUILDING names, keep/boost only
    # the best ready leg that is actually selectable (fail soft if #1 was filtered).
    try:
        from app.engines.building_ltp_monitor import filter_candidates_building_best_pick

        candidates = filter_candidates_building_best_pick(candidates)
    except Exception:
        pass
    if not candidates:
        return None

    # SENSEX-first on chop days + session backtest index preference
    session_trades = collect_session_trades(state)
    index_adj = index_rank_from_backtest(compute_symbol_stats(session_trades))

    for c in candidates:
        c.score += symbol_rank_adjustment(c.symbol, chop)
        c.score += index_adj.get(c.symbol.upper(), 0.0)
        from app.engines.bad_day_routing import cross_index_elite_priority_bonus, cross_index_rank_adjustment

        c.score += cross_index_rank_adjustment(c, state, snapshots)
        c.score += cross_index_elite_priority_bonus(c, snapshots)
        if settings.edge_engine_enabled:
            edge = compute_entry_edge(c, c.snap, state)
            c.score += edge_rank_bonus(edge)
            c.pretrade_meta = {**(c.pretrade_meta or {}), "edgeScore": edge.total}
        exhausted = False
        if c.mode == "explosion":
            from app.engines.session_mode_feedback import (
                exhausted_ftv_reentry_blocked,
                failed_launch_reentry_blocked,
            )

            fail_blocked, _ = failed_launch_reentry_blocked(
                state,
                symbol=c.symbol,
                side=c.side,
                strike=float(c.strike or 0),
            )
            if fail_blocked:
                c.pretrade_meta = {
                    **(c.pretrade_meta or {}),
                    "failedLaunchReentryBlocked": True,
                    "causalRanking": {
                        "grade": "REJECT",
                        "reasons": ["failed_launch_reentry_cooldown"],
                    },
                }
                continue

            exhausted, _ = exhausted_ftv_reentry_blocked(
                state,
                symbol=c.symbol,
                side=c.side,
                strike=float(c.strike or 0),
                premium=float(c.premium or 0),
                velocity_3s=float(
                    getattr(c.explosion_event, "velocity_3s", 0) or 0
                ),
            )
        from app.engines.trade_ranking import (
            ftv_authorization_policy,
            ftv_policy_settings,
            rank_entry_candidate,
            resolve_policy_day_mode,
        )

        causal_ranking = rank_entry_candidate(c, exhausted_reentry=exhausted)
        policy_ok = True
        policy_reason = "disabled"
        if bool(getattr(settings, "ftv_elite_top_only_enabled", True)):
            from app.engines.moneyness import atm_itm_entry_allows

            money_ok, _, _ = atm_itm_entry_allows(c.side, c.strike, c.snap)
            policy_decision = ftv_authorization_policy(
                causal_ranking.get("evidence") or {},
                causal_ranking,
                snapshot_available=True,
                atm_itm_allowed=money_ok,
                day_mode=resolve_policy_day_mode(state),
                **ftv_policy_settings(settings),
            )
            policy_ok = policy_decision.allowed
            policy_reason = policy_decision.reason
            policy_mode = policy_decision.mode
            policy_cap = policy_decision.max_capital_pct
        else:
            policy_mode = None
            policy_cap = None
        c.pretrade_meta = {
            **(c.pretrade_meta or {}),
            "causalRanking": causal_ranking,
            "ftvEliteTopPolicy": {
                "enabled": bool(
                    getattr(settings, "ftv_elite_top_only_enabled", True)
                ),
                "passed": policy_ok,
                "reason": policy_reason,
                "authorizationMode": policy_mode,
                "maxCapitalPct": policy_cap,
            },
        }

    candidates = [
        c
        for c in candidates
        if (c.pretrade_meta or {}).get("causalRanking", {}).get("grade") != "REJECT"
        and (
            not bool(getattr(settings, "ftv_elite_top_only_enabled", True))
            or (c.pretrade_meta or {}).get("ftvEliteTopPolicy", {}).get("passed")
        )
    ]
    if not candidates:
        return None

    pf_fb = session_pf_feedback(state) if settings.edge_engine_enabled else None
    from app.engines.session_mode_feedback import compute_mode_stats, mode_session_rank_bonus

    mode_stats = compute_mode_stats(session_trades)

    if limits:
        day_mode = str(getattr(limits, "dayMode", "") or "")
        conf_tier = str(getattr(limits, "confidenceTier", "") or "MEDIUM")
        phase = str(getattr(limits, "phase", "") or "ACCUMULATE")
    else:
        from app.engines.chop_day_guards import chop_guard_summary

        chop_meta = chop_guard_summary(state, snapshots)
        day_mode = str(chop_meta.get("dayMode") or "NORMAL")
        conf_tier = "MEDIUM"
        phase = "ACCUMULATE"
    adaptive = resolve_day_adaptive(
        snapshots, state, day_mode=day_mode, confidence_tier=conf_tier, phase=phase,
    )

    from app.engines.dual_mode_strategy import (
        aggressive_min_rank_floor,
        resolve_trading_session_mode,
        skip_best_trades_only_filter,
    )

    trading_mode, _dual_meta = resolve_trading_session_mode(
        state,
        snapshots,
        day_mode=day_mode,
        confidence_tier=conf_tier,
    )

    if should_pause_regular_scalps(
        adaptive, edge_pause_scalps=bool(pf_fb and pf_fb.pause_quick_scalps),
    ):
        candidates = [c for c in candidates if c.mode != "scalp"]

    # Worst-day adaptive: drop quick_sideways only (scalp/momentum stay).
    if adaptive.allow_quick_sideways is False or adaptive.day_type == "WORST":
        candidates = [c for c in candidates if c.mode != "quick_sideways"]

    # When high-confidence base rips exist (missed-trade keep list), trade those
    # first so capital captures Jul15-style ELITE simultaneously — not cheap OTM.
    if (
        explosion_only
        and getattr(settings, "missed_explosion_promote_enabled", True)
    ):
        from app.engines.explosion_confidence import high_confidence_explosion

        top_causal = [
            c
            for c in candidates
            if (c.pretrade_meta or {}).get("causalRanking", {}).get("grade") == "S"
        ]
        preferred: list[EntryCandidate] = []
        for c in candidates:
            if c.mode != "explosion":
                continue
            ok, _, _ = high_confidence_explosion(
                side=c.side,
                strike=float(c.strike),
                premium=float(c.premium or 0),
                snap=c.snap,
                alert=c.alert if isinstance(c.alert, dict) else {},
                explosion_event=c.explosion_event,
                tier=str(c.tier or ""),
                score=float(c.confidence or 0),
            )
            if ok:
                preferred.append(c)
        if top_causal:
            candidates = top_causal
        elif preferred:
            candidates = preferred

    candidates = filter_candidates_pretrade(candidates, state, snapshots)
    from app.engines.worst_day_guard import filter_worst_day_candidates

    candidates = filter_worst_day_candidates(candidates, state, snapshots)
    if limits and settings.daily_18pct_strategy_enabled:
        filtered: list[EntryCandidate] = []
        for c in candidates:
            ok, reason = entries_allowed_by_limits(
                limits, c.mode, c.score, trades_today,
            )
            if ok:
                filtered.append(c)
        candidates = filtered
    if not candidates:
        return None

    settings = get_settings()
    if settings.best_trades_only_enabled and not skip_best_trades_only_filter(trading_mode):
        from app.engines.aligned_explosion_bypass import expiry_aligned_explosion_trade_allowed

        candidates = [
            c for c in candidates
            if c.score >= settings.best_trades_min_rank_score
            or expiry_aligned_explosion_trade_allowed(c, c.snap)[0]
        ]
        if not candidates:
            return None

    last_n = last_n_trades_summary(state)
    if (
        settings.best_trades_only_enabled
        and not skip_best_trades_only_filter(trading_mode)
        and last_n.get("losses", 0) >= settings.best_trades_explosion_only_after_losses
    ):
        explosion_only = [c for c in candidates if c.mode == "explosion"]
        if explosion_only:
            candidates = explosion_only

    def sort_key(c: EntryCandidate) -> float:
        bonus = 20 if c.mode == "explosion" else (
            15 if c.mode == "worst_day_itm_fade" else (
                10 if c.mode == "slow_bounce" else (
                    8 if c.mode == "quick_sideways" else (5 if c.mode == "swing" else 0)
                )
            )
        )
        if c.mode == "quick_sideways" and (c.pretrade_meta or {}).get("worstDayQuick"):
            bonus = max(bonus, 12)
        if worst_day_defensive_session_active(state, snapshots) and c.mode == "explosion":
            bonus -= 12
        if trading_mode == "AGGRESSIVE" and c.mode == "explosion":
            bonus += 14
        bonus += mode_rank_bonus(c.mode, adaptive)
        # Today's book: promote modes that paid, demote modes that bled.
        bonus += mode_session_rank_bonus(c.mode, mode_stats)
        # Missed-trade quality promote: bullish/bearish base-window ELITE jumps queue.
        from app.engines.explosion_confidence import missed_explosion_rank_bonus

        bonus += missed_explosion_rank_bonus(c, c.snap)
        breadth_bias = (c.snap.breadth.bias if c.snap.breadth else "NEUTRAL") or "NEUTRAL"
        if c.mode == "explosion":
            from app.engines.extreme_explosion_moment import is_extreme_explosion_all_in_bypass

            daily_move = 0.0
            if c.explosion_event is not None:
                daily_move = float(getattr(c.explosion_event, "daily_move_pct", 0) or 0)
                peak = float(getattr(c.explosion_event, "peak_move_pct", 0) or 0)
                if peak > daily_move:
                    daily_move = peak
            early_min = float(getattr(settings, "explosion_early_window_min_move_pct", 28.0) or 28.0)
            early_max = float(getattr(settings, "explosion_early_window_max_move_pct", 55.0) or 55.0)
            # Prefer first lift off local base (15–25%) over day-% chase windows.
            alert = c.alert if isinstance(getattr(c, "alert", None), dict) else {}
            pad = float(
                alert.get("ictBaseRelativeMovePct")
                or alert.get("localBaseMovePct")
                or 0
            )
            first_lift = bool(alert.get("ictFirstLift"))
            pad_lo = float(getattr(settings, "ict_structured_early_min_move_pct", 15.0) or 15.0)
            pad_sweet = float(
                getattr(settings, "explosion_first_lift_sweet_max_move_pct", 25.0) or 25.0
            )
            pad_hi = float(getattr(settings, "elite_local_base_max_move_pct", 40.0) or 40.0)
            if first_lift or (pad_lo <= pad <= pad_sweet):
                bonus += float(
                    getattr(settings, "explosion_first_lift_rank_bonus", 24.0) or 24.0
                )
            elif pad_lo <= pad <= pad_hi:
                bonus += 14
            elif pad > pad_hi:
                bonus -= min(40, (pad - pad_hi) * 0.9)
            # Prioritize winner-shaped ELITE/EXPLODING still sitting on the local-base
            # pad so they win rank-1 before the rip leaves the 5–25% catch window.
            try:
                quality = float(
                    alert.get("flatVerticalQuality")
                    or alert.get("ictFlatVerticalQuality")
                    or 0
                )
            except (TypeError, ValueError):
                quality = 0.0
            score_v = float(
                getattr(c, "confidence", 0)
                or alert.get("explosionScore")
                or 0
            )
            tier_u = str(
                getattr(c, "tier", "") or alert.get("tier") or ""
            ).upper()
            winner_pad_lo = float(
                getattr(settings, "winner_local_base_min_local_base_move_pct", 5.0)
                or 5.0
            )
            winner_pad_hi = float(
                getattr(settings, "winner_local_base_max_local_base_move_pct", 25.0)
                or 25.0
            )
            if (
                tier_u in {"ELITE", "EXPLODING"}
                and winner_pad_lo <= pad <= winner_pad_hi
                and score_v
                >= float(
                    getattr(settings, "winner_local_base_min_explosion_score", 75.0)
                    or 75.0
                )
                and quality
                >= float(
                    getattr(settings, "winner_local_base_min_quality", 70.0) or 70.0
                )
                and (
                    first_lift
                    or alert.get("ictArmedBaseLaunch")
                    or alert.get("ictEliteBaseReady")
                    or alert.get("ictArmedBaseSustainedLift")
                    or (
                        bool(getattr(settings, "winner_local_base_early_ftv_fresh_enabled", True))
                        and alert.get("ictFlatThenVertical")
                        and alert.get("ictBreakout")
                        and (
                            alert.get("ictVolumeAwakening")
                            or alert.get("volumeAwaken")
                            or alert.get("ictDisplacement")
                        )
                    )
                )
            ):
                bonus += float(
                    getattr(settings, "winner_local_base_rank_bonus", 28.0) or 28.0
                )
            # Reward early window only — do NOT boost already-extended % moves.
            if early_min <= daily_move <= early_max and pad <= pad_hi:
                bonus += 12
            elif daily_move > early_max and pad > pad_hi:
                bonus -= min(40, (daily_move - early_max) * 0.7)
            if is_extreme_explosion_all_in_bypass(candidate=c):
                bonus += 20
            elif side_aligned_with_breadth(c.side, breadth_bias):
                bonus += 18
            else:
                bonus -= 22
            from app.engines.ict_breakout_monitor import analyze_explosion_event_ict

            if c.explosion_event is not None:
                ict = analyze_explosion_event_ict(c.explosion_event, c.snap)
                if ict.flat_then_vertical and ict.active:
                    bonus += 18 if trading_mode == "AGGRESSIVE" else 12
                elif ict.active and daily_move <= early_max:
                    bonus += min(16, ict.score * 0.2)
                elif ict.mega_rip:
                    # Mega rip without early flat base is usually a chase — small bump only.
                    bonus += 6
        elif c.mode == "scalp":
            # Best-only: do not boost mediocre scalps over explosions (Jul27 pattern).
            if not getattr(settings, "scalp_best_only_enabled", True):
                bonus += 6
        # Nearest expiry index #1, same-week next #2 (Tue NIFTY ↔ Thu SENSEX).
        if getattr(settings, "expiry_day_prefer_same_day_enabled", True):
            from app.engines.bad_day_routing import expiry_proximity_ranks

            nearest, nxt = expiry_proximity_ranks(snapshots)
            sym_u = c.symbol.upper()
            if sym_u in nearest:
                bonus += float(
                    getattr(settings, "expiry_day_sort_priority_bonus", 30.0) or 30.0
                )
            elif sym_u in nxt:
                bonus += float(
                    getattr(settings, "expiry_day_same_week_next_sort_bonus", 15.0) or 15.0
                )
        penalty = entry_score_penalty(c.symbol)
        return c.score + bonus - penalty

    # Stable leg identity breaks exact score ties so the capital-first slot cannot
    # flip between otherwise identical snapshots because of collection order.
    ranked_candidates = rank_candidates_for_selection(candidates, sort_key)
    best = ranked_candidates[0]
    leader_ranking = (best.pretrade_meta or {}).get("causalRanking", {})
    best.pretrade_meta = {
        **(best.pretrade_meta or {}),
        "legacySelectionScore": round(sort_key(best), 3),
        "rankedOut": [
            {
                "key": (
                    f"{candidate.symbol.upper()}:{candidate.side.value}:"
                    f"{float(candidate.strike):g}"
                ),
                "symbol": candidate.symbol.upper(),
                "side": candidate.side.value,
                "strike": float(candidate.strike),
                "causalGrade": (
                    (candidate.pretrade_meta or {})
                    .get("causalRanking", {})
                    .get("grade")
                ),
                "causalRankScore": (
                    (candidate.pretrade_meta or {})
                    .get("causalRanking", {})
                    .get("rankScore")
                ),
                "legacySelectionScore": round(sort_key(candidate), 3),
                "finalRankPosition": position,
                "leaderKey": (
                    f"{best.symbol.upper()}:{best.side.value}:"
                    f"{float(best.strike):g}"
                ),
                "leaderCausalGrade": leader_ranking.get("grade"),
                "leaderCausalRankScore": leader_ranking.get("rankScore"),
                "leaderLegacySelectionScore": round(sort_key(best), 3),
            }
            for position, candidate in enumerate(ranked_candidates[1:], start=2)
        ],
    }
    floor = min_rank_for_entry(chop, snapshots)
    floor = max(floor, last_n_elevated_min_rank(state, snapshots))

    agg_floor = aggressive_min_rank_floor(trading_mode)
    if agg_floor > 0:
        floor = min(floor, agg_floor)
    if pf_fb and settings.edge_engine_enabled and pf_fb.rank_penalty > 0:
        floor += pf_fb.rank_penalty
    if limits and settings.daily_18pct_strategy_enabled:
        floor = max(floor, limits.minRankScore)
    from app.engines.morning_premium_capture import (
        in_all_day_explosion_window,
        in_premium_capture_window,
        premium_capture_rank_floor,
    )

    if in_premium_capture_window() and best.mode == "explosion":
        floor = min(floor, premium_capture_rank_floor())
    if best.mode == "quick_sideways":
        floor = min(floor, settings.quick_sideways_min_rank_score)
        if (best.pretrade_meta or {}).get("worstDayQuick"):
            floor = min(floor, settings.worst_day_quick_min_rank)
    elif best.mode == "worst_day_itm_fade":
        floor = min(floor, settings.worst_day_itm_fade_min_rank)
    elif best.mode == "slow_bounce":
        floor = min(floor, settings.quick_sideways_slow_bounce_min_rank_score)
    elif best.mode == "scalp" and getattr(settings, "scalp_best_only_enabled", True):
        floor = max(
            floor,
            float(getattr(settings, "scalp_best_min_rank_score", 84.0) or 84.0),
        )
    elif settings.best_trades_only_enabled:
        from app.engines.aligned_explosion_bypass import expiry_aligned_explosion_trade_allowed

        if not expiry_aligned_explosion_trade_allowed(best, best.snap)[0]:
            floor = max(floor, settings.best_trades_min_rank_score)
    floor = apply_rank_floor_adaptive(floor, adaptive, candidate_mode=best.mode)
    from app.engines.bad_day_routing import bad_day_min_rank_floor

    floor = max(floor, bad_day_min_rank_floor(state, snapshots))
    if best.mode == "explosion" and best.explosion_event is not None:
        open_move = float(getattr(best.explosion_event, "daily_move_pct", 0) or 0)
        if open_move >= settings.all_day_explosion_extreme_move_min_pct:
            floor = min(floor, settings.all_day_explosion_min_score)
        elif (
            open_move >= settings.all_day_explosion_session_move_min_pct
            and in_all_day_explosion_window()
        ):
            floor = min(floor, settings.all_day_explosion_min_score + 4)
    from app.engines.worst_day_guard import session_entry_policy

    policy, _ = session_entry_policy(state, snapshots)
    if policy == "BREAKOUT_ONLY" and trading_mode != "AGGRESSIVE":
        floor = max(floor, settings.worst_day_breakout_min_rank)
    from app.engines.chart_exit_levels import chart_trade_confidence

    chart_conf, _ = chart_trade_confidence(best.snap, best.side)
    if chart_conf >= settings.all_day_min_chart_confidence:
        floor = min(floor, settings.all_day_min_rank_score)
    if floor > 0 and sort_key(best) < floor:
        from app.engines.extreme_explosion_moment import (
            is_extreme_explosion_all_in_bypass,
            is_high_mover_elite_bypass,
        )

        if not (
            best.mode == "explosion"
            and (
                is_extreme_explosion_all_in_bypass(candidate=best)
                or is_high_mover_elite_bypass(candidate=best)
            )
        ):
            return None
    return best


def diagnose_missed_entries(
    snapshots: dict[str, SymbolSnapshot],
    state: AutoTraderState,
) -> list[dict[str, Any]]:
    """Surface near-miss signals when no entry is taken — helps debug zero-trade sessions."""
    from app.engines.explosion_detector import effective_explosion_min_score

    settings = get_settings()
    notes: list[dict[str, Any]] = []

    for symbol, snap in snapshots.items():
        if not snap.dataAvailable:
            continue

        elite_only = bool(getattr(settings, "explosion_elite_exploding_only", True))
        for alert in snap.explosionAlerts or []:
            if (
                alert.get("tier") not in ("ELITE", "EXPLODING", "BUILDING")
                and not alert.get("ictFirstLift")
            ):
                continue
            score = float(alert.get("explosionScore", 0))
            prem = alert.get("premium")
            daily_move = float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0)
            peak_move = float(alert.get("peakMovePct") or 0)
            tier_str = str(alert.get("tier") or "WATCH")
            min_score = effective_explosion_min_score(
                tier=tier_str,
                peak_move_pct=peak_move,
                daily_move_pct=daily_move,
            )
            blockers: list[str] = []
            first_lift_ready = False
            if bool(
                alert.get("ictFirstLift")
                or alert.get("ictVRipReady")
                or alert.get("ictBuildingRipReady")
                or alert.get("ictEliteBaseReady")
                or alert.get("ictArmedBaseLaunch")
                or (
                    str(alert.get("tier") or "").upper() == "BUILDING"
                    and (
                        alert.get("volumeAwaken")
                        or alert.get("ictVolumeAwakening")
                    )
                )
            ):
                from app.engines.ict_breakout_monitor import (
                    first_lift_entry_readiness,
                )

                first_lift_ready, readiness_reason = first_lift_entry_readiness(
                    snap=snap,
                    alert=alert,
                    state=state,
                )
                if not first_lift_ready:
                    blockers.append(readiness_reason)
            if elite_only and tier_str.upper() not in ("ELITE", "EXPLODING"):
                if not first_lift_ready and not _building_aligned_ict_alert_ok(
                    alert, snap, str(tier_str).upper(),
                    state=state, snapshots=snapshots,
                ):
                    blockers.append("tier_not_elite_exploding")
            if bool(getattr(settings, "explosion_require_chart_align_enabled", True)):
                from app.engines.spot_direction import side_aligned_with_chart

                side_raw = str(alert.get("side") or "").upper()
                if side_raw in ("CALL", "PUT") and snap.spotChart is not None:
                    if (
                        not side_aligned_with_chart(Side(side_raw), snap.spotChart)
                        and not first_lift_ready
                    ):
                        blockers.append("chart_not_aligned")
            if not premium_in_band(prem, mode="explosion", peak_move_pct=peak_move, snap=snap):
                blockers.append("premium_out_of_band")
            if score < min_score:
                blockers.append(f"explosion_score<{min_score:.0f}")
            if snap.tradeQualityScore < 25 and score < settings.aggressive_min_explosion_score + 10:
                blockers.append("symbol_tqs_low")
            if blockers:
                notes.append({
                    "symbol": symbol,
                    "reason": "explosion_near_miss",
                    "mode": "explosion",
                    "message": ", ".join(blockers),
                    "premium": prem,
                    "score": score,
                    "tier": alert.get("tier"),
                })

        for suggestion in snap.suggestedTrades or []:
            if suggestion.strategyType == StrategyType.EXPLOSIVE:
                continue
            trade_score = max(suggestion.tqs, suggestion.confidence or 0)
            vel = suggestion.runnerSignal.premiumVelocityPct if suggestion.runnerSignal else 0
            blockers = []
            if not premium_in_band(suggestion.lastPremium):
                blockers.append("premium_out_of_band")
            if trade_score < settings.aggressive_min_tqs:
                blockers.append(f"trade_score<{settings.aggressive_min_tqs}")
            if vel < settings.enhanced_velocity_threshold and trade_score < settings.aggressive_min_tqs + 5:
                blockers.append(f"velocity<{settings.enhanced_velocity_threshold}")
            if blockers:
                notes.append({
                    "symbol": symbol,
                    "reason": "scalp_near_miss",
                    "mode": "scalp",
                    "message": ", ".join(blockers),
                    "premium": suggestion.lastPremium,
                    "score": trade_score,
                    "side": suggestion.side.value,
                })

    return notes[:6]
