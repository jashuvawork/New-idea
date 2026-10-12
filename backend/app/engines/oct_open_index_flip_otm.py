"""Open-window index flip (CALL rally / PUT slide) — OTM depth + entry-window floor relief.

Oct 12 2026 RCA: ELITE PUT rips at 9:15 were blocked as shallow OTM (22550/22500)
despite index slide; SENSEX 72700 hit entry_window_local_low_4%. Mirrors CE rally off
session low for PUT slide off session high when Frozen Oct paper rules are active.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.models.schemas import Side, SymbolSnapshot


def _side_u(side: Any) -> str:
    if hasattr(side, "value"):
        return str(side.value or "").upper()
    return str(side or "").upper()


def _in_open_premium_window() -> bool:
    try:
        from app.engines.session_timing import in_open_premium_window

        return bool(in_open_premium_window())
    except Exception:
        return False


def _oct_open_flip_active(settings: Any) -> bool:
    from app.engines.live_paper_parity import trading_rules_match_paper

    if not trading_rules_match_paper(settings):
        return False
    if not bool(getattr(settings, "oct_paper_open_moment_pad_waiver_enabled", True)):
        return False
    return _in_open_premium_window()


def index_flip_bypass_for_alert(
    alert: Mapping[str, Any],
    snap: Optional[SymbolSnapshot],
    *,
    settings: Any = None,
) -> tuple[bool, str]:
    """True when index rally (CALL) or slide (PUT) bypass fires for this symbol."""
    from app.config import get_settings
    from app.engines.index_rally_side_flip import index_rally_side_flip_bypass

    settings = settings or get_settings()
    if snap is None or not isinstance(alert, dict):
        return False, ""
    side = _side_u(alert.get("side"))
    if side not in ("CALL", "PUT"):
        return False, ""
    symbol = str(alert.get("symbol") or getattr(snap, "symbol", "") or "").upper()
    if not symbol:
        return False, ""
    ok, reason, _metrics = index_rally_side_flip_bypass(
        symbol,
        Side(side),
        snap,
        settings=settings,
    )
    return ok, reason or ""


def open_index_flip_structural_open_rip(alert: Mapping[str, Any]) -> bool:
    from app.engines.open_rip_selector import open_rip_elite_structural_evidence

    return open_rip_elite_structural_evidence(alert)


def oct_open_index_flip_otm_entry_ok(
    alert: Mapping[str, Any],
    snap: Optional[SymbolSnapshot],
    *,
    settings: Any = None,
) -> bool:
    """
    Allow shallow OTM (up to configured steps) on open index-flip rips under Frozen Oct.

    Does not enable lottery deep OTM; depth capped by oct_open_index_flip_max_otm_steps.
    """
    from app.config import get_settings
    from app.engines.moneyness import _depth_steps, classify_moneyness

    settings = settings or get_settings()
    if not _oct_open_flip_active(settings):
        return False
    if not isinstance(alert, dict) or snap is None:
        return False
    side = _side_u(alert.get("side"))
    if side not in ("CALL", "PUT"):
        return False
    tier = str(alert.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return False
    if not open_index_flip_structural_open_rip(alert):
        return False
    flip_ok, _ = index_flip_bypass_for_alert(alert, snap, settings=settings)
    if not flip_ok:
        return False
    try:
        strike = float(alert.get("strike") or 0)
    except (TypeError, ValueError):
        return False
    spot = float(getattr(snap, "spot", 0) or 0)
    atm = float(getattr(snap, "atmStrike", 0) or 0) or spot
    symbol = str(alert.get("symbol") or getattr(snap, "symbol", "") or "").upper()
    if strike <= 0 or spot <= 0:
        return False
    money = classify_moneyness(
        Side(side), strike, spot, symbol=symbol, atm=atm if atm > 0 else None,
    )
    if money != "OTM":
        return True
    max_steps = int(getattr(settings, "oct_open_index_flip_max_otm_steps", 2) or 2)
    depth = _depth_steps(Side(side), strike, spot, symbol, atm if atm > 0 else spot)
    return depth <= max_steps


def oct_open_index_flip_entry_window_lo_relax(
    alert: Mapping[str, Any],
    snap: Optional[SymbolSnapshot],
    explosion_event: Any,
    *,
    default_lo: float,
    settings: Any = None,
) -> float:
    """Lower entry-window floor for early open index-flip pads (e.g. 4% on SENSEX slide)."""
    settings = settings or get_settings()
    if not _oct_open_flip_active(settings):
        return default_lo
    if not isinstance(alert, dict) or snap is None or explosion_event is None:
        return default_lo
    tier = str(getattr(explosion_event, "tier", "") or alert.get("tier") or "").upper()
    if tier not in ("ELITE", "EXPLODING"):
        return default_lo
    if not open_index_flip_structural_open_rip(alert):
        return default_lo
    flip_ok, _ = index_flip_bypass_for_alert(alert, snap, settings=settings)
    if not flip_ok:
        return default_lo
    floor = float(getattr(settings, "oct_open_index_flip_min_pad_pct", 3.0) or 3.0)
    return min(default_lo, max(0.0, floor))
