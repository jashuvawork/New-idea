"""Open-gap ITM CE/PE capture — prev-close ELITE rips must not die in chop/MTF/pre-expiry."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot


def _event_session_move(event: Any) -> float:
    if event is None:
        return 0.0
    daily = float(getattr(event, "daily_move_pct", 0) or 0)
    peak = float(getattr(event, "peak_move_pct", 0) or 0)
    if isinstance(event, dict):
        daily = float(event.get("dailyMovePct") or event.get("daily_move_pct") or daily or 0)
        peak = float(event.get("peakMovePct") or event.get("peak_move_pct") or peak or 0)
    return max(daily, peak)


def _event_tier(event: Any, candidate: Any = None) -> str:
    if event is not None:
        if isinstance(event, dict):
            tier = event.get("tier") or ""
        else:
            tier = getattr(event, "tier", "") or ""
        if tier:
            return str(tier).upper()
    if candidate is not None:
        return str(getattr(candidate, "tier", "") or "").upper()
    return ""


def _breadth_aligned(side: Side | str, snap: SymbolSnapshot) -> bool:
    side_val = side.value if isinstance(side, Side) else str(side).upper()
    bias = (getattr(snap.breadth, "bias", None) or "NEUTRAL")
    bias = bias.upper() if hasattr(bias, "upper") else str(bias).upper()
    aligned = bool(getattr(snap.breadth, "aligned", False))
    want = "BULLISH" if side_val == "CALL" else "BEARISH"
    return aligned or bias == want or bias == "NEUTRAL"


def is_open_gap_elite_rip(
    event: Any,
    *,
    candidate: Any = None,
    min_move_pct: Optional[float] = None,
) -> bool:
    """True for ELITE (or strong EXPLODING) open-gap session rips."""
    settings = get_settings()
    tier = _event_tier(event, candidate)
    move = _event_session_move(event)
    floor = float(
        min_move_pct
        if min_move_pct is not None
        else getattr(settings, "open_gap_elite_mtf_min_move_pct", 40.0) or 40.0
    )
    if tier == "ELITE" and move >= float(
        getattr(settings, "open_premium_min_move_pct", 25.0) or 25.0
    ):
        return True
    if tier in ("ELITE", "EXPLODING") and move >= floor:
        return True
    return False


def elite_open_gap_mtf_bypass(
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    explosion_event: Any = None,
    mode: str = "",
) -> bool:
    """
    Breadth-aligned ELITE/EXPLODING open-gap — skip stale 5m MTF oppose.

    Jul29: NIFTY 24100 CE scalp score 112 died on exec_mtf_5m_opposes_call while
    breadth/chart were bullish and ATM CE was ripping.
    """
    settings = get_settings()
    if not bool(getattr(settings, "open_gap_elite_mtf_bypass_enabled", True)):
        return False
    mode_l = (mode or "").lower()
    if mode_l and mode_l not in ("explosion", "scalp", ""):
        # Still allow explosion + high-conviction scalp on the rip.
        if mode_l not in ("quick_sideways",):
            pass
    if explosion_event is None and mode_l == "scalp":
        # Scalp near an open-gap needs the event; without it only breadth is weak signal.
        return False
    if not is_open_gap_elite_rip(explosion_event):
        return False
    return _breadth_aligned(side, snap)


def open_gap_chop_bypass(candidate: Any, snap: SymbolSnapshot) -> bool:
    """ELITE (and strong EXPLODING open-gaps) must not die as chop_immature pre-10."""
    settings = get_settings()
    if not bool(getattr(settings, "open_gap_chop_elite_bypass_enabled", True)):
        return False
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False
    event = getattr(candidate, "explosion_event", None)
    tier = _event_tier(event, candidate)
    if tier == "ELITE":
        return True
    try:
        from app.engines.elite_never_block import elite_never_block_active

        if elite_never_block_active(candidate=candidate):
            return True
    except Exception:
        pass
    return is_open_gap_elite_rip(
        event,
        candidate=candidate,
        min_move_pct=float(
            getattr(settings, "all_day_explosion_session_move_min_pct", 40.0) or 40.0
        ),
    )


def open_gap_near_expiry_symbol_allow(
    candidate: Any,
    snap: SymbolSnapshot,
) -> bool:
    """Allow breadth-aligned ELITE/EXPLODING on near-expiry symbol (don't force alternate)."""
    settings = get_settings()
    if not bool(getattr(settings, "open_gap_near_expiry_symbol_allow_enabled", True)):
        return False
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False
    from app.engines.expiry_day_guards import is_near_expiry_day

    if not is_near_expiry_day(snap):
        return False
    event = getattr(candidate, "explosion_event", None)
    if not is_open_gap_elite_rip(event, candidate=candidate):
        # Still allow aligned ELITE/EXPLODING on near-expiry at the configured floor.
        tier = _event_tier(event, candidate)
        score = float(getattr(candidate, "score", 0) or 0)
        min_rank = float(
            getattr(settings, "pre_expiry_expiry_symbol_explosion_min_rank", 45.0) or 45.0
        )
        if tier not in ("ELITE", "EXPLODING") or score < min_rank:
            return False
    side = getattr(candidate, "side", None) or getattr(event, "side", None)
    if side is None:
        return False
    return _breadth_aligned(side, snap)
