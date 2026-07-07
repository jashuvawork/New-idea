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


def _reentry_blocked(
    symbol: str,
    side: Side,
    strike: float,
    snap: SymbolSnapshot,
) -> tuple[bool, str]:
    blocked, reason = symbol_in_cooldown(symbol)
    if blocked:
        return True, reason
    blocked, reason = instrument_in_cooldown(symbol, side, strike)
    if blocked:
        return True, reason
    from app.engines.directional_lock import check_directional_side_lock

    blocked, reason = check_directional_side_lock(symbol, side, snap)
    if blocked:
        return True, reason
    if instrument_daily_cap_reached(symbol, side, strike):
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
    out: list[EntryCandidate] = []
    for alert in snap.explosionAlerts or []:
        if not alert.get("tradeable"):
            continue
        if not premium_in_band(alert.get("premium"), mode="explosion"):
            continue
        if alert.get("tier") not in ("ELITE", "EXPLODING"):
            from app.engines.morning_premium_capture import is_premium_capture_alert

            if not is_premium_capture_alert(alert, snap.spotChart):
                continue
        score_val = float(alert.get("explosionScore", 0))
        if score_val < settings.aggressive_min_explosion_score:
            continue
        # Explosion score is primary quality — don't block on low symbol TQS alone
        if snap.tradeQualityScore < 25 and score_val < settings.aggressive_min_explosion_score + 10:
            continue

        from app.engines.explosion_detector import ExplosionEvent

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
        )
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
        )
        if not passed:
            continue

        from app.engines.rally_capture import cross_side_chase_blocked

        blocked_x, _ = cross_side_chase_blocked(event, snap)
        if blocked_x:
            continue

        blocked, reason = _reentry_blocked(symbol, event.side, event.strike, snap)
        if blocked:
            continue

        rank = score_val * 0.55 + snap.tradeQualityScore * 0.25
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
        ))
    return out


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

        blocked, reason = _reentry_blocked(symbol, suggestion.side, suggestion.strike, snap)
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
        ))

    for row in heatmap_moneyness_candidates(symbol, snap, snapshots={symbol: snap}):
        suggestion = row["suggestion"]
        blocked, reason = _reentry_blocked(symbol, suggestion.side, suggestion.strike, snap)
        if blocked:
            continue
        rank = float(row["score"]) + snap.tradeQualityScore * 0.2
        rank += moneyness_rank_adjustment(
            suggestion.side, suggestion.strike, snap, mode="scalp", candidate_score=rank,
            snapshots={symbol: snap},
        )
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
        ))
    return out


