"""Hard block counter-breadth entries when stock breadth is directional."""

from __future__ import annotations

from app.config import get_settings
from app.models.schemas import Side


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def breadth_hard_blocks_side(side: Side | str, breadth_bias: str) -> tuple[bool, str]:
    """
    No PUT on BULLISH breadth, no CALL on BEARISH breadth.
    Applies regardless of explosion tier or premium-led bypass.
    """
    settings = get_settings()
    if not settings.breadth_hard_side_block_enabled:
        return False, "ok"
    bias = (breadth_bias or "NEUTRAL").upper()
    if bias == "NEUTRAL":
        return False, "ok"
    side_v = _side_val(side)
    if bias == "BULLISH" and side_v == "PUT":
        return True, "hard_block_put_vs_bullish_breadth"
    if bias == "BEARISH" and side_v == "CALL":
        return True, "hard_block_call_vs_bearish_breadth"
    return False, "ok"


def counter_breadth_side_blocked(side: Side | str, breadth_bias: str) -> bool:
    blocked, _ = breadth_hard_blocks_side(side, breadth_bias)
    return blocked
