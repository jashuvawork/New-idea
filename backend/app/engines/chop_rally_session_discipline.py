"""Session repeat discipline — #676 bottom line (base capture, not ladder stacks).

Applies on configured day modes (default: all regular capture days except EXPIRY WORST).
CE + PE symmetric:
- At most one open explosion leg per index + side.
- Same strike after a loss: no restack for the rest of the session.
- Same strike after a win: only #866 fresh-base reentry inside the 22% pad (+ tighter blowout).

Does not replace #890 post-win different-strike ladder (global); EOD showed ladder blocks
hurt trend days when combined with this bundle on all 21 radar ZIPs.
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot

# Modes where EOD / worst-day machinery already caps behavior — skip repeat bundle.
_DEFAULT_EXCLUDED_MODES = frozenset({"EXPIRY WORST", "NO_DATA"})

_DEFAULT_DISCIPLINE_MODES = frozenset({
    "CHOP + RALLY",
    "CHOP DAY",
    "CHOP (PRE-10)",
    "MOMENTUM RALLY",
    "MIXED DAY",
    "NORMAL",
    "BULLISH DAY",
    "LEAN BULLISH",
    "BEARISH DAY",
    "LEAN BEARISH",
    "EXPIRY DAY",
})


def _parse_modes_csv(raw: str) -> frozenset[str]:
    text = str(raw or "").strip()
    if not text:
        return frozenset()
    if text == "*":
        return _DEFAULT_DISCIPLINE_MODES
    return frozenset(s.strip().upper() for s in text.split(",") if s.strip())


def session_repeat_discipline_modes(settings: Any = None) -> frozenset[str]:
    settings = settings or get_settings()
    csv = getattr(settings, "session_repeat_discipline_day_modes_csv", None)
    if csv is not None and str(csv).strip():
        modes = _parse_modes_csv(str(csv))
    elif bool(getattr(settings, "chop_rally_session_discipline_enabled", True)):
        modes = frozenset({"CHOP + RALLY"})
    else:
        modes = frozenset()
    exclude = _parse_modes_csv(
        str(getattr(settings, "session_repeat_discipline_exclude_day_modes_csv", "") or "")
    )
    if not exclude:
        exclude = _DEFAULT_EXCLUDED_MODES
    return frozenset(m for m in modes if m not in exclude)


def is_session_repeat_discipline_day(
    state: Any = None,
    snap: Optional[SymbolSnapshot] = None,
    *,
    day_mode: str = "",
) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "session_repeat_discipline_enabled", True)):
        if not bool(getattr(settings, "chop_rally_session_discipline_enabled", True)):
            return False
    modes = session_repeat_discipline_modes(settings)
    if not modes:
        return False
    from app.engines.pe_win_ce_mirror import _resolve_chop_rally_day_mode

    dm = _resolve_chop_rally_day_mode(day_mode, state=state, snap=snap).strip().upper()
    if not dm:
        return False
    return dm in modes


def is_chop_rally_day(
    state: Any = None,
    snap: Optional[SymbolSnapshot] = None,
    *,
    day_mode: str = "",
) -> bool:
    """Backward-compatible alias."""
    return is_session_repeat_discipline_day(state, snap, day_mode=day_mode)


def _open_cap(settings: Any) -> int:
    cap = getattr(settings, "session_repeat_discipline_max_open_legs_per_symbol_side", None)
    if cap is None:
        cap = getattr(settings, "chop_rally_max_open_legs_per_symbol_side", 1)
    return int(cap or 1)


def _block_same_strike_after_loss(settings: Any) -> bool:
    v = getattr(settings, "session_repeat_discipline_block_same_strike_after_loss", None)
    if v is None:
        return bool(getattr(settings, "chop_rally_block_same_strike_after_loss", True))
    return bool(v)


def _require_fresh_base_after_win(settings: Any) -> bool:
    v = getattr(settings, "session_repeat_discipline_same_strike_post_win_requires_fresh_base", None)
    if v is None:
        return bool(getattr(settings, "chop_rally_same_strike_post_win_requires_fresh_base", True))
    return bool(v)


def _blowout_pct(settings: Any) -> float:
    v = getattr(settings, "session_repeat_discipline_same_strike_post_win_max_premium_above_win_entry_pct", None)
    if v is None:
        v = getattr(settings, "chop_rally_same_strike_post_win_max_premium_above_win_entry_pct", 22.0)
    return float(v or 22.0)


def chop_rally_symbol_side_open_cap_blocked(
    state: Any,
    *,
    symbol: str,
    side: Any,
    snap: Optional[SymbolSnapshot] = None,
    day_mode: str = "",
) -> tuple[bool, str, dict[str, Any]]:
    """Block a second open explosion on the same index + side."""
    meta: dict[str, Any] = {"sessionRepeatOpenCap": False}
    if not is_session_repeat_discipline_day(state, snap, day_mode=day_mode):
        return False, "", meta

    settings = get_settings()
    cap = _open_cap(settings)
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

    meta.update({
        "openExplosionLegs": open_count,
        "cap": cap,
        "sessionRepeatOpenCap": True,
        "chopRallyOpenCap": True,
    })
    if open_count >= cap:
        reason = "session_one_open_leg_per_symbol_side"
        meta["reason"] = reason
        meta["legacyReason"] = "chop_rally_one_open_leg_per_symbol_side"
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
    """Same-strike reentry: no restack after loss; win only via fresh base (+ 22% blowout)."""
    meta: dict[str, Any] = {"sessionRepeatSameStrikeDiscipline": False}
    if not is_session_repeat_discipline_day(state, snap, day_mode=day_mode):
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
    meta["sessionRepeatSameStrikeDiscipline"] = True
    meta["chopRallySameStrikeDiscipline"] = True

    if prior_pnl < -1e-6:
        if _block_same_strike_after_loss(settings):
            reason = "session_same_strike_loss_no_restack"
            meta["reason"] = reason
            meta["legacyReason"] = "chop_rally_same_strike_loss_no_restack"
            return True, reason, meta
        return False, "", meta

    if not _require_fresh_base_after_win(settings):
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
        reason = "session_same_strike_requires_fresh_base"
        meta["reason"] = reason
        meta["legacyReason"] = "chop_rally_same_strike_requires_fresh_base"
        return True, reason, meta

    max_pct = _blowout_pct(settings)
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
