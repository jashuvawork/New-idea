"""Live chop guards — hard blocks and early exits on worst/chop days.

Session lift and elite must-take bypasses must not reopen immature local-base
chases or stacked same-side legs when live trading on chop/worst sessions.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.capital_allocator import lot_multiplier
from app.models.schemas import AutoTraderState, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")
logger = logging.getLogger(__name__)

# Prevent re-adopting the same broker leg after a phantom close in one session.
_adopted_instrument_keys_session: set[str] = set()

_OPTION_SYMBOL_RE = re.compile(
    r"^(?P<symbol>NIFTY|SENSEX|BANKNIFTY)\s*(?P<strike>\d+(?:\.\d+)?)\s*(?P<side>CE|PE)$",
    re.IGNORECASE,
)
# Upstox compact: NIFTY2690124050PE → NIFTY + 5-digit expiry token + 5-digit strike.
_OPTION_UPSTOX_COMPACT_RE = re.compile(
    r"^(?P<symbol>NIFTY|SENSEX|BANKNIFTY)(?P<expiry>\d{5})(?P<strike>\d{5})(?P<side>CE|PE)$",
    re.IGNORECASE,
)
# Legacy compact without expiry token (heatmap-style keys only).
_OPTION_COMPACT_RE = re.compile(
    r"^(?P<symbol>NIFTY|SENSEX|BANKNIFTY)(?P<strike>\d{4,5})(?P<side>CE|PE)$",
    re.IGNORECASE,
)

_STRIKE_BOUNDS: dict[str, tuple[float, float]] = {
    "NIFTY": (15_000.0, 35_000.0),
    "BANKNIFTY": (30_000.0, 70_000.0),
    "SENSEX": (60_000.0, 90_000.0),
}


def reset_chop_live_adoption_cache() -> None:
    """Clear adoption dedupe — call on session reset."""
    global _adopted_instrument_keys_session
    _adopted_instrument_keys_session = set()


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def _strike_sane(symbol: str, strike: float) -> bool:
    bounds = _STRIKE_BOUNDS.get(str(symbol or "").upper())
    if not bounds:
        return 10_000.0 <= strike <= 100_000.0
    lo, hi = bounds
    return lo <= strike <= hi


def parse_broker_option_symbol(trading_symbol: str) -> tuple[str, float, Side] | None:
    """Parse Upstox symbols like ``NIFTY 24050 PE`` or ``NIFTY2690124050PE``."""
    raw = str(trading_symbol or "").strip().upper().replace("_", " ")
    compact = raw.replace(" ", "")
    if not compact:
        return None

    # Upstox compact first — spaced regex would mis-parse expiry+strike blob as strike.
    match = _OPTION_UPSTOX_COMPACT_RE.match(compact)
    if match:
        symbol = match.group("symbol").upper()
        strike = float(match.group("strike"))
        side = Side.CALL if match.group("side").upper() == "CE" else Side.PUT
        if _strike_sane(symbol, strike):
            return symbol, strike, side
        return None

    match = _OPTION_SYMBOL_RE.match(raw)
    if match:
        symbol = match.group("symbol").upper()
        strike = float(match.group("strike"))
        side = Side.CALL if match.group("side").upper() == "CE" else Side.PUT
        if _strike_sane(symbol, strike):
            return symbol, strike, side
        return None

    match = _OPTION_COMPACT_RE.match(compact)
    if match:
        symbol = match.group("symbol").upper()
        strike = float(match.group("strike"))
        side = Side.CALL if match.group("side").upper() == "CE" else Side.PUT
        if _strike_sane(symbol, strike):
            return symbol, strike, side
    return None


def chop_live_guard_day_active(
    state: AutoTraderState,
    snap: SymbolSnapshot,
    snapshots: dict[str, SymbolSnapshot] | None = None,
) -> bool:
    """True when live chop guards should apply (worst day or chop session)."""
    settings = get_settings()
    if not getattr(settings, "chop_live_guards_enabled", True):
        return False

    ds = getattr(state, "dailyStrategy", None) or {}
    day_mode = str(ds.get("dayMode") or "").upper()
    if "WORST" in day_mode or "EXPIRY WORST" in day_mode:
        return True

    if snapshots:
        from app.engines.worst_day_guard import identify_worst_day

        verdict = identify_worst_day(state, snapshots)
        if verdict.is_worst:
            return True

    from app.engines.explosion_entry_guards import _regime_chopish

    if _regime_chopish(snap):
        return True

    if snapshots:
        from app.engines.chop_day_guards import is_chop_session

        if is_chop_session(snapshots):
            return True

    return False


def chop_live_session_lift_allowed(
    state: AutoTraderState,
    snap: SymbolSnapshot,
    snapshots: dict[str, SymbolSnapshot] | None = None,
) -> bool:
    """Session lift must not bypass live worst/chop blocks when disabled."""
    settings = get_settings()
    if not getattr(settings, "chop_live_disable_session_lift", True):
        return True
    if not settings.enable_live_trading:
        return True
    if not chop_live_guard_day_active(state, snap, snapshots):
        return True
    return False


def _known_broker_instrument_keys(state: AutoTraderState) -> set[str]:
    keys: set[str] = set(_adopted_instrument_keys_session)
    for trade in list(state.openPaperTrades) + list(state.closedPaperTrades):
        ctx = getattr(trade, "entryContext", None) or {}
        raw = str(ctx.get("instrumentKey") or "").replace(":", "|")
        if raw:
            keys.add(raw)
    return keys


def _immature_local_base_hard_block(
    candidate: Any,
    snap: SymbolSnapshot,
) -> tuple[bool, str]:
    """Immature local-base check without elite / must-take bypass."""
    event = getattr(candidate, "explosion_event", None)
    if event is None:
        return False, ""

    from app.engines.explosion_entry_guards import immature_explosion_blocked
    from app.engines.ict_breakout_monitor import analyze_explosion_event_ict

    alert = getattr(candidate, "alert", None)
    if not isinstance(alert, dict):
        alert = None
    ict = analyze_explosion_event_ict(event, snap)
    from app.engines.bullish_local_base import bullish_local_base_prediction

    bullish = bullish_local_base_prediction(snap, event, ict, alert=alert)
    blocked, reason = immature_explosion_blocked(
        event,
        ict=ict,
        alert=alert,
        bullish_local_base=bool(bullish.get("active")),
        skip_elite_bypass=True,
    )
    if blocked:
        return True, f"chop_live_{reason}"
    return False, ""


def _faded_rip_hard_block(candidate: Any, snap: SymbolSnapshot) -> tuple[bool, str]:
    settings = get_settings()
    if not getattr(settings, "chop_live_block_faded_rip", True):
        return False, ""
    event = getattr(candidate, "explosion_event", None)
    if event is None:
        return False, ""
    from app.engines.explosion_entry_guards import detect_faded_vertical_rip

    faded, _ = detect_faded_vertical_rip(event, snap)
    if faded:
        return True, "chop_live_faded_vertical_rip"
    return False, ""


def _extended_chase_hard_block(candidate: Any, snap: SymbolSnapshot) -> tuple[bool, str]:
    """Block late session chase without a mature trusted local-base pad."""
    settings = get_settings()
    if not getattr(settings, "chop_live_block_extended_chase", True):
        return False, ""
    event = getattr(candidate, "explosion_event", None)
    if event is None:
        return False, ""

    from app.engines.explosion_entry_guards import (
        effective_local_base_move_pct,
        trustworthy_local_base_move,
    )
    from app.engines.ict_breakout_monitor import analyze_explosion_event_ict

    ict = analyze_explosion_event_ict(event, snap)
    pad = max(
        effective_local_base_move_pct(event, ict),
        trustworthy_local_base_move(ict),
    )
    min_pad = float(
        getattr(settings, "chop_live_min_trusted_local_base_pct", 15.0) or 15.0
    )
    min_session = float(
        getattr(settings, "chop_live_extended_chase_min_session_move_pct", 28.0) or 28.0
    )
    daily = float(getattr(event, "daily_move_pct", 0) or 0)
    peak = float(getattr(event, "peak_move_pct", 0) or 0)
    session = max(daily, peak, float(getattr(ict, "session_move_pct", 0) or 0))

    if session >= min_session and pad < min_pad:
        return True, f"chop_live_extended_chase_pad_{pad:.1f}%"
    return False, ""


def _premium_5m_fading(
    *,
    side: Side | str,
    chart_meta: dict[str, Any] | None,
) -> tuple[bool, str, dict[str, Any]]:
    settings = get_settings()
    meta: dict[str, Any] = {}
    if not getattr(settings, "chop_live_block_premium_5m_fade", True):
        return False, "", meta

    premium_chart = (chart_meta or {}).get("premiumChart")
    mom5 = 0.0
    direction = "NEUTRAL"
    if premium_chart is None:
        premium_mtf = (chart_meta or {}).get("premiumMtf") or {}
        pt = premium_mtf.get("5m") if isinstance(premium_mtf, dict) else None
        if pt is None:
            return False, "", meta
        mom5 = float(getattr(pt, "momentumPct", 0) or 0)
        direction = str(getattr(pt, "direction", "") or "").upper()
    elif isinstance(premium_chart, dict):
        mom5 = float(premium_chart.get("momentum5Pct") or 0)
        direction = str(premium_chart.get("direction") or "").upper()
    else:
        mom5 = float(getattr(premium_chart, "momentum5Pct", 0) or 0)
        direction = str(getattr(premium_chart, "direction", "") or "").upper()

    meta["premiumMom5Pct"] = round(mom5, 3)
    meta["premiumDirection5m"] = direction

    min_mom = float(
        getattr(settings, "chop_live_premium_5m_fade_min_mom_pct", -0.12) or -0.12
    )
    side_v = _side_val(side)
    if side_v == "PUT" and direction == "BEARISH" and mom5 < min_mom:
        return True, "chop_live_premium_5m_fade", meta
    if side_v == "CALL" and direction == "BEARISH" and mom5 < min_mom:
        return True, "chop_live_premium_5m_fade", meta
    if mom5 < min_mom and direction == "BEARISH":
        return True, "chop_live_premium_5m_fade", meta
    return False, "", meta


def chop_live_entry_blocked(
    candidate: Any,
    snap: SymbolSnapshot,
    state: AutoTraderState,
    *,
    snapshots: dict[str, SymbolSnapshot] | None = None,
    chart_meta: dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Hard live-order gate on chop/worst days — no session-lift / elite bypass.

    Blocks immature local-base launches, faded rips, extended chase, and 5m fades.
    """
    settings = get_settings()
    meta: dict[str, Any] = {"chopLiveGuard": True}
    if not getattr(settings, "chop_live_guards_enabled", True):
        return False, "ok", meta
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False, "ok", meta
    if not chop_live_guard_day_active(state, snap, snapshots):
        return False, "ok", meta

    if getattr(settings, "chop_live_hard_block_worst_day", True) and snapshots:
        from app.engines.worst_day_guard import identify_worst_day

        verdict = identify_worst_day(state, snapshots)
        if verdict.is_worst and settings.enable_live_trading:
            meta["worstDayHardBlock"] = True
            meta["worstDayReasons"] = verdict.reasons
            return True, "chop_live_worst_day_hard_block", meta

    if getattr(settings, "chop_live_block_immature_local_base", True):
        blocked, reason = _immature_local_base_hard_block(candidate, snap)
        if blocked:
            meta["immatureLocalBase"] = True
            return True, reason, meta

    blocked, reason = _faded_rip_hard_block(candidate, snap)
    if blocked:
        meta["fadedVerticalRip"] = True
        return True, reason, meta

    blocked, reason = _extended_chase_hard_block(candidate, snap)
    if blocked:
        meta["extendedChase"] = True
        return True, reason, meta

    fade_blocked, fade_reason, fade_meta = _premium_5m_fading(
        side=getattr(candidate, "side", Side.CALL),
        chart_meta=chart_meta,
    )
    meta.update(fade_meta)
    if fade_blocked:
        meta["premium5mFade"] = True
        return True, fade_reason, meta

    return False, "ok", meta


