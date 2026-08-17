"""Session outcome → mode weights — promote what paid, demote what bled."""

from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass
from typing import Any, Optional
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.models.schemas import AutoTraderState

_IST = ZoneInfo("Asia/Kolkata")


@dataclass
class ModeSessionStats:
    mode: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    net_pnl_inr: float = 0.0
    profit_factor: float = 0.0
    win_rate: float = 0.0
    best_points_max: float = 0.0


def _mode_of(trade: Any) -> str:
    mode = str(getattr(trade, "mode", "") or "").strip().lower()
    if mode:
        return mode
    ctx = getattr(trade, "entryContext", None) or {}
    if isinstance(ctx, dict):
        return str(ctx.get("selectionMode") or "").strip().lower()
    return ""


def compute_mode_stats(trades: list[Any]) -> dict[str, ModeSessionStats]:
    buckets: dict[str, list[Any]] = {}
    for t in trades:
        mode = _mode_of(t)
        if not mode:
            mode = "unknown"
        buckets.setdefault(mode, []).append(t)

    out: dict[str, ModeSessionStats] = {}
    for mode, rows in buckets.items():
        wins = sum(1 for t in rows if float(getattr(t, "pnl_inr", 0) or 0) > 0)
        losses = sum(1 for t in rows if float(getattr(t, "pnl_inr", 0) or 0) < 0)
        net = sum(float(getattr(t, "pnl_inr", 0) or 0) for t in rows)
        gross_win = sum(float(getattr(t, "pnl_inr", 0) or 0) for t in rows if float(getattr(t, "pnl_inr", 0) or 0) > 0)
        gross_loss = abs(sum(float(getattr(t, "pnl_inr", 0) or 0) for t in rows if float(getattr(t, "pnl_inr", 0) or 0) < 0))
        pf = gross_win if gross_loss <= 0 else (gross_win / gross_loss if gross_loss else 0.0)
        best_max = max((float(getattr(t, "best_pnl_points", 0) or 0) for t in rows), default=0.0)
        n = len(rows)
        out[mode] = ModeSessionStats(
            mode=mode,
            trades=n,
            wins=wins,
            losses=losses,
            net_pnl_inr=round(net, 2),
            profit_factor=round(pf, 2),
            win_rate=round((wins / n * 100) if n else 0.0, 1),
            best_points_max=best_max,
        )
    return out


def mode_session_rank_bonus(mode: str, mode_stats: dict[str, ModeSessionStats]) -> float:
    """
    Outcome-driven mode tilt for today's book.
    Positive PF modes get promoted; bleeding modes get demoted.
    """
    settings = get_settings()
    if not getattr(settings, "session_mode_feedback_enabled", True):
        return 0.0
    key = (mode or "").strip().lower()
    stats = mode_stats.get(key)
    if stats is None or stats.trades < int(getattr(settings, "session_mode_feedback_min_trades", 2) or 2):
        return 0.0

    target = float(getattr(settings, "edge_session_pf_target", 2.5) or 2.5)
    pf = stats.profit_factor
    bonus = 0.0
    if pf >= target and stats.wins >= 1:
        bonus = min(18.0, 6.0 + (pf - target) * 4.0)
    elif pf >= 1.2 and stats.net_pnl_inr > 0:
        bonus = 4.0
    elif stats.losses >= 2 and stats.net_pnl_inr < 0:
        bonus = -min(22.0, 8.0 + abs(stats.net_pnl_inr) / 5000.0)
    elif pf < 0.6 and stats.trades >= 2:
        bonus = -12.0
    return round(bonus, 2)


