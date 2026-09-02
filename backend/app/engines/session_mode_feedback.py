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


def _failed_launch_reentry_exit_reasons(settings: Any) -> set[str]:
    raw = getattr(
        settings,
        "explosion_failed_launch_reentry_exit_reasons_csv",
        "explosion_failed_launch,explosion_never_green_stop,adaptive_stop_loss",
    )
    if not isinstance(raw, str) or not raw.strip():
        raw = "explosion_failed_launch,explosion_never_green_stop,adaptive_stop_loss"
    return {part.strip() for part in raw.split(",") if part.strip()}


def _failed_launch_reentry_qualifies(
    *,
    exit_reason: str,
    prior_pnl: float,
    best_points: float,
    settings: Any,
) -> bool:
    """True when a prior close should arm the failed-launch re-entry cooldown."""
    reason = str(exit_reason or "").strip()
    max_best = float(
        getattr(settings, "explosion_failed_launch_max_best_points", 1.0) or 1.0
    )
    if reason == "adaptive_stop_loss":
        # Aug28 24050 PE: adaptive SL after best +0.3pt must not re-arm 17m later.
        return prior_pnl < 0 and best_points <= max_best
    if prior_pnl >= 0 and best_points > 1.0:
        return False
    return True


def _latest_failed_launch_nearby_close(
    state: AutoTraderState,
    *,
    symbol: str,
    side: Any,
    strike: float,
    strike_steps: int = 1,
) -> Optional[Any]:
    """Latest failed-launch / never-green close within ±strike_steps of strike."""
    sym = str(symbol or "").upper()
    side_v = _side_key(side)
    strike_f = float(strike or 0)
    try:
        from app.engines.moneyness import strike_step

        step = float(strike_step(sym) or 50.0)
    except Exception:
        step = 50.0
    max_dist = max(0.0, float(strike_steps) * step) + 0.01
    settings = get_settings()
    reasons = _failed_launch_reentry_exit_reasons(settings)
    latest: Optional[Any] = None
    latest_ts = None

    def _is_explosion(t: Any) -> bool:
        ctx = getattr(t, "entryContext", None) or {}
        mode = str(ctx.get("selectionMode") or getattr(t, "mode", "") or "").lower()
        st = str(getattr(t, "strategyType", "") or "")
        st_u = st.upper() if not hasattr(st, "value") else str(st.value).upper()
        return mode == "explosion" or st_u == "EXPLOSIVE"

    for t in getattr(state, "closedPaperTrades", []) or []:
        if str(getattr(t, "symbol", "") or "").upper() != sym:
            continue
        if _side_key(getattr(t, "side", "")) != side_v:
            continue
        if not _is_explosion(t):
            continue
        reason = str(getattr(t, "exitReason", "") or "")
        if reason not in reasons:
            continue
        prior_strike = float(getattr(t, "strike", 0) or 0)
        if abs(prior_strike - strike_f) > max_dist:
            continue
        prior_pnl = float(getattr(t, "pnlInr", 0) or getattr(t, "pnl_inr", 0) or 0)
        best = float(getattr(t, "bestPnlPoints", 0) or 0)
        if not _failed_launch_reentry_qualifies(
            exit_reason=reason,
            prior_pnl=prior_pnl,
            best_points=best,
            settings=settings,
        ):
            continue
        ts = getattr(t, "closedAt", None) or getattr(t, "openedAt", None)
        if latest is None or (ts is not None and (latest_ts is None or ts > latest_ts)):
            latest = t
            latest_ts = ts
    return latest


