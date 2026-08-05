"""Top ELITE/EXPLODING — never block near-base ATM/ITM entries.

Policy (Aug5): if a top explosion is on radar at ATM/ITM with premium ≥ band
min and still inside the near-base window, take it. Chase / cold tape / MACD /
BREAKOUT_ONLY floors / stand-asides must not bury that print.
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import Side


def _tier_from_sources(
    *,
    tier: Optional[str] = None,
    event: Any = None,
    candidate: Any = None,
    alert: Optional[dict] = None,
) -> str:
    if tier:
        return str(tier).upper()
    if event is not None:
        t = str(getattr(event, "tier", "") or "").upper()
        if t:
            return t
    if candidate is not None:
        t = str(getattr(candidate, "tier", "") or "").upper()
        if t:
            return t
        ev = getattr(candidate, "explosion_event", None)
        if ev is not None:
            t = str(getattr(ev, "tier", "") or "").upper()
            if t:
                return t
        alert = alert or getattr(candidate, "alert", None)
    if isinstance(alert, dict):
        return str(alert.get("tier") or "").upper()
    return ""


def _must_take_tiers() -> set[str]:
    settings = get_settings()
    raw = str(
        getattr(settings, "explosion_top_must_take_tiers_csv", "ELITE,EXPLODING")
        or "ELITE,EXPLODING"
    )
    return {t.strip().upper() for t in raw.split(",") if t.strip()}


def _resolve_sources(
    *,
    event: Any = None,
    candidate: Any = None,
    alert: Optional[dict] = None,
    snap: Any = None,
) -> tuple[Any, dict, Any, Any, float, Side | str, float]:
    """Return event, alert, snap, side, strike, premium."""
    resolved_event = event
    resolved_alert = alert if isinstance(alert, dict) else None
    resolved_snap = snap
    side: Any = ""
    strike = 0.0
    premium = 0.0

    if candidate is not None:
        if resolved_event is None:
            resolved_event = getattr(candidate, "explosion_event", None)
        if resolved_alert is None:
            a = getattr(candidate, "alert", None)
            resolved_alert = a if isinstance(a, dict) else None
        if resolved_snap is None:
            resolved_snap = getattr(candidate, "snap", None)
        side = getattr(candidate, "side", "") or side
        try:
            strike = float(getattr(candidate, "strike", 0) or 0)
        except (TypeError, ValueError):
            strike = 0.0
        try:
            premium = float(getattr(candidate, "premium", 0) or 0)
        except (TypeError, ValueError):
            premium = 0.0

    if resolved_event is not None:
        if not side:
            side = getattr(resolved_event, "side", "")
        if strike <= 0:
            try:
                strike = float(getattr(resolved_event, "strike", 0) or 0)
            except (TypeError, ValueError):
                strike = 0.0
        if premium <= 0:
            try:
                premium = float(getattr(resolved_event, "premium", 0) or 0)
            except (TypeError, ValueError):
                premium = 0.0

    if resolved_alert:
        if not side:
            side = resolved_alert.get("side") or ""
        if strike <= 0:
            try:
                strike = float(resolved_alert.get("strike") or 0)
            except (TypeError, ValueError):
                strike = 0.0
        if premium <= 0:
            try:
                premium = float(resolved_alert.get("premium") or 0)
            except (TypeError, ValueError):
                premium = 0.0

    return resolved_event, resolved_alert or {}, resolved_snap, side, strike, premium


def _near_base_move_pct(
    event: Any,
    alert: dict,
    *,
    ict: Any = None,
) -> float:
    if ict is not None:
        try:
            from app.engines.explosion_entry_guards import trustworthy_local_base_move

            base = trustworthy_local_base_move(ict)
            if base > 0:
                return float(base)
        except Exception:
            pass
        try:
            rel = float(getattr(ict, "base_relative_move_pct", 0) or 0)
            if rel > 0:
                return rel
        except (TypeError, ValueError):
            pass
    if alert:
        for key in (
            "ictBaseRelativeMovePct",
            "baseRelativeMovePct",
            "offLowMovePct",
        ):
            try:
                v = float(alert.get(key) or 0)
            except (TypeError, ValueError):
                v = 0.0
            if v > 0:
                return v
    if event is not None:
        for key in ("ict_base_relative_move_pct", "off_low_move_pct"):
            try:
                v = float(getattr(event, key, 0) or 0)
            except (TypeError, ValueError):
                v = 0.0
            if v > 0:
                return v
    # Never use mega day-peak % as "base move" — that turns every rip into a
    # chase and blocks must-take. Only modest session moves (still near pad)
    # may stand in when ICT local base has not printed yet.
    try:
        from app.config import get_settings as _gs

        hi = float(getattr(_gs(), "ict_structured_early_max_move_pct", 65.0) or 65.0)
    except Exception:
        hi = 65.0
    session = 0.0
    if event is not None:
        try:
            session = max(
                float(getattr(event, "daily_move_pct", 0) or 0),
                float(getattr(event, "peak_move_pct", 0) or 0),
            )
        except (TypeError, ValueError):
            session = 0.0
    if session <= 0 and alert:
        try:
            session = max(
                float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0),
                float(alert.get("peakMovePct") or 0),
            )
        except (TypeError, ValueError):
            session = 0.0
    if 0 < session <= hi:
        return session
    return 0.0


def _in_near_base_window(
    event: Any,
    alert: dict,
    *,
    ict: Any = None,
) -> bool:
    """True when move is inside the structured near-base band (default 10–65%).

    Always use the structured pad (10–65), never the unstructured early floor (28%).
    Aug5 SENSEX 77800 PE was already ELITE at ~11% off the pad — but must-take
    borrowed entry_window_bounds() which raised the floor to 28% until ICT heat
    printed, so we waited, then the rip was 40→160 and died as late chase.
    """
    settings = get_settings()
    lo = float(getattr(settings, "ict_structured_early_min_move_pct", 10.0) or 10.0)
    hi = float(getattr(settings, "ict_structured_early_max_move_pct", 65.0) or 65.0)
    move = _near_base_move_pct(event, alert, ict=ict)
    if move <= 0:
        return False
    return lo <= move <= hi


def _is_atm_or_itm(
    side: Side | str,
    strike: float,
    snap: Any,
) -> bool:
    if snap is None or strike <= 0 or not side:
        return False
    spot = float(getattr(snap, "spot", 0) or 0)
    if spot <= 0:
        return False
    atm = float(getattr(snap, "atmStrike", 0) or 0) or None
    from app.engines.moneyness import classify_moneyness

    money = classify_moneyness(
        side,
        strike,
        spot,
        symbol=str(getattr(snap, "symbol", "NIFTY") or "NIFTY"),
        atm=atm,
    )
    return money in ("ATM", "ITM")


def top_explosion_must_take_active(
    *,
    tier: Optional[str] = None,
    event: Any = None,
    candidate: Any = None,
    alert: Optional[dict] = None,
    snap: Any = None,
    ict: Any = None,
) -> bool:
    """True → take this top ELITE/EXPLODING ATM/ITM near-base print; skip blockers.

    Requires:
      - tier ELITE or EXPLODING
      - premium ≥ min_option_premium_inr
      - ATM or ITM (when strike/snap known)
      - base-relative (or session) move inside near-base window (10–65% structured)
    Does NOT require hot live velocity — COLD_BASE near the pad must still fill.
    """
    settings = get_settings()
    if not bool(getattr(settings, "explosion_top_must_take_enabled", True)):
        return False

    tier_u = _tier_from_sources(
        tier=tier, event=event, candidate=candidate, alert=alert,
    )
    if tier_u not in _must_take_tiers():
        return False

    if candidate is not None:
        mode = str(getattr(candidate, "mode", "") or "")
        if mode and mode != "explosion":
            return False

    resolved_event, resolved_alert, resolved_snap, side, strike, premium = _resolve_sources(
        event=event, candidate=candidate, alert=alert, snap=snap,
    )

    min_score = float(
        getattr(settings, "explosion_top_must_take_min_score", 62.0) or 62.0
    )
    score = 0.0
    if candidate is not None:
        score = float(
            getattr(candidate, "score", 0)
            or getattr(candidate, "confidence", 0)
            or 0
        )
    if score <= 0 and resolved_event is not None:
        score = float(getattr(resolved_event, "explosion_score", 0) or 0)
    if score <= 0 and resolved_alert:
        score = float(resolved_alert.get("explosionScore") or 0)
    if score < min_score:
        return False

    min_prem = float(getattr(settings, "min_option_premium_inr", 18.0) or 18.0)
    if premium > 0 and premium < min_prem:
        return False

    # ATM/ITM required when we can classify; if strike/snap missing, allow tier path
    # only when alert already marked tradeable (radar already filtered OTM).
    if strike > 0 and resolved_snap is not None:
        if not _is_atm_or_itm(side, strike, resolved_snap):
            return False
    elif bool(getattr(settings, "explosion_top_must_take_require_atm_itm", True)):
        if strike > 0 and resolved_snap is None:
            pass  # can't classify — still require near-base below
        elif strike <= 0 and not resolved_alert.get("tradeable", True):
            return False

    resolved_ict = ict
    if resolved_ict is None and resolved_event is not None:
        try:
            from app.engines.ict_breakout_monitor import analyze_explosion_event_ict

            resolved_ict = analyze_explosion_event_ict(resolved_event)
        except Exception:
            resolved_ict = None

    if not _in_near_base_window(resolved_event, resolved_alert, ict=resolved_ict):
        return False

    return True


def elite_never_block_active(
    *,
    tier: Optional[str] = None,
    event: Any = None,
    candidate: Any = None,
    alert: Optional[dict] = None,
    timing: Optional[dict] = None,
    snap: Any = None,
    ict: Any = None,
) -> bool:
    """True when top explosions may skip FOMO/chase/stand-down/live/timing blocks.

    Two paths:
      1) Near-base must-take — ELITE/EXPLODING + ATM/ITM + premium≥min + in 10–65%
         window → always take (Aug5 24500 PE).
      2) Legacy ELITE + GOOD hot timing bypass for other FOMO gates.
    """
    if top_explosion_must_take_active(
        tier=tier,
        event=event,
        candidate=candidate,
        alert=alert,
        snap=snap,
        ict=ict,
    ):
        return True

    settings = get_settings()
    if not getattr(settings, "explosion_elite_never_block_enabled", True):
        return False
    if _tier_from_sources(tier=tier, event=event, candidate=candidate, alert=alert) != "ELITE":
        return False

    if not bool(getattr(settings, "entry_timing_elite_bypass_requires_hot", True)):
        return True

    resolved_timing = timing
    resolved_event = event
    if resolved_event is None and candidate is not None:
        resolved_event = getattr(candidate, "explosion_event", None)

    resolved_snap = snap
    if resolved_snap is None and candidate is not None:
        resolved_snap = getattr(candidate, "snap", None)

    if resolved_timing is None and resolved_event is not None:
        try:
            from app.engines.entry_timing import assess_timing_for_event
            from app.engines.morning_premium_capture import is_premium_capture_event

            chart = getattr(resolved_snap, "spotChart", None) if resolved_snap is not None else None
            resolved_timing = assess_timing_for_event(
                resolved_event,
                snap=resolved_snap,
                premium_capture=is_premium_capture_event(resolved_event, chart=chart),
            )
        except Exception:
            resolved_timing = None

    # Fail closed: without a GOOD timing verdict, bare ELITE does not skip FOMO gates.
    if resolved_timing is None:
        return False
    from app.engines.entry_timing import elite_bypass_allowed_for_timing

    return elite_bypass_allowed_for_timing(resolved_timing)


def snapshots_have_top_must_take(snapshots: dict[str, Any]) -> bool:
    """True when any snapshot has a must-take ELITE/EXPLODING near-base ATM/ITM alert."""
    if not snapshots:
        return False
    for snap in snapshots.values():
        if snap is None:
            continue
        for alert in getattr(snap, "explosionAlerts", None) or []:
            if not isinstance(alert, dict):
                continue
            if top_explosion_must_take_active(alert=alert, snap=snap):
                return True
    return False
