"""Hard block counter-breadth entries when stock breadth is directional."""

from __future__ import annotations

from typing import Any, Optional

from app.config import get_settings
from app.models.schemas import Side, SymbolSnapshot


def _side_val(side: Side | str) -> str:
    return side.value if isinstance(side, Side) else str(side).upper()


def _resolve_snap(
    snap: Optional[SymbolSnapshot] = None,
    *,
    candidate: Any = None,
) -> Optional[SymbolSnapshot]:
    if snap is not None:
        return snap
    if candidate is not None:
        cand_snap = getattr(candidate, "snap", None)
        if cand_snap is not None:
            return cand_snap
    return None


def _explosion_score(
    *,
    event: Any = None,
    candidate: Any = None,
    alert: Any = None,
) -> float:
    if event is not None:
        return float(
            getattr(event, "explosion_score", 0)
            or getattr(event, "score", 0)
            or 0,
        )
    if candidate is not None:
        return float(getattr(candidate, "score", 0) or 0)
    if isinstance(alert, dict):
        return float(alert.get("explosionScore") or alert.get("score") or 0)
    return 0.0


def chart_mtf_read(snap: Optional[SymbolSnapshot]) -> tuple[str, str, int, int]:
    """Return spot_chart_direction, mtf_consensus, aligned_count, total_timeframes."""
    if not snap:
        return "NEUTRAL", "NEUTRAL", 0, 0
    chart_dir = "NEUTRAL"
    if snap.spotChart and snap.spotChart.direction:
        chart_dir = str(snap.spotChart.direction).upper()
    analysis = snap.chartAnalysis
    if not analysis:
        return chart_dir, "NEUTRAL", 0, 0
    consensus = str(analysis.consensus or "NEUTRAL").upper()
    return (
        chart_dir,
        consensus,
        int(analysis.alignedCount or 0),
        int(analysis.totalTimeframes or 0),
    )


def chart_mtf_bullish_confirmed(snap: Optional[SymbolSnapshot]) -> bool:
    """spotChart + MTF both bullish — breadth OI can lag a live index rally."""
    settings = get_settings()
    if not settings.chart_mtf_breadth_bypass_enabled or not snap or not snap.spotChart:
        return False

    chart_dir, consensus, aligned, total = chart_mtf_read(snap)
    if chart_dir != "BULLISH" or consensus != "BULLISH":
        return False

    min_aligned = settings.chart_mtf_breadth_bypass_min_aligned
    if total > 0 and aligned < min_aligned:
        return False

    if total == 0 and snap.chartAnalysis:
        ich = snap.chartAnalysis.ichimoku or {}
        cloud = str(ich.get("cloudBias") or "NEUTRAL").upper()
        price_vs = str(ich.get("priceVsCloud") or "NEUTRAL").upper()
        if cloud != "BULLISH" or price_vs not in ("ABOVE", "INSIDE"):
            return False

    rsi = float(snap.spotChart.rsi or 50)
    macd = str(snap.spotChart.macdBias or "NEUTRAL").upper()
    if rsi < settings.chart_mtf_breadth_bypass_min_rsi:
        return False
    if macd == "BEARISH":
        return False
    return True


def chart_mtf_bearish_confirmed(snap: Optional[SymbolSnapshot]) -> bool:
    """spotChart + MTF both bearish — symmetric bypass for PUT vs bullish breadth."""
    settings = get_settings()
    if not settings.chart_mtf_breadth_bypass_enabled or not snap or not snap.spotChart:
        return False

    chart_dir, consensus, aligned, total = chart_mtf_read(snap)
    if chart_dir != "BEARISH" or consensus != "BEARISH":
        return False

    min_aligned = settings.chart_mtf_breadth_bypass_min_aligned
    if total > 0 and aligned < min_aligned:
        return False

    if total == 0 and snap.chartAnalysis:
        ich = snap.chartAnalysis.ichimoku or {}
        cloud = str(ich.get("cloudBias") or "NEUTRAL").upper()
        price_vs = str(ich.get("priceVsCloud") or "NEUTRAL").upper()
        if cloud != "BEARISH" or price_vs not in ("BELOW", "INSIDE"):
            return False

    rsi = float(snap.spotChart.rsi or 50)
    macd = str(snap.spotChart.macdBias or "NEUTRAL").upper()
    if rsi > (100 - settings.chart_mtf_breadth_bypass_min_rsi):
        return False
    if macd == "BULLISH":
        return False
    return True


