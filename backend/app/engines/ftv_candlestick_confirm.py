"""Index candlestick pattern confirmation for FTV / V-moment entries.

Named patterns from ``chart_advanced_analysis`` (engulfing, marubozu, pin bar,
morning/evening star, soldiers/crows) confirm the index turn that premium FTV/V
structure is already printing. Used to:

- bypass session chart-align blocks when the 5m label lags but a reversal pattern
  agrees with the option side;
- count as index alignment for grade-A FTV capture;
- nudge selector rank when pattern + flat→vertical / V-rip align.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from app.config import get_settings
from app.engines.chart_exit_levels import _pattern_side
from app.models.schemas import Side, SymbolSnapshot


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side or "").upper()


def _alert_dict(alert: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    return dict(alert) if isinstance(alert, Mapping) else {}


def _chart_patterns(snap: Optional[SymbolSnapshot]) -> list[dict[str, Any]]:
    if snap is None:
        return []
    analysis = getattr(snap, "chartAnalysis", None)
    if analysis is None:
        return []
    patterns = getattr(analysis, "patterns", None) or []
    return [p for p in patterns if isinstance(p, dict)]


def aligned_candlestick_patterns(
    side: Side | str,
    snap: Optional[SymbolSnapshot],
    *,
    min_strength: float | None = None,
) -> list[dict[str, Any]]:
    """Index patterns whose bias matches CALL/PUT."""
    settings = get_settings()
    if not bool(getattr(settings, "ftv_candlestick_confirm_enabled", True)):
        return []
    side_v = _side_val(side)
    if side_v not in ("CALL", "PUT"):
        return []
    floor = float(
        min_strength
        if min_strength is not None
        else getattr(settings, "ftv_candlestick_min_pattern_strength", 68.0) or 68.0
    )
    out: list[dict[str, Any]] = []
    for pat in _chart_patterns(snap):
        name = str(pat.get("name") or "")
        p_side = _pattern_side(name)
        if p_side != side_v:
            continue
        strength = float(pat.get("strength") or 0)
        if strength < floor:
            continue
        out.append(pat)
    return sorted(out, key=lambda p: float(p.get("strength") or 0), reverse=True)


def best_aligned_pattern_strength(
    side: Side | str,
    snap: Optional[SymbolSnapshot],
) -> float:
    patterns = aligned_candlestick_patterns(side, snap)
    if not patterns:
        return 0.0
    return float(patterns[0].get("strength") or 0)


def alert_has_ftv_v_structure(alert: Mapping[str, Any]) -> bool:
    """Premium tape shows flat→vertical or V-rip structure."""
    if bool(alert.get("ictVRipReady") or alert.get("vRipReady")):
        return True
    if bool(alert.get("ictFlatThenVertical")):
        if bool(
            alert.get("ictBreakout")
            or alert.get("ictFirstLift")
            or alert.get("ictActive")
            or alert.get("ictArmedBaseLaunch")
            or alert.get("ictBaseArmed")
        ):
            return True
        quality = float(alert.get("flatVerticalQuality") or 0)
        min_q = float(
            getattr(get_settings(), "ftv_candlestick_min_flat_vertical_quality", 50.0)
            or 50.0
        )
        if quality >= min_q:
            return True
    from app.engines.top_ftv_v_expiry_bypass import alert_evidence
    from app.engines.top_moment_gate import classify_top_moment_type

    moment = classify_top_moment_type(alert_evidence(alert))
    return moment in ("FTV", "V")


def _live_momentum_ok(side: Side | str, snap: Optional[SymbolSnapshot]) -> bool:
    chart = getattr(snap, "spotChart", None) if snap is not None else None
    if chart is None:
        return True
    settings = get_settings()
    max_against = float(
        getattr(settings, "ftv_candlestick_max_adverse_mom5_pct", 0.08) or 0.08
    )
    mom5 = float(getattr(chart, "momentum5Pct", 0) or 0)
    side_v = _side_val(side)
    if side_v == "CALL" and mom5 < -max_against:
        return False
    if side_v == "PUT" and mom5 > max_against:
        return False
    return True


def ftv_candlestick_pattern_confirms(
    side: Side | str,
    snap: Optional[SymbolSnapshot],
    *,
    alert: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Aligned index candlestick pattern with optional FTV/V premium structure."""
    settings = get_settings()
    if not bool(getattr(settings, "ftv_candlestick_confirm_enabled", True)):
        return False
    if not aligned_candlestick_patterns(side, snap):
        return False
    if bool(getattr(settings, "ftv_candlestick_require_ftv_structure", True)):
        merged = _alert_dict(alert)
        if merged and not alert_has_ftv_v_structure(merged):
            return False
    return True


