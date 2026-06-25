"""Pick the single best paper entry when running aggressive max-lot mode."""

from dataclasses import dataclass
from typing import Any, Optional

from app.config import get_settings
from app.engines.explosion_profit import check_explosion_entry
from app.engines.simple_profit import check_entry_gate
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
        if alert.get("tier") not in ("ELITE", "EXPLODING"):
            continue
        score_val = float(alert.get("explosionScore", 0))
        if score_val < settings.aggressive_min_explosion_score:
            continue
        if snap.tradeQualityScore < settings.aggressive_min_tqs:
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
        passed, _ = check_explosion_entry(event, suggestion, snap.breadth, blocked)
        if not passed:
            continue

        rank = score_val * 0.55 + snap.tradeQualityScore * 0.25
        if event.tier == "ELITE":
            rank += 15
        rank += min(10, event.velocity_3s)

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
        if not suggestion.lastPremium or suggestion.lastPremium <= 0:
            continue
        if suggestion.tqs < settings.aggressive_min_tqs:
            continue
        if snap.tradeQualityScore < settings.aggressive_min_tqs:
            continue

        blocked = state.calibrationBlocks.get(suggestion.side.value, False)
        momentum = (snap.orderflow.volumeAcceleration or 0) > 65
        override = snap.explosiveRunner.candidate and (snap.explosiveRunner.score or 0) >= 82
        vel = suggestion.runnerSignal.premiumVelocityPct if suggestion.runnerSignal else 0

        passed, _ = check_entry_gate(
            suggestion, snap.breadth, snap.tradeQualityScore, vel,
            blocked, momentum_surge=momentum, alignment_override=override,
        )
        if not passed:
            continue

        rank = suggestion.tqs * 0.5 + suggestion.confidence * 0.3 + snap.tradeQualityScore * 0.2
        if snap.breadth.aligned:
            rank += 8
        if momentum:
            rank += 5

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
    scalp_open = sum(1 for t in state.openPaperTrades if t.strategyType != StrategyType.SWING)
    swing_open = sum(1 for t in state.openPaperTrades if t.strategyType == StrategyType.SWING)

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

    # Explosion beats scalp at similar scores; then highest score wins
    def sort_key(c: EntryCandidate) -> float:
        bonus = 20 if c.mode == "explosion" else (5 if c.mode == "swing" else 0)
        return c.score + bonus

    return max(candidates, key=sort_key)
