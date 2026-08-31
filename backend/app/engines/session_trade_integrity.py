"""Filter phantom / corrupted session trades from P&L, caps, and reports."""

from __future__ import annotations

from typing import Any, Iterable

from app.models.schemas import AutoTraderState, PaperTrade

_STRIKE_BOUNDS: dict[str, tuple[float, float]] = {
    "NIFTY": (15_000.0, 35_000.0),
    "BANKNIFTY": (30_000.0, 70_000.0),
    "SENSEX": (60_000.0, 90_000.0),
}


def _strike_sane(symbol: str, strike: float) -> bool:
    bounds = _STRIKE_BOUNDS.get(str(symbol or "").upper())
    if not bounds:
        return 10_000.0 <= strike <= 100_000.0
    lo, hi = bounds
    return lo <= strike <= hi


def is_phantom_session_trade(trade: Any) -> bool:
    """
    Corrupted rows that must not affect session P&L, trade caps, or stage locks.

    Typical causes: broker adoption parser bugs (strike 2690124050), zero entry
    premium, fake explosion_target_hit closes on adopted legs.
    """
    strike = float(getattr(trade, "strike", 0) or 0)
    symbol = str(getattr(trade, "symbol", "") or "").upper()
    entry = float(getattr(trade, "entryPremium", 0) or 0)
    ctx = getattr(trade, "entryContext", None) or {}
    exit_reason = str(getattr(trade, "exitReason", "") or "")

    if strike > 100_000.0:
        return True
    if symbol and strike > 0 and not _strike_sane(symbol, strike):
        return True
    if entry <= 0:
        return True
    if ctx.get("brokerAdopted") and entry <= 0:
        return True
    if (
        ctx.get("brokerAdopted")
        and exit_reason == "explosion_target_hit"
        and float(getattr(trade, "pnlInr", 0) or 0) > 0
        and entry <= 0
    ):
        return True
    return False


def real_session_closed_trades(
    state: AutoTraderState,
    *,
    trades: Iterable[PaperTrade] | None = None,
) -> list[PaperTrade]:
    source = list(trades) if trades is not None else list(state.closedPaperTrades)
    return [t for t in source if not is_phantom_session_trade(t)]


def real_session_closed_count(state: AutoTraderState) -> int:
    return len(real_session_closed_trades(state))


def purge_phantom_trades_from_state(state: AutoTraderState) -> int:
    """Remove phantom rows from in-memory session — returns purged count."""
    removed = 0
    kept_closed: list[PaperTrade] = []
    for trade in state.closedPaperTrades:
        if is_phantom_session_trade(trade):
            removed += 1
            continue
        kept_closed.append(trade)
    state.closedPaperTrades = kept_closed

    kept_open: list[PaperTrade] = []
    for trade in state.openPaperTrades:
        if is_phantom_session_trade(trade):
            removed += 1
            continue
        kept_open.append(trade)
    state.openPaperTrades = kept_open
    return removed


def is_phantom_trade_row(row: dict[str, Any]) -> bool:
    """Disk/archive row check — used when hydrating session from trade store."""
    try:
        side_raw = str(row.get("side", "CALL")).upper()
        from app.models.schemas import PaperTrade, Side, StrategyType

        trade = PaperTrade(
            id=str(row.get("id", "phantom-check")),
            symbol=str(row.get("symbol", "")),
            side=Side(side_raw),
            strike=float(row.get("strike") or 0),
            entryPremium=float(row.get("entryPremium") or 0),
            currentPremium=float(
                row.get("currentPremium")
                or row.get("exitPremium")
                or row.get("entryPremium")
                or 0
            ),
            lots=int(row.get("lots") or 1),
            pnlInr=float(row.get("pnlInr") or 0),
            status=str(row.get("status") or "CLOSED"),
            exitReason=str(row.get("exitReason") or ""),
            strategyType=StrategyType(str(row.get("strategyType") or "EXPLOSIVE")),
            entryContext=row.get("entryContext") if isinstance(row.get("entryContext"), dict) else {},
        )
        return is_phantom_session_trade(trade)
    except Exception:
        strike = float(row.get("strike") or 0)
        entry = float(row.get("entryPremium") or 0)
        if strike > 100_000.0 or entry <= 0:
            return True
        symbol = str(row.get("symbol", "") or "").upper()
        if symbol and strike > 0 and not _strike_sane(symbol, strike):
            return True
        return False
