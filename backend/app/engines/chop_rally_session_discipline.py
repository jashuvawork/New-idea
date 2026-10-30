"""CHOP + RALLY session discipline — #676 bottom line (base capture, not ladder stacks).

On CHOP + RALLY only (CE + PE symmetric):
- At most one open explosion leg per index + side (no 22950 + 23050 CE together).
- Same strike after a loss: no restack for the rest of the session.
- Same strike after a win: only #866 fresh-base reentry inside the 22% pad (+ tighter blowout).
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot


def is_chop_rally_day(
    state: Any = None,
    snap: Optional[SymbolSnapshot] = None,
    *,
    day_mode: str = "",
) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "chop_rally_session_discipline_enabled", True)):
        return False
    from app.engines.pe_win_ce_mirror import _resolve_chop_rally_day_mode

    dm = _resolve_chop_rally_day_mode(day_mode, state=state, snap=snap)
    return dm == "CHOP + RALLY"


def chop_rally_symbol_side_open_cap_blocked(
    state: Any,
    *,
    symbol: str,
    side: Any,
    snap: Optional[SymbolSnapshot] = None,
    day_mode: str = "",
) -> tuple[bool, str, dict[str, Any]]:
    """Block a second open explosion on the same index + side (Oct30 22950 + 23050 CE)."""
    meta: dict[str, Any] = {"chopRallyOpenCap": False}
    if not is_chop_rally_day(state, snap, day_mode=day_mode):
        return False, "", meta

    settings = get_settings()
    cap = int(getattr(settings, "chop_rally_max_open_legs_per_symbol_side", 1) or 1)
    if cap < 1:
        return False, "", meta

    from app.engines.session_mode_feedback import _is_explosion_trade, _side_key

    def _open_explosion_leg(t: Any) -> bool:
        if _is_explosion_trade(t):
            return True
        st = getattr(t, "strategyType", None)
        if st is not None and hasattr(st, "value"):
            return str(st.value).upper() == "EXPLOSIVE"
        return str(st or "").upper().endswith("EXPLOSIVE")

    sym = str(symbol or "").upper()
    side_v = _side_key(side)
    open_count = 0
    for t in getattr(state, "openPaperTrades", []) or []:
        if str(getattr(t, "status", "OPEN") or "").upper() != "OPEN":
            continue
        if str(getattr(t, "symbol", "") or "").upper() != sym:
            continue
        if _side_key(getattr(t, "side", "")) != side_v:
            continue
        if not _open_explosion_leg(t):
            continue
        open_count += 1

    meta.update({"openExplosionLegs": open_count, "cap": cap, "chopRallyOpenCap": True})
    if open_count >= cap:
        reason = "chop_rally_one_open_leg_per_symbol_side"
        meta["reason"] = reason
        return True, reason, meta
    return False, "", meta


def chop_rally_same_strike_reentry_discipline_blocked(
    state: Any,
    *,
    symbol: str,
    side: Any,
    strike: float,
    premium: float,
    velocity_3s: float = 0.0,
    alert: Optional[dict[str, Any]] = None,
    snap: Optional[SymbolSnapshot] = None,
    day_mode: str = "",
) -> tuple[bool, str, dict[str, Any]]:
    """Same-strike reentry on CHOP + RALLY: no restack after loss; win only via fresh base."""
    meta: dict[str, Any] = {"chopRallySameStrikeDiscipline": False}
    if not is_chop_rally_day(state, snap, day_mode=day_mode):
        return False, "", meta

    settings = get_settings()
    from app.engines.session_mode_feedback import (
        _latest_same_strike_explosion_close,
        same_strike_post_win_fresh_base_reentry,
        same_strike_post_win_premium_blowout_blocked,
    )

    prior = _latest_same_strike_explosion_close(
        state, symbol=symbol, side=side, strike=float(strike or 0),
    )
    if prior is None:
        return False, "", meta

    prior_pnl = float(
        getattr(prior, "pnlInr", 0) or getattr(prior, "pnl_inr", 0) or 0
    )
    meta["priorPnlInr"] = round(prior_pnl, 2)
    meta["chopRallySameStrikeDiscipline"] = True

    if prior_pnl < -1e-6:
        if bool(getattr(settings, "chop_rally_block_same_strike_after_loss", True)):
            reason = "chop_rally_same_strike_loss_no_restack"
            meta["reason"] = reason
            return True, reason, meta
        return False, "", meta

    if not bool(getattr(settings, "chop_rally_same_strike_post_win_requires_fresh_base", True)):
        return False, "", meta

    side_enum = side if isinstance(side, Side) else Side.CALL if _side_str(side) == "CALL" else Side.PUT
    fresh_ok, fresh_meta = same_strike_post_win_fresh_base_reentry(
        state,
        symbol=symbol,
        side=side_enum,
        strike=float(strike or 0),
        premium=float(premium or 0),
        velocity_3s=float(velocity_3s or 0),
        alert=alert,
    )
    meta["freshBaseCheck"] = fresh_meta
    if not fresh_ok:
        reason = "chop_rally_same_strike_requires_fresh_base"
        meta["reason"] = reason
        return True, reason, meta

    max_pct = float(
        getattr(settings, "chop_rally_same_strike_post_win_max_premium_above_win_entry_pct", 22.0)
        or 22.0
    )
    blow_b, blow_r, blow_m = same_strike_post_win_premium_blowout_blocked(
        state,
        symbol=symbol,
        side=side_enum,
        strike=float(strike or 0),
        premium=float(premium or 0),
        velocity_3s=float(velocity_3s or 0),
        max_premium_above_win_entry_pct=max_pct,
    )
    meta["blowoutCheck"] = blow_m
    if blow_b:
        return True, blow_r or "same_strike_post_win_premium_blowout", meta

    return False, "", meta


def _side_str(side: Any) -> str:
    return side.value if isinstance(side, Side) else str(side or "").upper()
