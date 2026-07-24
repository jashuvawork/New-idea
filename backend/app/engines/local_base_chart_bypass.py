"""Local-base overrides session chart + sibling side/bias blocks.

Gap-down mornings leave spotChart.direction / breadth BEARISH, which
blanket-blocks every CALL. Jul24 NIFTY 23700 CE was EXPLODING ~98 off a ~110
local base and still died on call_vs_bearish_chart /
explosion_call_vs_bearish_breadth / market_opposes_side.

Policy: a confirmed LOCAL PREMIUM BASE lifts session chart, explosion breadth,
market-opposes, directional confirmation, and bad-day/worst-day alignment
gates. Ichimoku agreement is optional confirmation, not a gate.
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
    require_cloud = bool(getattr(settings, "local_base_ichimoku_require_cloud", False))
    if require_cloud:
        if cloud == target:
            return True
        if tk == target and (
            (target == "BULLISH" and price_vs == "ABOVE")
            or (target == "BEARISH" and price_vs == "BELOW")
        ):
            return True
        return False
    return cloud == target or tk == target


def _alert_session_move(alert: dict[str, Any]) -> float:
    return max(
        float(alert.get("dailyMovePct") or alert.get("openPremiumMove") or 0),
        float(alert.get("peakMovePct") or 0),
        float(alert.get("ictBaseRelativeMovePct") or 0),
    )


def _alert_has_local_base(alert: dict[str, Any]) -> bool:
    """Local premium launch pad — ICT structure OR strong early-window explosion."""
    settings = get_settings()
    if alert.get("ictFlatThenVertical") or alert.get("localSwingBase"):
        return True
    if alert.get("ictBreakout") and float(alert.get("ictBaseRelativeMovePct") or 0) > 0:
        return True
    if str(alert.get("ictPattern") or "") in (
        "flat_then_vertical", "early_flat_break", "local_swing_base",
    ):
        return True
    # Base-relative already measured in the tradeable local window.
    base_rel = float(alert.get("ictBaseRelativeMovePct") or 0)
    local_max = float(
        getattr(settings, "explosion_local_base_chase_max_move_pct", 70.0) or 70.0
    )
    if 0 < base_rel < local_max:
        return True
    # Jul24 23700 CE: EXPLODING/ELITE on radar with early-window move after a
    # gap-down — ICT flags sometimes lag one poll; tier+score+move is enough.
    tier = str(alert.get("tier") or "").upper()
    score = float(alert.get("explosionScore") or 0)
    move = _alert_session_move(alert)
    min_score = float(
        getattr(settings, "local_base_chart_bypass_min_score", 38.0) or 38.0
    )
    early_min = float(
        getattr(settings, "explosion_local_base_entry_min_move_pct", 28.0) or 28.0
    )
    if (
        tier in ("EXPLODING", "ELITE")
        and score >= min_score
        and early_min <= move <= local_max
    ):
        return True
    if (
        tier == "BUILDING"
        and score >= min_score
        and (
            bool(alert.get("volumeAwaken"))
            or bool(alert.get("ictVolumeAwakening"))
            or float(alert.get("velocity3s") or 0) >= 2.0
        )
        and move >= early_min * 0.5
        and move <= local_max
    ):
        return True
    return False


def _alert_or_event_local_base(
    *,
    side: Side | str = "",
    event: Any = None,
    alert: Optional[dict[str, Any]] = None,
    snap: Optional[SymbolSnapshot] = None,
) -> bool:
    """Local premium structure: flat→vertical, swing V-base, or early EXPLODING rip."""
    if isinstance(alert, dict) and _alert_has_local_base(alert):
        return True
    side_v = _side_val(side) if side else ""
    if not side_v and event is not None:
        side_v = _side_val(getattr(event, "side", ""))
    # Scan live radar alerts even when event is absent (directional lock / hard block).
    if snap is not None and side_v:
        strike = float(getattr(event, "strike", 0) or 0) if event is not None else 0.0
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
        # Event-only fallback (same as alert early-window EXPLODING path).
        settings = get_settings()
        tier = str(getattr(event, "tier", "") or "").upper()
        score = float(getattr(event, "explosion_score", 0) or 0)
        move = max(
            float(getattr(event, "daily_move_pct", 0) or 0),
            float(getattr(event, "peak_move_pct", 0) or 0),
        )
        min_score = float(
            getattr(settings, "local_base_chart_bypass_min_score", 38.0) or 38.0
        )
        early_min = float(
            getattr(settings, "explosion_local_base_entry_min_move_pct", 28.0) or 28.0
        )
        local_max = float(
            getattr(settings, "explosion_local_base_chase_max_move_pct", 70.0) or 70.0
        )
        if (
            tier in ("EXPLODING", "ELITE")
            and score >= min_score
            and early_min <= move <= local_max
        ):
            return True
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


def local_base_structure_active(
    side: Side | str,
    snap: Optional[SymbolSnapshot],
    *,
    event: Any = None,
    alert: Optional[dict[str, Any]] = None,
) -> bool:
    """True when a local premium base / early EXPLODING rip is confirmed for side."""
    settings = get_settings()
    if not getattr(settings, "local_base_overrides_session_chart_enabled", True):
        if not getattr(settings, "local_base_ichimoku_chart_bypass_enabled", True):
            return False
    if snap is None:
        return False
    if not _alert_or_event_local_base(side=side, event=event, alert=alert, snap=snap):
        return False
    if getattr(settings, "local_base_chart_bypass_require_ichimoku", False):
        if not ichimoku_supports_side(side, snap):
            return False
    chart = snap.spotChart
    side_v = _side_val(side)
    max_against = float(
        getattr(settings, "local_base_ichimoku_max_adverse_mom5_pct", 0.12) or 0.12
    )
    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0) if chart else 0.0
    if side_v == "CALL" and mom5 < -max_against:
        return False
    if side_v == "PUT" and mom5 > max_against:
        return False
    return True


def local_base_overrides_side_bias(
    side: Side | str,
    snap: Optional[SymbolSnapshot],
    *,
    event: Any = None,
    alert: Optional[dict[str, Any]] = None,
) -> bool:
    """
    Lift session breadth / market-opposes / directional / bad-day / worst-day
    side blocks when a local premium base is confirmed.

    Same structure gate as chart bypass; gated by local_base_overrides_bearish_breadth
    (name kept for config compat — covers CALL-vs-bearish and PUT-vs-bullish alike).
    """
    settings = get_settings()
    if not getattr(settings, "local_base_overrides_bearish_breadth", True):
        return False
    return local_base_structure_active(side, snap, event=event, alert=alert)


def local_base_overrides_session_chart(
    side: Side | str,
    snap: Optional[SymbolSnapshot],
    *,
    event: Any = None,
    alert: Optional[dict[str, Any]] = None,
) -> bool:
    """
    Lift call_vs_bearish / put_vs_bullish when a local premium base is confirmed.

    Ichimoku is optional. Primary signal = local base / early-window EXPLODING rip.
    """
    if not session_chart_conflicts_side(side, snap):
        return False
    return local_base_structure_active(side, snap, event=event, alert=alert)


# Backward-compatible names used across the codebase.
def local_base_ichimoku_chart_bypass(
    side: Side | str,
    snap: Optional[SymbolSnapshot],
    *,
    event: Any = None,
    alert: Optional[dict[str, Any]] = None,
) -> bool:
    return local_base_overrides_session_chart(
        side, snap, event=event, alert=alert,
    )


def local_base_ichimoku_bypass_for_snap(
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    explosion_event: Any = None,
) -> bool:
    """Snap helper — also scans matching explosionAlerts when event is absent."""
    if local_base_overrides_session_chart(side, snap, event=explosion_event):
        return True
    side_v = _side_val(side)
    for alert in snap.explosionAlerts or []:
        if str(alert.get("side") or "").upper() != side_v:
            continue
        if local_base_overrides_session_chart(
            side, snap, event=explosion_event, alert=alert,
        ):
            return True
    return False
