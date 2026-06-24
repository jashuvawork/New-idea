"""Dual strategy — scalp + explosive lanes (dormant by default)."""

from app.config import get_settings
from app.models.schemas import Side, StrategyType, SuggestedTrade


def filter_dual_candidates(
    suggestions: list[SuggestedTrade],
) -> tuple[list[SuggestedTrade], list[SuggestedTrade]]:
    """Split into scalp lane and explosive sniper lane."""
    settings = get_settings()
    if not settings.paper_dual_strategy_enabled:
        return suggestions, []

    scalp: list[SuggestedTrade] = []
    explosive: list[SuggestedTrade] = []

    for s in suggestions:
        if s.runnerSignal and s.runnerSignal.score >= 92 and s.runnerSignal.premiumVelocityPct >= 3.0:
            s.strategyType = StrategyType.EXPLOSIVE
            explosive.append(s)
        else:
            s.strategyType = StrategyType.DUAL_SCALP
            scalp.append(s)

    return scalp, explosive


def dual_entry_gate(trade: SuggestedTrade, tqs: float, vah: float, val: float, spot: float) -> bool:
    """Dual strategy entry: TQS + VAH/VAL + breadth."""
    if tqs < 72:
        return False
    if trade.side == Side.CALL and spot < val:
        return False
    if trade.side == Side.PUT and spot > vah:
        return False
    return True