def ftv_candlestick_chart_bypass(
    side: Side | str,
    snap: Optional[SymbolSnapshot],
    *,
    alert: Optional[Mapping[str, Any]] = None,
    event: Any = None,
) -> bool:
    """Lift chart-align block when index reversal pattern confirms FTV/V premium."""
    settings = get_settings()
    if not bool(getattr(settings, "ftv_candlestick_chart_bypass_enabled", True)):
        return False
    if snap is None:
        return False
    merged = _alert_dict(alert)
    if not merged and event is not None:
        merged = {
            "side": _side_val(side),
            "tier": str(getattr(event, "tier", "") or ""),
            "explosionScore": float(getattr(event, "explosion_score", 0) or 0),
            "ictFlatThenVertical": bool(getattr(event, "flat_then_vertical", False)),
            "ictVRipReady": bool(getattr(event, "v_rip_ready", False)),
            "ictBreakout": bool(getattr(event, "active", False)),
            "ictFirstLift": bool(getattr(event, "first_lift", False)),
            "flatVerticalQuality": float(getattr(event, "flat_vertical_quality", 0) or 0),
        }
    if not ftv_candlestick_pattern_confirms(side, snap, alert=merged or None):
        return False
    if not _live_momentum_ok(side, snap):
        return False
    from app.engines.local_base_chart_bypass import session_chart_conflicts_side
    from app.engines.spot_direction import side_aligned_with_chart

    chart = getattr(snap, "spotChart", None)
    if chart is None:
        return False
    # Only bypass when session chart label hasn't caught up yet.
    if side_aligned_with_chart(side, chart):
        return False
    if not session_chart_conflicts_side(side, snap):
        return False
    min_score = float(
        getattr(settings, "ftv_candlestick_chart_bypass_min_score", 25.0) or 25.0
    )
    score = float(merged.get("explosionScore") or merged.get("score") or 0)
    if event is not None and score <= 0:
        score = float(getattr(event, "explosion_score", 0) or 0)
    if score < min_score:
        return False
    return True


def ftv_candlestick_bypass_for_snap(
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    explosion_event: Any = None,
    alert: Optional[dict[str, Any]] = None,
) -> bool:
    """Pretrade helper — scan matching alerts when event is absent."""
    if ftv_candlestick_chart_bypass(
        side, snap, alert=alert, event=explosion_event,
    ):
        return True
    side_v = _side_val(side)
    for row in snap.explosionAlerts or []:
        if str(row.get("side") or "").upper() != side_v:
            continue
        if ftv_candlestick_chart_bypass(
            side, snap, alert=row, event=explosion_event,
        ):
            return True
    return False


def ftv_candlestick_index_aligned(
    alert: Mapping[str, Any],
    snap: Optional[SymbolSnapshot],
) -> bool:
    """Pattern-based index alignment for grade-A FTV when candleBias lags."""
    side = str(alert.get("side") or "").upper()
    if side not in ("CALL", "PUT"):
        return False
    if not alert_has_ftv_v_structure(alert):
        return False
    return ftv_candlestick_pattern_confirms(side, snap, alert=alert)


def ftv_candlestick_rank_bonus(
    snap: Optional[SymbolSnapshot],
    alert: Mapping[str, Any],
    side: Side | str,
) -> float:
    """Selector rank nudge when index pattern confirms premium FTV/V."""
    settings = get_settings()
    if not bool(getattr(settings, "ftv_candlestick_rank_bonus_enabled", True)):
        return 0.0
    if not alert_has_ftv_v_structure(alert):
        return 0.0
    strength = best_aligned_pattern_strength(side, snap)
    if strength <= 0:
        return 0.0
    cap = float(getattr(settings, "ftv_candlestick_rank_bonus_max", 10.0) or 10.0)
    # Scale 68–82 strength → partial..full bonus.
    scaled = cap * max(0.0, min(1.0, (strength - 65.0) / 17.0))
    return round(scaled, 2)
