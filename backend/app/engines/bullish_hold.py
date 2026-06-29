"""Hold winners longer when trade direction matches session breadth."""

from app.config import get_settings
from app.models.schemas import PaperTrade, Side


def direction_aligned_with_breadth(trade: PaperTrade) -> bool:
    """CALL+BULLISH or PUT+BEARISH — extend holds toward TP."""
    settings = get_settings()
    if not settings.bullish_hold_enabled:
        return False
    ctx = trade.entryContext or {}
    bias = str(ctx.get("breadth", "NEUTRAL")).upper()
    if trade.side == Side.CALL and bias == "BULLISH":
        return True
    if trade.side == Side.PUT and bias == "BEARISH":
        return True
    return False
