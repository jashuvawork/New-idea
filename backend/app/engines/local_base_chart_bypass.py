"""Local-base + Ichimoku chart bypass — gap-down session bias vs structure.

Gap-down mornings leave spotChart.direction BEARISH (mom15/mom30 still red),
which blocks every CALL as call_vs_bearish_chart. Local premium bases and
Ichimoku (cloud / TK) can already be bullish — allow CE/PE when those agree
with the trade side and a local premium base is confirmed.
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def _ichimoku_dict(snap: Optional[SymbolSnapshot]) -> dict[str, Any]:
    if snap is None:
        return {}
    analysis = getattr(snap, "chartAnalysis", None)
    if analysis is None:
        return {}
    ich = getattr(analysis, "ichimoku", None) or {}
    return ich if isinstance(ich, dict) else {}


def ichimoku_supports_side(side: Side | str, snap: Optional[SymbolSnapshot]) -> bool:
    """True when Ichimoku cloud/TK agrees with CALL→bullish or PUT→bearish."""
    settings = get_settings()
    ich = _ichimoku_dict(snap)
    if not ich:
        return False
    side_v = _side_val(side)
    target = "BULLISH" if side_v == "CALL" else "BEARISH"
    cloud = str(ich.get("cloudBias") or "NEUTRAL").upper()
    tk = str(ich.get("tkCross") or "NEUTRAL").upper()
    price_vs = str(ich.get("priceVsCloud") or "").upper()
    require_cloud = bool(getattr(settings, "local_base_ichimoku_require_cloud", True))
    if require_cloud:
        if cloud == target:
            return True
        # Price above/below cloud with TK agree — still counts as structure bias.
        if tk == target and (
            (target == "BULLISH" and price_vs == "ABOVE")
            or (target == "BEARISH" and price_vs == "BELOW")
        ):
            return True
        return False
    return cloud == target or tk == target


def _alert_has_local_base(alert: dict[str, Any]) -> bool:
    if alert.get("ictFlatThenVertical") or alert.get("localSwingBase"):
        return True
    if alert.get("ictBreakout") and float(alert.get("ictBaseRelativeMovePct") or 0) > 0:
        return True
    if str(alert.get("ictPattern") or "") in ("flat_then_vertical", "early_flat_break"):
        return True
    return False


def _alert_or_event_local_base(
    *,
    event: Any = None,
    alert: Optional[dict[str, Any]] = None,
    snap: Optional[SymbolSnapshot] = None,
) -> bool:
    """Local premium structure: flat→vertical, swing V-base, or ICT breakout base."""
    if isinstance(alert, dict) and _alert_has_local_base(alert):
        return True
    # Prefer radar alert fields when the live ICT recompute has no poll history yet.
    if event is not None and snap is not None:
        side_v = _side_val(getattr(event, "side", ""))
        strike = float(getattr(event, "strike", 0) or 0)
        for a in snap.explosionAlerts or []:
            if str(a.get("side") or "").upper() != side_v:
                continue
            if strike and abs(float(a.get("strike") or 0) - strike) > 0.1:
                continue
            if _alert_has_local_base(a):
                return True
    if event is not None:
        try:
            from app.engines.ict_breakout_monitor import analyze_explosion_event_ict

            ict = analyze_explosion_event_ict(event, snap)
            if bool(getattr(ict, "flat_then_vertical", False)):
                return True
            if bool(getattr(ict, "local_swing_base", False)):
                return True
            if float(getattr(ict, "base_relative_move_pct", 0) or 0) > 0 and bool(
                getattr(ict, "active", False)
            ):
                return True
        except Exception:
            pass
    return False


def session_chart_conflicts_side(side: Side | str, snap: Optional[SymbolSnapshot]) -> bool:
    chart = getattr(snap, "spotChart", None) if snap is not None else None
    if chart is None:
        return False
    direction = str(getattr(chart, "direction", None) or "NEUTRAL").upper()
    side_v = _side_val(side)
    if side_v == "CALL" and direction == "BEARISH":
        return True
    if side_v == "PUT" and direction == "BULLISH":
        return True
    return False


def local_base_ichimoku_chart_bypass(
    side: Side | str,
    snap: Optional[SymbolSnapshot],
    *,
    event: Any = None,
    alert: Optional[dict[str, Any]] = None,
) -> bool:
    """
    Lift gap-down (or gap-up) session chart hard-block when local structure agrees.

    Example: spotChart BEARISH after gap-down, but Ichimoku cloud bullish and the
    option is breaking a local premium base → allow CALL.
    """
    settings = get_settings()
    if not getattr(settings, "local_base_ichimoku_chart_bypass_enabled", True):
        return False
    if snap is None:
        return False
    if not session_chart_conflicts_side(side, snap):
        return False
    if not ichimoku_supports_side(side, snap):
        return False
    if not _alert_or_event_local_base(event=event, alert=alert, snap=snap):
        return False

    # Avoid bypassing while the index is still in a hard live dump against the side.
    chart = snap.spotChart
    side_v = _side_val(side)
    max_against = float(
        getattr(settings, "local_base_ichimoku_max_adverse_mom5_pct", 0.08) or 0.08
    )
    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0) if chart else 0.0
    if side_v == "CALL" and mom5 < -max_against:
        return False
    if side_v == "PUT" and mom5 > max_against:
        return False
    return True


def local_base_ichimoku_bypass_for_snap(
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    explosion_event: Any = None,
) -> bool:
    """Snap helper — also scans matching explosionAlerts when event is absent."""
    if local_base_ichimoku_chart_bypass(side, snap, event=explosion_event):
        return True
    side_v = _side_val(side)
    for alert in snap.explosionAlerts or []:
        if str(alert.get("side") or "").upper() != side_v:
            continue
        if local_base_ichimoku_chart_bypass(side, snap, event=explosion_event, alert=alert):
            return True
    return False