def chart_mtf_breadth_bypass_active(
    side: Side | str,
    breadth_bias: str,
    snap: Optional[SymbolSnapshot],
    *,
    score: float = 0.0,
) -> tuple[bool, str]:
    """True when chart+MTF override stale option-chain breadth for this side."""
    settings = get_settings()
    if not settings.chart_mtf_breadth_bypass_enabled or not snap:
        return False, ""

    side_v = _side_val(side)
    bias = (breadth_bias or "NEUTRAL").upper()
    min_score = settings.chart_mtf_breadth_bypass_min_explosion_score
    if score < min_score:
        return False, ""

    if bias == "BEARISH" and side_v == "CALL" and chart_mtf_bullish_confirmed(snap):
        return True, "chart_mtf_bullish_bypass_bearish_breadth"
    if bias == "BULLISH" and side_v == "PUT" and chart_mtf_bearish_confirmed(snap):
        return True, "chart_mtf_bearish_bypass_bullish_breadth"
    return False, ""


def _live_chart_supports_put(snap: Optional[SymbolSnapshot]) -> bool:
    """Live index dump — OI breadth can lag; allow PE when 5m chart is bearish."""
    if not snap or not snap.spotChart:
        return False
    chart = snap.spotChart
    if str(chart.direction or "").upper() != "BEARISH":
        return False
    mom = float(chart.momentum5Pct or 0)
    trend = float(chart.trendStrength or 0)
    return mom <= -0.06 or trend >= 15.0


def breadth_hard_blocks_side(
    side: Side | str,
    breadth_bias: str,
    *,
    event: Any = None,
    candidate: Any = None,
    alert: Any = None,
    snap: Optional[SymbolSnapshot] = None,
    state: Any = None,
) -> tuple[bool, str]:
    """
    No PUT on BULLISH breadth, no CALL on BEARISH breadth.
    Extreme ELITE session rips (100%+) bypass via extreme_explosion_moment.
    Chart+MTF alignment can bypass when option-chain OI breadth lags live price.
    """
    from app.engines.extreme_explosion_moment import is_extreme_explosion_all_in_bypass

    if is_extreme_explosion_all_in_bypass(event=event, candidate=candidate, alert=alert):
        return False, "ok"

    settings = get_settings()
    if not settings.breadth_hard_side_block_enabled:
        return False, "ok"

    resolved_snap = _resolve_snap(snap, candidate=candidate)

    from app.engines.vertical_rip_bypass import vertical_rip_bypasses_hard_breadth

    if vertical_rip_bypasses_hard_breadth(
        side,
        breadth_bias,
        event=event or getattr(candidate, "explosion_event", None) or candidate,
        snap=resolved_snap,
    ):
        return False, "ok"

    score = _explosion_score(event=event, candidate=candidate, alert=alert)
    bypassed, _ = chart_mtf_breadth_bypass_active(
        side, breadth_bias, resolved_snap, score=score,
    )
    if bypassed:
        return False, "ok"

    bias = (breadth_bias or "NEUTRAL").upper()
    if bias == "NEUTRAL":
        return False, "ok"
    side_v = _side_val(side)
    # Local premium base rip (Jul24 23700 CE) — gap-down breadth stays BEARISH while
    # the option is breaking its own base; do not hard-block that structure.
    if resolved_snap is not None:
        from app.engines.local_base_chart_bypass import local_base_overrides_side_bias

        ev = event or getattr(candidate, "explosion_event", None)
        resolved_alert = alert if isinstance(alert, dict) else None
        if resolved_alert is None and candidate is not None:
            ca = getattr(candidate, "alert", None)
            if isinstance(ca, dict):
                resolved_alert = ca
        if local_base_overrides_side_bias(
            side_v, resolved_snap, event=ev, alert=resolved_alert,
        ):
            return False, "ok"
        from app.engines.index_confirmed_local_base import index_confirmed_local_base

        if index_confirmed_local_base(side_v, resolved_snap, resolved_alert):
            return False, "ok"
    if bias == "BULLISH" and side_v == "PUT":
        if _live_chart_supports_put(resolved_snap):
            return False, "ok"
        if resolved_snap is not None:
            from app.engines.index_rally_side_flip import index_rally_side_flip_bypass

            sym = str(getattr(resolved_snap, "symbol", "") or "")
            slide_ok, _, _ = index_rally_side_flip_bypass(sym, side_v, resolved_snap)
            if slide_ok:
                return False, "ok"
        return True, "hard_block_put_vs_bullish_breadth"
    if bias == "BEARISH" and side_v == "CALL":
        if resolved_snap is not None:
            from app.engines.index_rally_side_flip import index_rally_side_flip_bypass

            sym = str(getattr(resolved_snap, "symbol", "") or "")
            rally_ok, _, _ = index_rally_side_flip_bypass(sym, side_v, resolved_snap)
            if rally_ok:
                return False, "ok"
        if (
            candidate is not None
            and bool(
                getattr(settings, "elite_call_pe_parity_bypass_bearish_breadth_enabled", True)
            )
        ):
            from app.engines.best_trade_policy import call_pe_parity_from_candidate

            if call_pe_parity_from_candidate(
                candidate, resolved_snap, settings=settings, state=state,
            ):
                return False, "ok"
        return True, "hard_block_call_vs_bearish_breadth"
    return False, "ok"


