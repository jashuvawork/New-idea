"""Whipsaw / churn guards — stop CE↔PE flip-flops in bearish sideways chop."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.chop_day_guards import is_chop_session
from app.engines.pretrade_validator import TradeRecord, collect_session_trades
from app.models.schemas import AutoTraderState, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")

_last_close_by_symbol: dict[str, dict[str, Any]] = {}
_whipsaw_pause_until: Optional[datetime] = None
_whipsaw_dual_cooldown_until: Optional[datetime] = None
_session_date: Optional[str] = None


def _roll_session() -> None:
    global _session_date, _last_close_by_symbol, _whipsaw_pause_until, _whipsaw_dual_cooldown_until
    today = datetime.now(IST).strftime("%Y-%m-%d")
    if _session_date != today:
        _session_date = today
        _last_close_by_symbol.clear()
        _whipsaw_pause_until = None
        _whipsaw_dual_cooldown_until = None


def reset_whipsaw_guards() -> None:
    global _session_date, _last_close_by_symbol, _whipsaw_pause_until, _whipsaw_dual_cooldown_until
    _last_close_by_symbol.clear()
    _whipsaw_pause_until = None
    _whipsaw_dual_cooldown_until = None
    _session_date = None


def momentum_rally_bypass_whipsaw(snapshots: Optional[dict[str, SymbolSnapshot]]) -> bool:
    """Allow entries during 11:00–13:45 rally when premium velocity is expanding."""
    if not snapshots:
        return False
    settings = get_settings()
    if not settings.whipsaw_momentum_rally_bypass_enabled:
        return False
    from app.engines.chop_day_guards import in_momentum_rally_window, is_momentum_surge

    if not in_momentum_rally_window():
        return False
    for snap in snapshots.values():
        if not snap.dataAvailable:
            continue
        vel = 0.0
        vol = 1.0
        score = 0.0
        runner = snap.explosiveRunner
        if runner and runner.signal:
            vel = float(runner.signal.premiumVelocityPct or 0)
            score = float(runner.score or 0)
            vol = float(runner.signal.volumeSurge or 1.0)
        top = snap.topExplosion or {}
        if top:
            vel = max(vel, float(top.get("velocity3s") or 0))
            score = max(score, float(top.get("score") or 0))
        if is_momentum_surge(vel, vol, score):
            return True
    return False


def _clear_expired_pause() -> None:
    """Drop expired timer and start dual-leg retrigger cooldown."""
    global _whipsaw_pause_until, _whipsaw_dual_cooldown_until
    if _whipsaw_pause_until is None:
        return
    now = datetime.now(IST)
    until = _whipsaw_pause_until if _whipsaw_pause_until.tzinfo else _whipsaw_pause_until.replace(tzinfo=IST)
    if now >= until.astimezone(IST):
        settings = get_settings()
        _whipsaw_pause_until = None
        cooldown = max(0, settings.whipsaw_dual_retrigger_cooldown_seconds)
        if cooldown > 0:
            _whipsaw_dual_cooldown_until = now + timedelta(seconds=cooldown)


def _dual_retrigger_blocked() -> bool:
    if _whipsaw_dual_cooldown_until is None:
        return False
    now = datetime.now(IST)
    until = (
        _whipsaw_dual_cooldown_until
        if _whipsaw_dual_cooldown_until.tzinfo
        else _whipsaw_dual_cooldown_until.replace(tzinfo=IST)
    )
    return now < until.astimezone(IST)


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def _regime_label(snap: SymbolSnapshot) -> str:
    reg = snap.regime
    return str(reg.value if hasattr(reg, "value") else reg).upper()


def is_bearish_sideways(snap: SymbolSnapshot) -> bool:
    """RANGE_BOUND/CHOP regime with bearish or neutral breadth — whipsaw-prone."""
    regime = _regime_label(snap)
    bias = (snap.breadth.bias or "NEUTRAL").upper()
    return regime in ("RANGE_BOUND", "CHOP") and bias in ("BEARISH", "NEUTRAL")


def is_bearish_sideways_session(snapshots: dict[str, SymbolSnapshot]) -> bool:
    live = [s for s in snapshots.values() if s.dataAvailable]
    if not live:
        return False
    sideways = sum(1 for s in live if _regime_label(s) in ("RANGE_BOUND", "CHOP"))
    bearish_neutral = sum(
        1 for s in live
        if (s.breadth.bias or "NEUTRAL").upper() in ("BEARISH", "NEUTRAL")
    )
    n = len(live)
    return sideways >= max(1, (2 * n) // 3) and bearish_neutral >= max(1, n // 2)


def detect_ce_pe_whipsaw(snap: SymbolSnapshot) -> tuple[bool, dict[str, Any]]:
    """
    Both CE and PE premiums expanding fast on the same index — classic chop trap.
    PUT bleeds on bounce while CALL rips on the same tick window.
    """
    settings = get_settings()
    if not settings.whipsaw_guards_enabled:
        return False, {}

    watchlist = snap.explosiveRunnerWatchlist or []
    best_call_vel = 0.0
    best_put_vel = 0.0
    for entry in watchlist:
        side = str(entry.get("side", "")).upper()
        vel = float(entry.get("premiumVelocityPct", 0) or 0)
        if side == "CALL":
            best_call_vel = max(best_call_vel, vel)
        elif side == "PUT":
            best_put_vel = max(best_put_vel, vel)

    threshold = settings.ce_pe_whipsaw_velocity_threshold
    if not is_bearish_sideways(snap):
        return False, {"callVel": best_call_vel, "putVel": best_put_vel}

    if best_call_vel >= threshold and best_put_vel >= threshold:
        return True, {
            "callVel": round(best_call_vel, 2),
            "putVel": round(best_put_vel, 2),
            "symbol": snap.symbol,
            "regime": _regime_label(snap),
            "breadth": (snap.breadth.bias or "NEUTRAL").upper(),
        }
    return False, {"callVel": best_call_vel, "putVel": best_put_vel}


def record_trade_close(
    symbol: str,
    side: Side | str,
    pnl_inr: float,
    exit_reason: str = "",
) -> None:
    """Track last close per symbol for opposite-side cooldown."""
    settings = get_settings()
    if not settings.whipsaw_guards_enabled:
        return
    _roll_session()
    sym = symbol.upper()
    _last_close_by_symbol[sym] = {
        "side": _side_val(side),
        "pnlInr": round(float(pnl_inr), 2),
        "exitReason": exit_reason or "",
        "at": datetime.now(IST),
    }


def _seconds_since_close(symbol: str) -> float:
    last = _last_close_by_symbol.get(symbol.upper())
    if not last or not last.get("at"):
        return 999_999.0
    at = last["at"]
    if at.tzinfo is None:
        at = at.replace(tzinfo=IST)
    return (datetime.now(IST) - at.astimezone(IST)).total_seconds()


def check_opposite_side_cooldown(
    symbol: str,
    side: Side | str,
    snap: SymbolSnapshot,
) -> tuple[bool, str]:
    """Block CE after PE exit (and vice versa) in bearish sideways chop."""
    settings = get_settings()
    if not settings.whipsaw_guards_enabled:
        return False, "ok"

    sym = symbol.upper()
    side_val = _side_val(side)
    last = _last_close_by_symbol.get(sym)
    if not last:
        return False, "ok"
    if last["side"] == side_val:
        return False, "ok"

    if not is_bearish_sideways(snap):
        return False, "ok"

    elapsed = _seconds_since_close(sym)
    cooldown = settings.opposite_side_cooldown_seconds
    if last.get("pnlInr", 0) < 0:
        cooldown = max(cooldown, settings.opposite_side_cooldown_after_loss_seconds)

    from app.engines.expiry_day_guards import relax_opposite_side_for_expiry_dual

    if relax_opposite_side_for_expiry_dual(sym, side_val, snap, {sym: snap}):
        cooldown = min(cooldown, settings.expiry_dual_scalp_opposite_cooldown_seconds)

    if elapsed < cooldown:
        remain = int(cooldown - elapsed)
        return True, f"opposite_side_cooldown_{sym}_{last['side']}_to_{side_val}_{remain}s"
    return False, "ok"


def count_flip_flops(trades: list[TradeRecord], lookback: int) -> int:
    """Count same-symbol CE↔PE switches in recent closed trades."""
    recent = trades[-lookback:] if trades else []
    flips = 0
    for i in range(1, len(recent)):
        prev, cur = recent[i - 1], recent[i]
        if prev.symbol == cur.symbol and prev.side != cur.side:
            flips += 1
    return flips


def trigger_whipsaw_pause(seconds: int, reason: str) -> None:
    global _whipsaw_pause_until
    _roll_session()
    until = datetime.now(IST) + timedelta(seconds=seconds)
    if _whipsaw_pause_until is None or until > _whipsaw_pause_until:
        _whipsaw_pause_until = until


def whipsaw_pause_active(
    snapshots: Optional[dict[str, SymbolSnapshot]] = None,
) -> tuple[bool, str]:
    settings = get_settings()
    if not settings.whipsaw_guards_enabled:
        return False, "ok"
    _roll_session()
    if momentum_rally_bypass_whipsaw(snapshots):
        return False, "momentum_rally_bypass"
    _clear_expired_pause()
    if _whipsaw_pause_until is None:
        return False, "ok"
    now = datetime.now(IST)
    until = _whipsaw_pause_until if _whipsaw_pause_until.tzinfo else _whipsaw_pause_until.replace(tzinfo=IST)
    if now < until.astimezone(IST):
        secs = int((until.astimezone(IST) - now).total_seconds())
        return True, f"whipsaw_pause_{secs}s"
    return False, "ok"


def check_session_whipsaw_pause(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, str, dict[str, Any]]:
    """Session pause when flip-flop churn or dual-leg whipsaw detected."""
    settings = get_settings()
    if not settings.whipsaw_guards_enabled:
        return False, "ok", {}

    if momentum_rally_bypass_whipsaw(snapshots):
        return False, "momentum_rally_bypass", {"momentumRallyBypass": True}

    paused, pause_reason = whipsaw_pause_active(snapshots)
    if paused:
        return True, pause_reason, {"whipsawPaused": True}

    trades = collect_session_trades(state)
    flips = count_flip_flops(trades, settings.flip_flop_lookback_trades)
    meta: dict[str, Any] = {
        "flipFlops": flips,
        "flipFlopLookback": settings.flip_flop_lookback_trades,
    }

    if flips >= settings.flip_flop_max_opposites and is_bearish_sideways_session(snapshots):
        from app.engines.expiry_day_guards import expiry_dual_scalp_active

        if not expiry_dual_scalp_active(snapshots):
            trigger_whipsaw_pause(settings.ce_pe_whipsaw_pause_seconds, "flip_flop_churn")
            return True, f"flip_flop_pause_{flips}_switches", meta

    dual_symbols: list[str] = []
    for sym, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        active, detail = detect_ce_pe_whipsaw(snap)
        if active:
            dual_symbols.append(sym)
            meta["dualLegWhipsaw"] = detail

    if dual_symbols and is_bearish_sideways_session(snapshots):
        from app.engines.expiry_day_guards import expiry_dual_scalp_active

        if not expiry_dual_scalp_active(snapshots) and not _dual_retrigger_blocked():
            trigger_whipsaw_pause(settings.ce_pe_whipsaw_pause_seconds, "dual_leg_whipsaw")
            meta["dualLegSymbols"] = dual_symbols
            return True, f"ce_pe_whipsaw_{','.join(dual_symbols)}", meta

    return False, "ok", meta


def whipsaw_session_status(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> dict[str, Any]:
    """Read-only whipsaw status — does not trigger new pauses (safe for UI summaries)."""
    settings = get_settings()
    trades = collect_session_trades(state)
    bypass = momentum_rally_bypass_whipsaw(snapshots)
    paused, pause_reason = whipsaw_pause_active(snapshots)

    dual_active: dict[str, Any] = {}
    for sym, snap in snapshots.items():
        if not snap.dataAvailable:
            continue
        active, detail = detect_ce_pe_whipsaw(snap)
        if active:
            dual_active[sym] = detail

    return {
        "enabled": settings.whipsaw_guards_enabled,
        "bearishSideways": is_bearish_sideways_session(snapshots),
        "whipsawPaused": paused and not bypass,
        "whipsawPauseReason": pause_reason if paused and not bypass else None,
        "momentumRallyBypass": bypass,
        "flipFlops": count_flip_flops(trades, settings.flip_flop_lookback_trades),
        "flipFlopLookback": settings.flip_flop_lookback_trades,
        "dualLegWhipsaw": dual_active,
        "dualRetriggerCooldown": _dual_retrigger_blocked(),
        "oppositeSideCooldownSeconds": settings.opposite_side_cooldown_seconds,
    }


def check_bearish_sideways_entry(
    candidate: Any,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, str]:
    """Halt scalps in bearish sideways — only high-tier explosions pass."""
    settings = get_settings()
    if not settings.whipsaw_guards_enabled or not settings.bearish_sideways_halt_enabled:
        return False, "ok"

    snap: SymbolSnapshot = candidate.snap
    if not is_bearish_sideways(snap) and not is_bearish_sideways_session(snapshots):
        return False, "ok"

    mode = str(getattr(candidate, "mode", "") or "")
    if mode == "explosion":
        tier = str(getattr(candidate, "tier", "") or "")
        score = float(getattr(candidate, "score", 0) or 0)
        if tier in ("ELITE", "EXPLODING") and score >= settings.bearish_sideways_explosion_min_score:
            return False, "ok"
        return True, "bearish_sideways_explosion_only"

    if settings.bearish_sideways_block_scalps:
        return True, "bearish_sideways_no_scalps"

    return False, "ok"


def check_whipsaw_candidate(
    candidate: Any,
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> tuple[bool, str, dict[str, Any]]:
    """Per-candidate whipsaw / churn gates."""
    settings = get_settings()
    meta: dict[str, Any] = {}
    if not settings.whipsaw_guards_enabled:
        return True, "ok", meta

    symbol = str(getattr(candidate, "symbol", "")).upper()
    side = getattr(candidate, "side", Side.CALL)
    snap: SymbolSnapshot = candidate.snap

    trades = collect_session_trades(state)
    if trades:
        last = trades[-1]
        if (
            last.symbol == symbol
            and last.side != _side_val(side)
            and is_bearish_sideways(snap)
        ):
            meta["lastTradeOppositeSide"] = True
            if last.pnl_inr < 0:
                return False, f"no_flip_after_{last.side}_loss", meta

    blocked, reason = check_opposite_side_cooldown(symbol, side, snap)
    if blocked:
        return False, reason, meta

    dual, dual_meta = detect_ce_pe_whipsaw(snap)
    meta["cePeWhipsaw"] = dual_meta
    if dual and is_bearish_sideways_session(snapshots):
        return False, f"ce_pe_dual_velocity_{symbol}", meta

    blocked, reason = check_bearish_sideways_entry(candidate, snapshots)
    if blocked:
        return False, reason, meta

    return True, "ok", meta


def whipsaw_guard_summary(
    state: AutoTraderState,
    snapshots: dict[str, SymbolSnapshot],
) -> dict[str, Any]:
    return whipsaw_session_status(state, snapshots)