def session_has_green_mode(
    state: AutoTraderState, mode: str, trades: Optional[list[Any]] = None
) -> bool:
    """
    True once any trade in `mode` proved green this session.

    Default: closed winner only (pnl>0). Fleeting best≥1pt on a red close must
    not unlock full size (Jul29 24100 CE best+1.5 → −₹72 unlocked 32-lot 77500).
    """
    settings = get_settings()
    require_win = bool(getattr(settings, "size_until_first_green_require_closed_win", True))
    mode = (mode or "").lower()
    if trades is None:
        from app.engines.pretrade_validator import collect_session_trades

        trades = collect_session_trades(state)
    for t in trades:
        if _mode_of(t) != mode:
            continue
        pnl = float(getattr(t, "pnl_inr", 0) or 0)
        best = float(getattr(t, "best_pnl_points", 0) or 0)
        if pnl > 0:
            return True
        if not require_win and best >= 1.0:
            return True
    # Also check in-memory paper trades (bestPnlPoints may not be on TradeRecord yet)
    for t in getattr(state, "closedPaperTrades", []) or []:
        ctx = getattr(t, "entryContext", None) or {}
        st = str(ctx.get("selectionMode") or "").lower()
        if not st:
            st = "explosion" if str(getattr(t, "strategyType", "")).upper() == "EXPLOSIVE" else "scalp"
        if st != mode:
            continue
        if float(getattr(t, "pnlInr", 0) or 0) > 0:
            return True
        if (
            not require_win
            and float(getattr(t, "bestPnlPoints", 0) or 0) >= 1.0
        ):
            return True
    return False


def session_has_green_explosion(state: AutoTraderState, trades: Optional[list[Any]] = None) -> bool:
    """True once any explosion trade went green (pnl>0 or best≥1pt)."""
    return session_has_green_mode(state, "explosion", trades)


def _first_green_capped_modes() -> set[str]:
    settings = get_settings()
    raw = str(getattr(settings, "size_until_first_green_modes_csv", "explosion,scalp") or "explosion,scalp")
    return {m.strip().lower() for m in raw.split(",") if m.strip()}


def cap_lots_until_first_green(lots: int, state: AutoTraderState, *, mode: str = "") -> int:
    """Keep size tiny until the session proves a green trade in this mode.

    Applies to explosion AND scalp (both were never-green oversize sources on Jul20).
    """
    settings = get_settings()
    if not getattr(settings, "size_until_first_green_enabled", True):
        return lots
    m = (mode or "").lower()
    if m not in _first_green_capped_modes():
        return lots
    if session_has_green_mode(state, m):
        return lots
    cap = int(getattr(settings, "size_until_first_green_lot_cap", 6) or 6)
    return min(max(0, lots), cap)


def _side_key(side: Any) -> str:
    return side.value if hasattr(side, "value") else str(side or "").upper()


def _latest_same_strike_explosion_close(
    state: AutoTraderState,
    *,
    symbol: str,
    side: Any,
    strike: float,
) -> Optional[Any]:
    """Latest closed explosion on exact symbol+side+strike (paper book first)."""
    sym = str(symbol or "").upper()
    side_v = _side_key(side)
    strike_f = float(strike or 0)
    latest: Optional[Any] = None
    latest_ts = None

    def _is_match(t: Any) -> bool:
        if str(getattr(t, "symbol", "") or "").upper() != sym:
            return False
        if _side_key(getattr(t, "side", "")) != side_v:
            return False
        if abs(float(getattr(t, "strike", 0) or 0) - strike_f) > 0.01:
            return False
        ctx = getattr(t, "entryContext", None) or {}
        mode = str(ctx.get("selectionMode") or getattr(t, "mode", "") or "").lower()
        st = str(getattr(t, "strategyType", "") or "")
        st_u = st.upper() if not hasattr(st, "value") else str(st.value).upper()
        if mode == "explosion" or st_u == "EXPLOSIVE":
            return True
        if mode == "" and st_u == "EXPLOSIVE":
            return True
        return False

    for t in getattr(state, "closedPaperTrades", []) or []:
        if not _is_match(t):
            continue
        ts = getattr(t, "closedAt", None) or getattr(t, "openedAt", None)
        if latest is None or (ts is not None and (latest_ts is None or ts > latest_ts)):
            latest = t
            latest_ts = ts
    return latest