def counter_breadth_side_blocked(side: Side | str, breadth_bias: str) -> bool:
    blocked, _ = breadth_hard_blocks_side(side, breadth_bias)
    return blocked


_CHOP_SIDE_ALIGNMENT_DAY_MODES = frozenset({
    "CHOP DAY",
    "CHOP (PRE-10)",
    "CHOP + RALLY",
})


def _chop_day_local_base_structural_bypass(
    side: Side | str,
    snap: SymbolSnapshot,
    *,
    alert: Any = None,
    event: Any = None,
    settings: Any = None,
) -> bool:
    """Narrow chop waiver — confirmed local-base lift at low pad only (not score-chase)."""
    settings = settings or get_settings()
    side_v = _side_val(side)
    alert_d = alert if isinstance(alert, dict) else {}
    if event is not None and not alert_d:
        alert_d = {
            "side": side_v,
            "tier": str(getattr(event, "tier", "") or ""),
            "localBaseMovePct": float(getattr(event, "daily_move_pct", 0) or 0),
            "ictBaseRelativeMovePct": float(getattr(event, "daily_move_pct", 0) or 0),
        }
    local = 0.0
    for key in ("ictBaseRelativeMovePct", "localBaseMovePct", "offLowMovePct"):
        try:
            local = max(local, float(alert_d.get(key) or 0))
        except (TypeError, ValueError):
            pass
    max_local = float(getattr(settings, "pe_win_ce_mirror_max_local_pct", 15.0) or 15.0)
    if local <= 0 or local > max_local + 1e-6:
        return False
    from app.engines.local_base_chart_bypass import local_base_ichimoku_chart_bypass

    return local_base_ichimoku_chart_bypass(side_v, snap, alert=alert_d)


def chop_day_side_alignment_blocks(
    side: Side | str,
    snap: Optional[SymbolSnapshot],
    *,
    day_mode: str = "",
    must_take: bool = False,
    alert: Any = None,
    event: Any = None,
    state: Any = None,
    readiness_reason: str = "",
    settings: Any = None,
) -> tuple[bool, str]:
    """
    Chop days — structural side alignment is the primary trade filter.

    Blocks counter-chart / counter-breadth legs (Sep21 PUT 23350 vs BULLISH day).
    Selection score alone must not override alignment on chop sessions.
    """
    settings = settings or get_settings()
    if not bool(getattr(settings, "chop_day_require_side_alignment_enabled", True)):
        return False, ""
    dm = str(day_mode or "").strip().upper()
    if dm not in _CHOP_SIDE_ALIGNMENT_DAY_MODES:
        return False, ""
    if must_take:
        return False, ""
    if snap is None:
        return False, ""

    side_v = _side_val(side)
    alert_d = alert if isinstance(alert, dict) else {}

    # CHOP+RALLY CE with index rally / premium local-base — aligned structural side at base.
    if side_v == "CALL" and dm == "CHOP + RALLY" and state is not None:
        local = 0.0
        for key in ("ictBaseRelativeMovePct", "localBaseMovePct", "offLowMovePct"):
            try:
                local = max(local, float(alert_d.get(key) or 0))
            except (TypeError, ValueError):
                pass
        max_local = float(getattr(settings, "pe_win_ce_mirror_max_local_pct", 15.0) or 15.0)
        if local > 0 and local <= max_local + 1e-6:
            from app.engines.pe_win_ce_mirror import call_ce_base_context_armed

            sym = str(alert_d.get("symbol") or getattr(snap, "symbol", "") or "").upper()
            armed, _, _ = call_ce_base_context_armed(
                state,
                snap,
                sym,
                alert_d,
                readiness_reason=readiness_reason,
                settings=settings,
            )
            if armed:
                return False, ""

    chart = snap.spotChart
    bias = (snap.breadth.bias if snap.breadth else "NEUTRAL") or "NEUTRAL"

    from app.engines.spot_direction import hard_counter_trend_chart, side_aligned_with_chart

    if hard_counter_trend_chart(side_v, chart):
        if _chop_day_local_base_structural_bypass(
            side_v, snap, alert=alert_d, event=event, settings=settings,
        ):
            return False, ""
        return True, "chop_day_counter_chart"

    if not side_aligned_with_chart(side_v, chart):
        if _chop_day_local_base_structural_bypass(
            side_v, snap, alert=alert_d, event=event, settings=settings,
        ):
            return False, ""
        return True, "chop_day_chart_not_aligned"

    hard_blocked, hard_reason = breadth_hard_blocks_side(
        side_v,
        bias,
        event=event,
        snap=snap,
        alert=alert_d if alert_d else None,
        state=state,
    )
    if hard_blocked:
        return True, hard_reason or "chop_day_counter_breadth"

    return False, ""
