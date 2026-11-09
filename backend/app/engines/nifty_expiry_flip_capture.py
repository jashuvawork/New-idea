"""NIFTY expiry: armed index/loss flip → near-base capture waivers (CE/PE symmetric)."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side or "").upper()


def _local_pad_from_alert(alert: Mapping[str, Any] | None, explosion_event: Any = None) -> float:
    if isinstance(alert, Mapping):
        for key in ("localBaseMovePct", "ictBaseRelativeMovePct", "offLowMovePct"):
            try:
                v = float(alert.get(key) or 0)
                if v > 0:
                    return v
            except (TypeError, ValueError):
                pass
    if explosion_event is not None:
        try:
            return float(getattr(explosion_event, "daily_move_pct", 0) or 0)
        except (TypeError, ValueError):
            pass
    return 0.0


def _tier_ok(tier: str, settings: Any) -> bool:
    tier_u = str(tier or "").upper()
    allowed = {
        t.strip().upper()
        for t in str(
            getattr(settings, "nifty_expiry_flip_capture_elite_tiers_csv", "ELITE,EXPLODING")
            or "ELITE,EXPLODING"
        ).split(",")
        if t.strip()
    }
    return tier_u in allowed


def nifty_expiry_flip_capture_armed(
    symbol: str,
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    state: Any = None,
    alert: Mapping[str, Any] | None = None,
    explosion_event: Any = None,
    candidate: Any = None,
    settings: Any = None,
) -> tuple[bool, str, dict[str, Any]]:
    """
    True on NIFTY weekly/monthly expiry when flip structure is armed and pad is near base.

    Armed = index_rally_side_flip_bypass (CALL rally / PUT slide) OR
            loss_triggered_opposite_flip_ready for target side.
    """
    settings = settings or get_settings()
    meta: dict[str, Any] = {"niftyExpiryFlipCapture": False}
    if not bool(getattr(settings, "nifty_expiry_flip_capture_waiver_enabled", True)):
        return False, "disabled", meta
    sym = str(symbol or getattr(snap, "symbol", "") or "").upper()
    if sym != "NIFTY":
        return False, "not_nifty", meta

    from app.engines.expiry_day_guards import is_symbol_expiry_day

    if not is_symbol_expiry_day(snap):
        return False, "not_expiry_day", meta

    side_v = _side_val(side)
    if side_v not in {"CALL", "PUT"}:
        return False, "invalid_side", meta

    tier = ""
    if explosion_event is not None:
        tier = str(getattr(explosion_event, "tier", "") or "")
    if not tier and isinstance(alert, Mapping):
        tier = str(alert.get("tier") or alert.get("bestTier") or "")
    if candidate is not None and not tier:
        tier = str(getattr(candidate, "tier", "") or "")
    if not _tier_ok(tier, settings):
        return False, "tier", {**meta, "tier": tier}

    local_pad = _local_pad_from_alert(alert, explosion_event)
    max_pad = float(
        getattr(settings, "nifty_expiry_flip_capture_max_local_base_pct", 28.0) or 28.0
    )
    meta["localBasePct"] = round(local_pad, 2)
    meta["maxLocalBasePct"] = max_pad
    if local_pad <= 0 or local_pad > max_pad + 1e-6:
        return False, "pad_out_of_band", meta

    from app.engines.index_rally_side_flip import index_rally_side_flip_bypass

    rally_ok, rally_reason, rally_meta = index_rally_side_flip_bypass(
        sym, side_v, snap, settings=settings,
    )
    meta.update(rally_meta or {})
    if rally_ok:
        meta["niftyExpiryFlipCapture"] = True
        meta["flipMode"] = rally_reason or "index_rally_side_flip"
        return True, meta["flipMode"], meta

    if state is not None:
        from app.engines.loss_triggered_side_flip import loss_triggered_opposite_flip_ready

        loss_ok, loss_reason, loss_meta = loss_triggered_opposite_flip_ready(
            sym,
            side_v,
            snap,
            state,
            candidate=candidate or explosion_event,
        )
        meta.update(loss_meta or {})
        if loss_ok:
            meta["niftyExpiryFlipCapture"] = True
            meta["flipMode"] = loss_reason or "loss_triggered_side_flip"
            return True, meta["flipMode"], meta

    return False, rally_reason or "flip_not_armed", meta


def nifty_expiry_flip_near_miss_waive(
    alert: Optional[dict[str, Any]],
    *,
    snap: Optional[SymbolSnapshot] = None,
    state: Any = None,
    readiness_reason: str = "",
    settings: Any = None,
) -> bool:
    if not isinstance(alert, dict) or snap is None:
        return False
    settings = settings or get_settings()
    sym = str(alert.get("symbol") or getattr(snap, "symbol", "") or "").upper()
    side_u = str(alert.get("side") or "").upper()
    if side_u not in ("CALL", "PUT"):
        return False
    armed, _, _ = nifty_expiry_flip_capture_armed(
        sym,
        side_u,
        snap,
        state=state,
        alert=alert,
        settings=settings,
    )
    return armed


def _nifty_expiry_afternoon_ist(now: Any = None) -> bool:
  from datetime import datetime
  from zoneinfo import ZoneInfo

  settings = get_settings()
  if not bool(getattr(settings, "nifty_expiry_afternoon_opposite_fade_suppress_enabled", True)):
    return False
  ist = ZoneInfo("Asia/Kolkata")
  when = now or datetime.now(ist)
  if when.tzinfo is None:
    when = when.replace(tzinfo=ist)
  else:
    when = when.astimezone(ist)
  hh = int(getattr(settings, "nifty_expiry_afternoon_opposite_fade_min_hour_ist", 11) or 11)
  mm = int(getattr(settings, "nifty_expiry_afternoon_opposite_fade_min_minute_ist", 45) or 45)
  start = when.replace(hour=hh, minute=mm, second=0, microsecond=0)
  return when >= start


def nifty_expiry_opposite_trend_fade_waiver_suppressed(
    symbol: str,
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    state: Any = None,
    settings: Any = None,
    now: Any = None,
) -> tuple[bool, str]:
    """
    On NIFTY expiry afternoon, suppress shallow premium-fade waivers when
    dominant index trend opposes the entry side (e.g. PUT into RALLY).
    """
    settings = settings or get_settings()
    sym = str(symbol or getattr(snap, "symbol", "") or "").upper()
    if sym != "NIFTY":
        return False, ""
    from app.engines.expiry_day_guards import is_symbol_expiry_day

    if not is_symbol_expiry_day(snap):
        return False, ""
    if not _nifty_expiry_afternoon_ist(now):
        return False, ""
    from app.engines.index_session_dominant_trend import (
        index_session_dominant_trend,
        index_trend_features_active,
        side_aligns_with_dominant_trend,
    )

    if not index_trend_features_active(settings):
        return False, ""
    dominant, meta = index_session_dominant_trend(
        sym, snap, state, settings=settings, track_flip=False,
    )
    side_u = _side_val(side)
    if side_aligns_with_dominant_trend(side_u, dominant):
        return False, ""
    if dominant == "NEUTRAL":
        return False, ""
    return True, f"nifty_expiry_afternoon_opposite_{dominant.lower()}"


def nifty_expiry_flip_cheap_otm_near_atm_bypass(
    candidate: Any,
    snap: SymbolSnapshot,
    alert: Mapping[str, Any] | None = None,
    *,
    state: Any = None,
    settings: Any = None,
) -> bool:
    """Flip-capture armed + shallow OTM only — not ₹17 deep cheap on expiry."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "nifty_expiry_flip_cheap_otm_near_atm_bypass_enabled", True)):
        return False
    sym = str(getattr(candidate, "symbol", "") or "").upper()
    if sym != "NIFTY" or snap is None:
        return False
    side_u = _side_val(getattr(candidate, "side", ""))
    alert_d = alert if isinstance(alert, Mapping) else {}
    if not alert_d and hasattr(candidate, "alert"):
        a = getattr(candidate, "alert", None)
        alert_d = dict(a) if isinstance(a, dict) else {}
    armed, _, _ = nifty_expiry_flip_capture_armed(
        sym,
        side_u,
        snap,
        state=state,
        alert=alert_d,
        explosion_event=getattr(candidate, "explosion_event", None),
        candidate=candidate,
        settings=settings,
    )
    if not armed:
        return False
    from app.engines.best_trade_policy import _classify_moneyness
    from app.engines.explosion_entry_guards import structured_near_atm
    from app.engines.moneyness import _depth_steps, atm_strike, classify_moneyness

    try:
        strike = float(getattr(candidate, "strike", 0) or alert_d.get("strike") or 0)
    except (TypeError, ValueError):
        strike = 0.0
    if strike <= 0:
        return False
    max_steps = int(
        getattr(settings, "nifty_expiry_flip_cheap_otm_max_otm_steps", 1) or 1
    )
    money = _classify_moneyness(candidate, snap)
    spot = float(getattr(snap, "spot", 0) or 0)
    sym_u = str(getattr(snap, "symbol", "") or sym).upper()
    atm = float(getattr(snap, "atmStrike", 0) or 0) or atm_strike(spot, sym_u)
    depth = _depth_steps(side_u, strike, spot, sym_u, atm)
    if money == "OTM" and depth > max_steps:
        return False
    return structured_near_atm(
        side_u,
        strike,
        snap,
        candidate=candidate,
        alert=alert_d,
        event=getattr(candidate, "explosion_event", None),
    )


def nifty_expiry_flip_premium_fade_bypass(
    *,
    side: Side | str,
    symbol: str,
    snap: SymbolSnapshot,
    state: Any = None,
    alert: Mapping[str, Any] | None = None,
    explosion_event: Any = None,
    settings: Any = None,
) -> bool:
    settings = settings or get_settings()
    if not bool(getattr(settings, "nifty_expiry_flip_capture_waive_exec_premium_fade", True)):
        return False
    suppressed, _ = nifty_expiry_opposite_trend_fade_waiver_suppressed(
        symbol, side, snap, state=state, settings=settings,
    )
    if suppressed:
        return False
    armed, _, _ = nifty_expiry_flip_capture_armed(
        symbol,
        side,
        snap,
        state=state,
        alert=alert,
        explosion_event=explosion_event,
        settings=settings,
    )
    return armed