def cap_opposite_side_flip_after_win(
    lots: int,
    state: AutoTraderState,
    *,
    symbol: str,
    side: Any,
    velocity_3s: float = 0.0,
) -> tuple[int, dict[str, Any]]:
    """Cap / block a counter-flip entry after a same-session WIN on the opposite side.

    Aug6: two CALLs won (market up), then a max-size PUT flip lost −₹20k. Flipping side
    right after an opposite-side winner is a whipsaw — don't ride it at max size.
    Weak-tape flips (v3 below breakout floor) are blocked entirely when configured.
    """
    meta: dict[str, Any] = {"applied": False, "blocked": False}
    settings = get_settings()
    if not getattr(settings, "explosion_whipsaw_flip_guard_enabled", True):
        return lots, meta
    side_v = side.value if hasattr(side, "value") else str(side or "").upper()
    if side_v not in ("CALL", "PUT"):
        return lots, meta
    opp = "PUT" if side_v == "CALL" else "CALL"
    lookback = float(
        getattr(settings, "explosion_whipsaw_flip_lookback_seconds", 3600) or 3600
    )
    now = datetime.now(_IST)
    win = None
    for t in reversed(getattr(state, "closedPaperTrades", []) or []):
        if str(getattr(t, "symbol", "") or "").upper() != symbol.upper():
            continue
        t_side = getattr(t, "side", None)
        t_side_v = t_side.value if hasattr(t_side, "value") else str(t_side or "").upper()
        if t_side_v != opp:
            continue
        closed = getattr(t, "closedAt", None)
        if closed is not None:
            try:
                if (now - closed).total_seconds() > lookback:
                    continue
            except Exception:
                pass
        if float(getattr(t, "pnlInr", 0) or 0) > 0:
            win = t
            break
    if win is None:
        return lots, meta

    try:
        v3 = float(velocity_3s or 0.0)
    except (TypeError, ValueError):
        v3 = 0.0
    min_v3 = float(
        getattr(settings, "explosion_whipsaw_flip_min_velocity_3s", 2.5) or 2.5
    )
    require_v = bool(getattr(settings, "explosion_whipsaw_flip_require_velocity", True))
    block_weak = bool(getattr(settings, "explosion_whipsaw_flip_block_weak", True))
    if require_v and block_weak and v3 < min_v3:
        meta.update({
            "applied": True,
            "blocked": True,
            "blockReason": "whipsaw_flip_velocity_below_breakout",
            "flipFromWinSide": opp,
            "priorWinPnlInr": round(float(getattr(win, "pnlInr", 0) or 0), 2),
            "velocity3s": round(v3, 3),
            "minVelocity3s": min_v3,
            "uncappedLots": lots,
            "cappedLots": 0,
        })
        return 0, meta

    cap = int(getattr(settings, "explosion_whipsaw_flip_lot_cap", 8) or 8)
    capped = min(max(0, lots), max(1, cap))
    meta.update({
        "applied": capped < lots,
        "blocked": False,
        "flipFromWinSide": opp,
        "priorWinPnlInr": round(float(getattr(win, "pnlInr", 0) or 0), 2),
        "uncappedLots": lots,
        "lotCap": cap,
        "cappedLots": capped,
        "velocity3s": round(v3, 3),
        "minVelocity3s": min_v3,
    })
    return capped, meta


def cap_same_strike_explosion_reentry_after_win(
    lots: int,
    state: AutoTraderState,
    *,
    symbol: str,
    side: Any,
    strike: float,
) -> tuple[int, dict[str, Any]]:
    """
    Optional soft-cap after a profitable explosive on this exact strike.

    Default OFF — multiple flat→vertical moments on the same strike in one day
    keep full capital lots. Enable only for the old Jul29 protective behavior
    (win @ 6 lots → next same-strike re-entry capped).
    """
    meta: dict[str, Any] = {"applied": False}
    settings = get_settings()
    if not getattr(settings, "explosion_post_win_same_strike_lot_cap_enabled", False):
        return lots, meta
    prior = _latest_same_strike_explosion_close(
        state, symbol=symbol, side=side, strike=strike,
    )
    if prior is None:
        return lots, meta
    prior_pnl = float(getattr(prior, "pnlInr", 0) or getattr(prior, "pnl_inr", 0) or 0)
    if prior_pnl <= 0:
        meta.update({
            "applied": False,
            "priorTradeId": getattr(prior, "id", None),
            "priorPnlInr": round(prior_pnl, 2),
            "reason": "latest_same_strike_not_a_win",
        })
        return lots, meta
    cap = int(getattr(settings, "explosion_post_win_same_strike_lot_cap", 6) or 6)
    capped = min(max(0, lots), max(1, cap))
    meta.update({
        "applied": capped < lots,
        "priorTradeId": getattr(prior, "id", None),
        "priorPnlInr": round(prior_pnl, 2),
        "priorLots": getattr(prior, "lots", None),
        "uncappedLots": lots,
        "lotCap": cap,
        "cappedLots": capped,
    })
    return capped, meta