def chop_second_same_side_leg_blocked(
    candidate: Any,
    state: AutoTraderState,
    snap: SymbolSnapshot,
    *,
    snapshots: dict[str, SymbolSnapshot] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Block stacking a second explosion leg on the same side during chop/worst days."""
    settings = get_settings()
    meta: dict[str, Any] = {}
    if not getattr(settings, "chop_live_second_leg_block_enabled", True):
        return False, "ok", meta
    if str(getattr(candidate, "mode", "") or "") != "explosion":
        return False, "ok", meta
    if not chop_live_guard_day_active(state, snap, snapshots):
        return False, "ok", meta

    side_v = _side_val(getattr(candidate, "side", Side.CALL))
    symbol = str(getattr(candidate, "symbol", "") or snap.symbol or "").upper()
    cooldown = int(
        getattr(settings, "chop_live_second_leg_cooldown_seconds", 900) or 900
    )
    now = datetime.now(IST)

    for trade in state.openPaperTrades:
        if trade.status != "OPEN":
            continue
        if str(trade.symbol or "").upper() != symbol:
            continue
        if _side_val(trade.side) != side_v:
            continue
        meta["existingOpenLegId"] = trade.id
        meta["existingStrike"] = float(trade.strike or 0)
        return True, "chop_live_second_same_side_open", meta

    from app.engines.pretrade_validator import collect_session_trades

    for trade in reversed(collect_session_trades(state)):
        if str(trade.symbol or "").upper() != symbol:
            continue
        if _side_val(trade.side) != side_v:
            continue
        opened = getattr(trade, "openedAt", None)
        if opened is None:
            continue
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=IST)
        age = (now - opened.astimezone(IST)).total_seconds()
        if age <= cooldown:
            meta["recentLegAgeSeconds"] = round(age, 1)
            meta["recentLegId"] = trade.id
            return True, "chop_live_second_same_side_recent", meta
        break

    return False, "ok", meta


def chop_live_early_fail_exit_reason(
    trade: Any,
    *,
    hold_seconds: float,
    best_points: float,
    pnl_points: float,
    live_velocity_3s: float,
) -> Optional[str]:
    """
    Scratch chop-day live runners that never establish green — even when
    LIVE_HOLD_TO_STRUCTURAL_SL would otherwise defer early exits.
    """
    settings = get_settings()
    if not getattr(settings, "chop_live_early_fail_exit_enabled", True):
        return None
    ctx = getattr(trade, "entryContext", None) or {}
    if not ctx.get("chopLiveGuard"):
        return None

    min_hold = int(getattr(settings, "chop_live_early_fail_min_hold_seconds", 30) or 30)
    max_hold = int(getattr(settings, "chop_live_early_fail_max_hold_seconds", 180) or 180)
    max_best = float(getattr(settings, "chop_live_early_fail_max_best_points", 0.5) or 0.5)
    min_loss = float(getattr(settings, "chop_live_early_fail_min_loss_points", 3.0) or 3.0)
    max_v3 = float(getattr(settings, "chop_live_early_fail_max_velocity_3s", 0.0) or 0.0)

    if not (min_hold <= hold_seconds <= max_hold):
        return None
    if best_points > max_best:
        return None
    if pnl_points > -min_loss:
        return None
    if live_velocity_3s >= max_v3:
        return None
    return "chop_live_early_fail"


def broker_adopted_trade_exit_blocked(trade: Any) -> bool:
    """Bad adoption rows must not generate fake target-hit P&L."""
    from app.engines.session_trade_integrity import is_phantom_session_trade

    return is_phantom_session_trade(trade)


async def adopt_untracked_broker_legs(
    state: AutoTraderState,
    client: Any,
    snapshots: dict[str, SymbolSnapshot],
) -> list[dict[str, Any]]:
    """Adopt broker-only live legs into openPaperTrades for exit management."""
    settings = get_settings()
    adopted: list[dict[str, Any]] = []
    if not getattr(settings, "live_broker_reconciliation_enabled", True):
        return adopted
    if not settings.enable_live_trading:
        return adopted
    if client is None:
        return adopted

    try:
        positions_raw = await client.get_positions()
    except Exception:
        return adopted

    tracked_keys = _known_broker_instrument_keys(state)

    for row in positions_raw or []:
        if not isinstance(row, dict):
            continue
        qty = int(float(row.get("quantity") or 0))
        if qty <= 0:
            continue
        instrument_key = str(
            row.get("instrument_token") or row.get("instrument_key") or ""
        ).replace(":", "|")
        if not instrument_key or instrument_key in tracked_keys:
            continue

        trading_symbol = str(row.get("trading_symbol") or row.get("tradingsymbol") or "")
        parsed = parse_broker_option_symbol(trading_symbol)
        if parsed is None:
            logger.warning(
                "Skip broker adoption — unparseable symbol %s (%s)",
                trading_symbol,
                instrument_key,
            )
            continue
        symbol, strike, side = parsed
        avg = float(row.get("average_price") or row.get("averagePrice") or 0)
        if avg <= 0:
            logger.warning(
                "Skip broker adoption — zero average price for %s (%s)",
                trading_symbol,
                instrument_key,
            )
            continue

        snap = snapshots.get(symbol)
        lot_size = lot_multiplier(symbol)
        lots = max(1, qty // lot_size) if lot_size > 0 else 1
        ltp = float(row.get("last_price") or row.get("ltp") or avg or 0)
        chop_flag = snap is not None and chop_live_guard_day_active(state, snap, snapshots)

        from app.models.schemas import PaperTrade, StrategyType

        trade = PaperTrade(
            id=str(uuid.uuid4())[:8],
            symbol=symbol,
            side=side,
            strike=strike,
            entryPremium=round(avg, 2),
            currentPremium=round(ltp, 2),
            lots=lots,
            openedAt=datetime.now(IST),
            strategyType=StrategyType.EXPLOSIVE,
            sessionDate=datetime.now(IST).strftime("%Y-%m-%d"),
            entryContext={
                "instrumentKey": instrument_key,
                "executionMode": "LIVE",
                "brokerAdopted": True,
                "brokerQuantity": qty,
                "lotSize": lot_size,
                "chopLiveGuard": chop_flag,
                "tradingSymbol": trading_symbol,
            },
        )
        state.openPaperTrades.append(trade)
        tracked_keys.add(instrument_key)
        _adopted_instrument_keys_session.add(instrument_key)
        adopted.append(
            {
                "id": trade.id,
                "symbol": symbol,
                "side": side.value,
                "strike": strike,
                "lots": lots,
                "instrumentKey": instrument_key,
            }
        )

    if adopted:
        from app.services import trade_store

        for trade in state.openPaperTrades[-len(adopted):]:
            await asyncio.to_thread(
                trade_store.record_trade_opened,
                trade,
                trade.entryContext or {},
            )

    return adopted
