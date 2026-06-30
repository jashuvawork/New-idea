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
)
from app.engines.simple_profit import check_entry_gate
from app.engines.spot_direction import chart_rank_adjustment
from app.engines.symbol_cooldown import (
    entry_score_penalty,
    requires_breadth_alignment,
    side_aligned_with_breadth,
    symbol_in_cooldown,
)
from app.engines.swing_profit import check_swing_entry
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
        if not premium_in_band(alert.get("premium")):
            continue
        if alert.get("tier") not in ("ELITE", "EXPLODING"):
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
        )
        if not passed:
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
            chart=snap.spotChart,
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
) -> Optional[EntryCandidate]:
    """Return highest-ranked setup across all symbols — one best trade only."""
    settings = get_settings()
    from app.engines.chop_day_guards import (
        is_chop_session,
        min_rank_for_entry,
        symbol_rank_adjustment,
    )

    scalp_open = sum(1 for t in state.openPaperTrades if t.strategyType != StrategyType.SWING)
    swing_open = sum(1 for t in state.openPaperTrades if t.strategyType == StrategyType.SWING)
    chop = is_chop_session(snapshots)

    candidates: list[EntryCandidate] = []

    for symbol, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        if settings.explosion_capture_mode and scalp_open < settings.aggressive_max_open_scalps:
            candidates.extend(_explosion_candidates(symbol, snap, state, settings))
        if settings.paper_simple_profit_mode and scalp_open < settings.aggressive_max_open_scalps:
            candidates.extend(_scalp_candidates(symbol, snap, state, settings))
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

    candidates = filter_candidates_pretrade(candidates, state, snapshots)
    if not candidates:
        return None

    def sort_key(c: EntryCandidate) -> float:
        bonus = 20 if c.mode == "explosion" else (5 if c.mode == "swing" else 0)
        penalty = entry_score_penalty(c.symbol)
        return c.score + bonus - penalty

    best = max(candidates, key=sort_key)
    floor = min_rank_for_entry(chop, snapshots)
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
            if not premium_in_band(prem):
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