def exhausted_ftv_reentry_blocked(
    state: AutoTraderState,
    *,
    symbol: str,
    side: Any,
    strike: float,
    premium: float,
    velocity_3s: float,
) -> tuple[bool, dict[str, Any]]:
    """Block a spent FTV contract until a new post-close base accelerates."""
    settings = get_settings()
    meta: dict[str, Any] = {"applied": False}
    if not getattr(settings, "explosion_post_peak_reentry_guard_enabled", True):
        return False, meta
    prior = _latest_same_strike_explosion_close(
        state, symbol=symbol, side=side, strike=strike,
    )
    if prior is None or getattr(prior, "closedAt", None) is None:
        return False, meta

    ctx = getattr(prior, "entryContext", None) or {}
    ftv = bool(
        ctx.get("ictFlatThenVertical")
        or ctx.get("ictFirstLift")
        or ctx.get("firstLiftCapture")
        or str(ctx.get("momentType") or "") in {
            "first_lift_local_base",
            "flat_then_vertical",
        }
    )
    entry = float(getattr(prior, "entryPremium", 0) or 0)
    peak = max(
        float(getattr(prior, "maxLtp", 0) or 0),
        entry + float(getattr(prior, "bestPnlPoints", 0) or 0),
    )
    min_peak = float(
        getattr(settings, "explosion_post_peak_reentry_min_peak_points", 20.0) or 20.0
    )
    peak_exit = str(getattr(prior, "exitReason", "") or "") in {
        "explosion_peak_capture",
        "explosion_peak_fade_profit_lock",
        "explosion_runner_giveback",
    }
    if not ftv or peak - entry < min_peak or not peak_exit:
        return False, meta

    now = datetime.now(_IST)
    closed_at = prior.closedAt
    if closed_at.tzinfo is None:
        closed_at = closed_at.replace(tzinfo=_IST)
    age_seconds = max(0.0, (now - closed_at.astimezone(_IST)).total_seconds())
    lookback = float(
        getattr(settings, "explosion_post_peak_reentry_lookback_seconds", 1800) or 1800
    )
    if age_seconds > lookback:
        return False, meta

    from app.engines.explosion_detector import post_close_base_reacceleration

    reset, reset_meta = post_close_base_reacceleration(
        symbol,
        strike,
        side,
        closed_at=closed_at,
        current_premium=premium,
        velocity_3s=velocity_3s,
        min_base_samples=int(
            getattr(settings, "explosion_post_peak_reentry_base_samples", 3) or 3
        ),
        min_base_span_seconds=float(
            getattr(settings, "explosion_post_peak_reentry_base_span_seconds", 6.0) or 6.0
        ),
        min_reacceleration_pct=float(
            getattr(settings, "explosion_post_peak_reentry_min_reacceleration_pct", 8.0)
            or 8.0
        ),
        min_velocity_3s=float(
            getattr(settings, "explosion_post_peak_reentry_min_velocity_3s", 1.5) or 1.5
        ),
    )
    near_peak_pct = float(
        getattr(settings, "explosion_post_peak_reentry_near_peak_pct", 15.0) or 15.0
    )
    meta.update(
        {
            "applied": not reset,
            "priorTradeId": getattr(prior, "id", None),
            "priorPeak": round(peak, 2),
            "priorEntry": round(entry, 2),
            "priorExitReason": getattr(prior, "exitReason", None),
            "secondsSinceClose": round(age_seconds, 1),
            "nearExhaustedPeak": float(premium or 0)
            >= peak * (1.0 - max(0.0, near_peak_pct) / 100.0),
            **reset_meta,
        }
    )
    return not reset, meta

