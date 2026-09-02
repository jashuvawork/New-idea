"""Loss-triggered opposite side flip — after same-side losses + index structure turn.

PUT losses + rally off session low (RSI/MACD) → unlock/prefer CALL (one elite setup).
CALL losses + slide off session high (mirror) → unlock/prefer PUT.
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import AutoTraderState, Side, SymbolSnapshot
from app.engines.pretrade_validator import TradeRecord, collect_session_trades

_loss_flip_consumed: dict[str, str] = {}


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side or "").upper()


def reset_loss_triggered_side_flip() -> None:
    _loss_flip_consumed.clear()


def mark_loss_triggered_flip_used(symbol: str, side: Side | str) -> None:
    settings = get_settings()
    if not bool(getattr(settings, "loss_triggered_side_flip_one_shot", True)):
        return
    _loss_flip_consumed[symbol.upper()] = _side_val(side)


def consecutive_same_side_losses(
    trades: list[TradeRecord],
    symbol: str,
    side: Side | str,
) -> int:
    """Count trailing closed losses on the same symbol + side."""
    sym = symbol.upper()
    side_v = _side_val(side)
    count = 0
    for trade in reversed(trades):
        if trade.symbol.upper() != sym:
            continue
        if _side_val(trade.side) != side_v:
            break
        if float(trade.pnl_inr or 0) < 0:
            count += 1
        else:
            break
    return count


def _elite_candidate_ok(candidate: Any, settings: Any) -> bool:
    if candidate is None:
        return False
    tier = str(getattr(candidate, "tier", "") or "").upper()
    score = float(
        getattr(candidate, "confidence", 0)
        or getattr(candidate, "score", 0)
        or 0
    )
    min_score = float(
        getattr(settings, "loss_triggered_side_flip_min_elite_score", 90.0) or 90.0
    )
    tiers_raw = str(
        getattr(settings, "loss_triggered_side_flip_elite_tiers_csv", "ELITE,EXPLODING")
        or "ELITE,EXPLODING"
    )
    tiers = {t.strip().upper() for t in tiers_raw.split(",") if t.strip()}
    return tier in tiers and score >= min_score


def loss_triggered_opposite_flip_ready(
    symbol: str,
    target_side: Side | str,
    snap: SymbolSnapshot,
    state: Optional[AutoTraderState] = None,
    *,
    candidate: Any = None,
    trades: Optional[list[TradeRecord]] = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    True when same-side losses + index rally/slide + RSI/MACD support opposite elite entry.

    Reuses index_rally_side_flip structure checks (pts off session low/high).
    """
    settings = get_settings()
    if not bool(getattr(settings, "loss_triggered_side_flip_enabled", True)):
        return False, "disabled", {}

    sym = symbol.upper()
    target_v = _side_val(target_side)
    if target_v not in {"CALL", "PUT"}:
        return False, "invalid_side", {}

    if bool(getattr(settings, "loss_triggered_side_flip_one_shot", True)):
        if _loss_flip_consumed.get(sym) == target_v:
            return False, "loss_flip_already_used", {"symbol": sym, "side": target_v}

    lost_side = "PUT" if target_v == "CALL" else "CALL"
    min_losses = int(
        getattr(settings, "loss_triggered_side_flip_min_same_side_losses", 1) or 1
    )
    closed = trades if trades is not None else (
        collect_session_trades(state) if state is not None else []
    )
    loss_count = consecutive_same_side_losses(closed, sym, lost_side)
    meta: dict[str, Any] = {
        "symbol": sym,
        "targetSide": target_v,
        "lostSide": lost_side,
        "consecutiveLosses": loss_count,
        "minLosses": min_losses,
    }
    if loss_count < min_losses:
        return False, f"need_{min_losses}_same_side_losses_have_{loss_count}", meta

    from app.engines.index_rally_side_flip import index_rally_side_flip_bypass

    struct_ok, struct_reason, struct_meta = index_rally_side_flip_bypass(
        sym, target_v, snap, settings=settings,
    )
    meta.update(struct_meta or {})
    if not struct_ok:
        return False, struct_reason, meta

    if bool(getattr(settings, "loss_triggered_side_flip_elite_only", True)):
        if not _elite_candidate_ok(candidate, settings):
            return False, "loss_flip_elite_only", meta

    meta["mode"] = "loss_triggered_side_flip"
    return True, "loss_triggered_side_flip", meta


def loss_triggered_side_flip_rank_bonus(
    symbol: str,
    side: Side | str,
    snap: SymbolSnapshot,
    state: AutoTraderState,
    *,
    candidate: Any = None,
) -> float:
    settings = get_settings()
    if not bool(getattr(settings, "loss_triggered_side_flip_enabled", True)):
        return 0.0
    ok, _, _ = loss_triggered_opposite_flip_ready(
        symbol, side, snap, state, candidate=candidate,
    )
    if not ok:
        return 0.0
    return float(
        getattr(settings, "loss_triggered_side_flip_rank_bonus", 25.0) or 25.0
    )