def failed_launch_reentry_blocked(
    state: AutoTraderState,
    *,
    symbol: str,
    side: Any,
    strike: float,
) -> tuple[bool, dict[str, Any]]:
    """Block same/nearby-strike re-entry after failed launch or never-green stop.

    Failed launches that never went green are chop spikes — do not re-arm the same
    contract (or ATM±1) until the cooldown expires. Peak-exhaustion guard does not
    cover these because bestPnl was 0. Never-green hard cuts often exit with flat
    velocity, so they must arm the same cooldown.
    """
    settings = get_settings()
    meta: dict[str, Any] = {"applied": False}
    if not getattr(settings, "explosion_failed_launch_reentry_block_enabled", True):
        return False, meta
    strike_steps_raw = getattr(
        settings, "explosion_failed_launch_reentry_strike_steps", 1
    )
    try:
        strike_steps = int(strike_steps_raw)
    except (TypeError, ValueError):
        strike_steps = 1
    prior = _latest_failed_launch_nearby_close(
        state,
        symbol=symbol,
        side=side,
        strike=strike,
        strike_steps=max(0, strike_steps),
    )
    if prior is None or getattr(prior, "closedAt", None) is None:
        return False, meta
    reason = str(getattr(prior, "exitReason", "") or "")
    prior_pnl = float(getattr(prior, "pnlInr", 0) or getattr(prior, "pnl_inr", 0) or 0)
    best = float(getattr(prior, "bestPnlPoints", 0) or 0)

    now = datetime.now(_IST)
    closed_at = prior.closedAt
    if closed_at.tzinfo is None:
        closed_at = closed_at.replace(tzinfo=_IST)
    age_seconds = max(0.0, (now - closed_at.astimezone(_IST)).total_seconds())
    cooldown = float(
        getattr(settings, "explosion_failed_launch_reentry_cooldown_seconds", 1800)
        or 1800
    )
    if age_seconds > cooldown:
        return False, meta
    meta.update(
        {
            "applied": True,
            "priorTradeId": getattr(prior, "id", None),
            "priorExitReason": reason,
            "priorStrike": float(getattr(prior, "strike", 0) or 0),
            "priorPnlInr": round(prior_pnl, 2),
            "priorBestPoints": round(best, 2),
            "ageSeconds": round(age_seconds, 1),
            "cooldownSeconds": cooldown,
            "strikeSteps": strike_steps,
            "reason": "failed_launch_reentry_cooldown",
        }
    )
    return True, meta


def _prior_session_explosion_closes(
    state: AutoTraderState,
    *,
    symbol: str,
    side: Any,
) -> list[Any]:
    """Closed explosion trades today on symbol+side (any strike)."""
    sym = str(symbol or "").upper()
    side_v = _side_key(side)
    closes: list[Any] = []

    def _is_explosion(t: Any) -> bool:
        ctx = getattr(t, "entryContext", None) or {}
        mode = str(ctx.get("selectionMode") or getattr(t, "mode", "") or "").lower()
        st = str(getattr(t, "strategyType", "") or "")
        st_u = st.upper() if not hasattr(st, "value") else str(st.value).upper()
        return mode == "explosion" or st_u == "EXPLOSIVE"

    for t in getattr(state, "closedPaperTrades", []) or []:
        if str(getattr(t, "symbol", "") or "").upper() != sym:
            continue
        if _side_key(getattr(t, "side", "")) != side_v:
            continue
        if not _is_explosion(t):
            continue
        if getattr(t, "closedAt", None) is None:
            continue
        closes.append(t)
    return closes


def reentry_ml_win_prob_blocked(
    state: AutoTraderState,
    *,
    symbol: str,
    side: Any,
    strike: float,
    snap: Any,
    confidence: float = 70.0,
) -> tuple[bool, dict[str, Any]]:
    """Block session / same-strike re-entries when ML win probability is too low.

    Aug28: winners ~56% ML, 24050 post-win/post-loss re-entries ~41-43%.
    First entries (no prior closes on symbol+side) are not gated.
    """
    settings = get_settings()
    meta: dict[str, Any] = {"applied": False}
    if not getattr(settings, "explosion_reentry_ml_win_prob_gate_enabled", True):
        return False, meta

    prior_closes = _prior_session_explosion_closes(state, symbol=symbol, side=side)
    same_strike_prior = _latest_same_strike_explosion_close(
        state,
        symbol=symbol,
        side=side,
        strike=strike,
    )
    if not prior_closes and same_strike_prior is None:
        return False, meta

    session_min = float(
        getattr(settings, "explosion_reentry_ml_win_prob_min", 0.52) or 0.52
    )
    same_strike_min = float(
        getattr(
            settings,
            "explosion_reentry_ml_win_prob_same_strike_min",
            0.55,
        )
        or 0.55
    )
    if same_strike_prior is not None:
        required = same_strike_min
        reentry_kind = "same_strike"
        prior = same_strike_prior
    else:
        required = session_min
        reentry_kind = "session"
        prior = prior_closes[-1]

    side_val = side.value if hasattr(side, "value") else str(side or "PUT").upper()
    from app.engines.adaptive_exits import predict_entry_ml_win_prob

    ml_prob = predict_entry_ml_win_prob(
        snap,
        side=side_val,
        confidence=float(confidence or 70.0),
    )
    meta.update(
        {
            "applied": True,
            "reentryKind": reentry_kind,
            "mlWinProb": round(ml_prob, 3),
            "requiredMlWinProb": round(required, 3),
            "priorTradeId": getattr(prior, "id", None),
            "priorExitReason": str(getattr(prior, "exitReason", "") or ""),
            "priorPnlInr": round(
                float(getattr(prior, "pnlInr", 0) or getattr(prior, "pnl_inr", 0) or 0),
                2,
            ),
            "reason": "reentry_ml_win_prob_low",
        }
    )
    if ml_prob + 1e-9 < required:
        return True, meta
    return False, meta