def _quick_sideways_candidates(
    symbol: str,
    snap: SymbolSnapshot,
    state: AutoTraderState,
    settings,
) -> list[EntryCandidate]:
    if not quick_sideways_enabled():
        return []
    out: list[EntryCandidate] = []
    for setup in scan_quick_sideways_setups(symbol, snap):
        side = setup["side"]
        strike = float(setup["strike"])
        premium = float(setup["premium"])
        blocked, reason = _reentry_blocked(symbol, side, strike, snap)
        if blocked:
            continue
        from app.engines.expiry_day_guards import expiry_pm_itm_quick_active

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
                "expiryPmItmQuick": expiry_pm_itm_quick_active(snap),
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
) -> Optional[EntryCandidate]:
    """Return highest-ranked setup across all symbols — one best trade only."""
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

    candidates: list[EntryCandidate] = []

    for symbol, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        if settings.explosion_capture_mode and scalp_open < settings.aggressive_max_open_scalps:
            if not limits or getattr(limits, "allowExplosion", True):
                candidates.extend(_explosion_candidates(symbol, snap, state, settings))
        if settings.paper_simple_profit_mode and scalp_open < settings.aggressive_max_open_scalps:
            candidates.extend(_scalp_candidates(symbol, snap, state, settings))
        if quick_sideways_enabled() and scalp_open < settings.aggressive_max_open_scalps:
            candidates.extend(_quick_sideways_candidates(symbol, snap, state, settings))
        if swing_open < settings.swing_max_open:
            candidates.extend(_swing_candidates(symbol, snap, state, settings))

    if not candidates:
        return None

    # SENSEX-first on chop days + session backtest index preference
    session_trades = collect_session_trades(state)
    index_adj = index_rank_from_backtest(compute_symbol_stats(session_trades))

    for c in candidates:
        c.score += symbol_rank_adjustment(c.symbol, chop)
        c.score += index_adj.get(c.symbol.upper(), 0.0)
        from app.engines.bad_day_routing import cross_index_rank_adjustment

        c.score += cross_index_rank_adjustment(c, state, snapshots)
        if settings.edge_engine_enabled:
            edge = compute_entry_edge(c, c.snap, state)
            c.score += edge_rank_bonus(edge)
            c.pretrade_meta = {**(c.pretrade_meta or {}), "edgeScore": edge.total}

    pf_fb = session_pf_feedback(state) if settings.edge_engine_enabled else None

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

    if should_pause_regular_scalps(
        adaptive, edge_pause_scalps=bool(pf_fb and pf_fb.pause_quick_scalps),
    ):
        candidates = [c for c in candidates if c.mode != "scalp"]

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
    if settings.best_trades_only_enabled:
        candidates = [
            c for c in candidates
            if c.score >= settings.best_trades_min_rank_score
        ]
        if not candidates:
            return None

    last_n = last_n_trades_summary(state)
    if (
        settings.best_trades_only_enabled
        and last_n.get("losses", 0) >= settings.best_trades_explosion_only_after_losses
    ):
        explosion_only = [c for c in candidates if c.mode == "explosion"]
        if explosion_only:
            candidates = explosion_only

    def sort_key(c: EntryCandidate) -> float:
        bonus = 20 if c.mode == "explosion" else (8 if c.mode == "quick_sideways" else (5 if c.mode == "swing" else 0))
        bonus += mode_rank_bonus(c.mode, adaptive)
        penalty = entry_score_penalty(c.symbol)
        return c.score + bonus - penalty

    best = max(candidates, key=sort_key)
    floor = min_rank_for_entry(chop, snapshots)
    floor = max(floor, last_n_elevated_min_rank(state))
    if pf_fb and settings.edge_engine_enabled and pf_fb.rank_penalty > 0:
        floor += pf_fb.rank_penalty
    if limits and settings.daily_18pct_strategy_enabled:
        floor = max(floor, limits.minRankScore)
    from app.engines.morning_premium_capture import (
        in_premium_capture_window,
        premium_capture_rank_floor,
    )

    if in_premium_capture_window() and best.mode == "explosion":
        floor = min(floor, premium_capture_rank_floor())
    if best.mode == "quick_sideways":
        floor = min(floor, settings.quick_sideways_min_rank_score)
    elif settings.best_trades_only_enabled:
        floor = max(floor, settings.best_trades_min_rank_score)
    floor = apply_rank_floor_adaptive(floor, adaptive, candidate_mode=best.mode)
    from app.engines.bad_day_routing import bad_day_min_rank_floor

    floor = max(floor, bad_day_min_rank_floor(state, snapshots))
    from app.engines.worst_day_guard import session_entry_policy

    policy, _ = session_entry_policy(state, snapshots)
    if policy == "BREAKOUT_ONLY":
        floor = max(floor, settings.worst_day_breakout_min_rank)
    if floor > 0 and sort_key(best) < floor:
        return None
    return best


def diagnose_missed_entries(
    snapshots: dict[str, SymbolSnapshot],
    state: AutoTraderState,
) -> list[dict[str, Any]]:
    """Surface near-miss signals when no entry is taken — helps debug zero-trade sessions."""
    settings = get_settings()
    notes: list[dict[str, Any]] = []

    for symbol, snap in snapshots.items():
        if not snap.dataAvailable:
            continue

        for alert in snap.explosionAlerts or []:
            if alert.get("tier") not in ("ELITE", "EXPLODING", "BUILDING"):
                continue
            score = float(alert.get("explosionScore", 0))
            prem = alert.get("premium")
            blockers: list[str] = []
            if not premium_in_band(prem, mode="explosion"):
                blockers.append("premium_out_of_band")
            if score < settings.aggressive_min_explosion_score:
                blockers.append(f"explosion_score<{settings.aggressive_min_explosion_score}")
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