def session_peak_late_reentry_blocked(
    *,
    symbol: str,
    side: Any,
    strike: float,
    premium: float,
    velocity_3s: float,
    alert: Optional[dict[str, Any]] = None,
) -> tuple[bool, str]:
    """Block chasing a strike still near its session peak after a real rip.

    Uses live session peak/low from the premium tape — not only prior closed trades.
    Fresh first-lift launches with real velocity may still pass.
    """
    settings = get_settings()
    if not bool(getattr(settings, "explosion_late_reentry_block_enabled", True)):
        return False, ""

    from app.engines.explosion_detector import (
        get_session_low_premium,
        get_session_peak_premium,
    )

    sess_peak = float(get_session_peak_premium(symbol, strike, side) or 0)
    sess_low = float(get_session_low_premium(symbol, strike, side) or 0)
    prem = float(premium or 0)
    if sess_peak <= 0 or prem <= 0:
        return False, ""

    min_peak_pts = float(
        getattr(settings, "explosion_late_reentry_min_peak_points", 15.0) or 15.0
    )
    peak_gain = sess_peak - sess_low if sess_low > 0 else 0.0
    if peak_gain < min_peak_pts:
        return False, ""

    pullback_ok_pct = float(
        getattr(settings, "explosion_late_reentry_pullback_ok_pct", 22.0) or 22.0
    )
    pullback_pct = ((sess_peak - prem) / sess_peak * 100.0) if sess_peak > 0 else 0.0
    if pullback_pct >= pullback_ok_pct:
        return False, ""

    near_peak_pct = float(
        getattr(settings, "explosion_late_reentry_near_peak_pct", 12.0) or 12.0
    )
    if prem < sess_peak * (1.0 - near_peak_pct / 100.0):
        return False, ""

    alert_d = alert if isinstance(alert, dict) else {}
    first_lift = bool(
        alert_d.get("ictFirstLift")
        or alert_d.get("firstLiftCapture")
        or alert_d.get("firstLiftReadinessReason")
        in {
            "first_lift_local_base_ready",
            "first_lift_option_led_ready",
            "armed_base_option_led_ready",
            "armed_base_launch_ready",
        }
    )
    min_v3 = float(
        getattr(settings, "explosion_late_reentry_min_velocity_3s", 1.2) or 1.2
    )
    v3 = float(velocity_3s or 0)
    v9 = float(alert_d.get("velocity9s") or alert_d.get("velocity_9s") or 0)
    if first_lift and v3 >= min_v3:
        return False, ""

    # Aug27 SENSEX PUT 77400: v_rip/first_lift at local-base pad with flat v3 is the
    # initial lift off trough — premium near session peak is expected, not a chase.
    from app.engines.explosion_detector import first_lift_pad_capture_lane
    from app.engines.pad_lane_capture import (
        _ftv_direct_evidence_from_alert,
        pad_lane_cold_velocity_ok,
    )

    pad_evidence = _ftv_direct_evidence_from_alert(alert_d)
    pad_evidence["firstLift"] = first_lift
    tier_u = str(alert_d.get("tier") or "").upper()
    peak_move = float(
        alert_d.get("peakMovePct") or alert_d.get("dailyMovePct") or 0
    )
    local_base = float(pad_evidence.get("localBaseMovePct") or 0)
    v_rip_ready = bool(pad_evidence.get("vRipReady"))
    if (
        first_lift_pad_capture_lane(
            tier=tier_u,
            peak_move_pct=peak_move,
            first_lift_ready=first_lift,
            local_base_move_pct=local_base,
            v_rip_ready=v_rip_ready,
        )
        and pad_lane_cold_velocity_ok(pad_evidence, v3, v9)
    ):
        return False, ""

    # Aug28 SENSEX PUT 77500: fresh ict_base_armed re-base near session peak with cold v3.
    from app.engines.early_radar_pad_capture import ict_base_armed_prelaunch_pad_lane

    if (
        ict_base_armed_prelaunch_pad_lane(alert_d)
        and pad_lane_cold_velocity_ok(pad_evidence, v3, v9)
    ):
        return False, ""

    return True, (
        f"late_reentry_near_session_peak_{sess_peak:.1f}"
        f"_pullback_{pullback_pct:.1f}pct_v3_{v3:.1f}"
    )


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
        or ctx.get("ictArmedBaseLaunch")
        or ctx.get("armedBaseCapture")
        or str(ctx.get("momentType") or "") in {
            "first_lift_local_base",
            "flat_then_vertical",
            "armed_base_launch",
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
    material_peak = peak - entry >= min_peak
    if not ftv or not material_peak:
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


def _latest_peak_fade_same_side_close(
    state: AutoTraderState,
    *,
    symbol: str,
    side: Any,
    min_peak_points: float,
) -> Optional[Any]:
    """Latest closed explosion on symbol+side with red close after material peak."""
    sym = str(symbol or "").upper()
    side_v = _side_key(side)
    latest: Optional[Any] = None
    latest_ts = None

    def _is_explosion(t: Any) -> bool:
        ctx = getattr(t, "entryContext", None) or {}
        mode = str(ctx.get("selectionMode") or getattr(t, "mode", "") or "").lower()
        st = str(getattr(t, "strategyType", "") or "")
        st_u = st.upper() if not hasattr(st, "value") else str(st.value).upper()
        return mode == "explosion" or st_u == "EXPLOSIVE"

    for t in getattr(state, "closedPaperTrades", []) or []:
        if str(getattr(t, "symbol", "") or "").upper() != sym:
            continue
        if _side_key(getattr(t, "side", "")) != side_v:
            continue
        if not _is_explosion(t):
            continue
        if getattr(t, "closedAt", None) is None:
            continue
        prior_pnl = float(getattr(t, "pnlInr", 0) or getattr(t, "pnl_inr", 0) or 0)
        if prior_pnl >= 0:
            continue
        best = float(getattr(t, "bestPnlPoints", 0) or getattr(t, "best_pnl_points", 0) or 0)
        if best + 1e-9 < float(min_peak_points):
            continue
        ts = t.closedAt
        if latest is None or (ts is not None and (latest_ts is None or ts > latest_ts)):
            latest = t
            latest_ts = ts
    return latest


def peak_fade_same_side_reentry_blocked(
    state: AutoTraderState,
    *,
    symbol: str,
    side: Any,
) -> tuple[bool, dict[str, Any]]:
    """Block same-side re-entry after a peak-fade loss on symbol+side.

    When a trade closed red but bestPnlPoints reached a material peak (default 30+),
    do not re-enter the same option side on that symbol until cooldown expires.
    Not bypassable by aligned_rip or post-loss interval waivers.
    """
    settings = get_settings()
    meta: dict[str, Any] = {"applied": False}
    if not getattr(settings, "peak_fade_same_side_reentry_enabled", True):
        return False, meta
    min_peak = float(
        getattr(settings, "peak_fade_same_side_reentry_min_peak_points", 30.0) or 30.0
    )
    prior = _latest_peak_fade_same_side_close(
        state,
        symbol=symbol,
        side=side,
        min_peak_points=min_peak,
    )
    if prior is None or getattr(prior, "closedAt", None) is None:
        return False, meta

    now = datetime.now(_IST)
    closed_at = prior.closedAt
    if closed_at.tzinfo is None:
        closed_at = closed_at.replace(tzinfo=_IST)
    age_seconds = max(0.0, (now - closed_at.astimezone(_IST)).total_seconds())
    cooldown = float(
        getattr(settings, "peak_fade_same_side_reentry_cooldown_seconds", 900) or 900
    )
    if age_seconds > cooldown:
        return False, meta

    prior_pnl = float(getattr(prior, "pnlInr", 0) or getattr(prior, "pnl_inr", 0) or 0)
    best = float(getattr(prior, "bestPnlPoints", 0) or getattr(prior, "best_pnl_points", 0) or 0)
    meta.update(
        {
            "applied": True,
            "priorTradeId": getattr(prior, "id", None),
            "priorStrike": float(getattr(prior, "strike", 0) or 0),
            "priorExitReason": str(getattr(prior, "exitReason", "") or ""),
            "priorPnlInr": round(prior_pnl, 2),
            "priorBestPoints": round(best, 2),
            "ageSeconds": round(age_seconds, 1),
            "cooldownSeconds": cooldown,
            "reason": "peak_fade_same_side_reentry_cooldown",
        }
    )
    return True, meta


def _is_explosion_trade(t: Any) -> bool:
    ctx = getattr(t, "entryContext", None) or {}
    mode = str(ctx.get("selectionMode") or getattr(t, "mode", "") or "").lower()
    st = str(getattr(t, "strategyType", "") or "")
    st_u = st.upper() if not hasattr(st, "value") else str(st.value).upper()
    return mode == "explosion" or st_u == "EXPLOSIVE"


def _latest_same_side_loss_close(
    state: AutoTraderState,
    *,
    side: Any,
) -> Optional[Any]:
    """Latest closed explosion loss today on any symbol for this side."""
    side_v = _side_key(side)
    latest: Optional[Any] = None
    latest_ts = None

    for t in getattr(state, "closedPaperTrades", []) or []:
        if _side_key(getattr(t, "side", "")) != side_v:
            continue
        if not _is_explosion_trade(t):
            continue
        if getattr(t, "closedAt", None) is None:
            continue
        prior_pnl = float(getattr(t, "pnlInr", 0) or getattr(t, "pnl_inr", 0) or 0)
        if prior_pnl >= 0:
            continue
        ts = t.closedAt
        if latest is None or (ts is not None and (latest_ts is None or ts > latest_ts)):
            latest = t
            latest_ts = ts
    return latest


def session_same_side_loss_reentry_blocked(
    state: AutoTraderState,
    *,
    symbol: str,
    side: Any,
    candidate: Any = None,
) -> tuple[bool, dict[str, Any]]:
    """Block or re-qualify same-side re-entry after a session explosion loss.

    Two-tier policy (Sep 2 live history):
    1. Hard cooldown (default 15m): block all same-side entries on any symbol.
    2. Elevated bar (default 15m–60m): allow only if candidate re-earns min grade
       (default S) via full causal ranking — not bypassable by aligned_rip.
    After elevated window, normal gates apply.
    """
    settings = get_settings()
    meta: dict[str, Any] = {"applied": False}
    if not getattr(settings, "session_same_side_loss_reentry_enabled", True):
        return False, meta
    prior = _latest_same_side_loss_close(state, side=side)
    if prior is None or getattr(prior, "closedAt", None) is None:
        return False, meta

    now = datetime.now(_IST)
    closed_at = prior.closedAt
    if closed_at.tzinfo is None:
        closed_at = closed_at.replace(tzinfo=_IST)
    age_seconds = max(0.0, (now - closed_at.astimezone(_IST)).total_seconds())
    hard_cooldown = float(
        getattr(settings, "session_same_side_loss_reentry_cooldown_seconds", 900) or 900
    )
    elevated_bar = float(
        getattr(settings, "session_same_side_loss_reentry_elevated_bar_seconds", 3600)
        or 3600
    )
    prior_pnl = float(getattr(prior, "pnlInr", 0) or getattr(prior, "pnl_inr", 0) or 0)
    prior_sym = str(getattr(prior, "symbol", "") or "").upper()
    meta_base = {
        "priorTradeId": getattr(prior, "id", None),
        "priorSymbol": prior_sym,
        "priorStrike": float(getattr(prior, "strike", 0) or 0),
        "priorExitReason": str(getattr(prior, "exitReason", "") or ""),
        "priorPnlInr": round(prior_pnl, 2),
        "ageSeconds": round(age_seconds, 1),
        "hardCooldownSeconds": hard_cooldown,
        "elevatedBarSeconds": elevated_bar,
        "crossSymbol": prior_sym != str(symbol or "").upper(),
    }

    if age_seconds > max(hard_cooldown, elevated_bar):
        return False, meta

    if age_seconds > hard_cooldown:
        min_grade = str(
            getattr(settings, "session_same_side_loss_reentry_elevated_min_grade", "S")
            or "S"
        ).upper()
        if candidate is not None and min_grade:
            from app.engines.trade_ranking import rank_entry_candidate

            ranking = rank_entry_candidate(candidate)
            grade = str(ranking.get("grade") or "").upper()
            meta_base["causalGrade"] = grade
            meta_base["requiredGrade"] = min_grade
            if grade == min_grade:
                return False, meta
        meta.update(
            {
                **meta_base,
                "applied": True,
                "reason": "session_same_side_loss_elevated_bar",
            }
        )
        return True, meta

    meta.update(
        {
            **meta_base,
            "applied": True,
            "cooldownSeconds": hard_cooldown,
            "reason": "session_same_side_loss_reentry_cooldown",
        }
    )
    return True, meta

