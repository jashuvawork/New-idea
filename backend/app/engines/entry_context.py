"""Entry/exit trade context — persist chart + MTF snapshot for audits and replay."""

from __future__ import annotations

from typing import Any, Optional

from app.engines.spot_direction import chart_summary_dict
from app.models.schemas import Side, SymbolSnapshot


def snapshot_chart_context(snap: Optional[SymbolSnapshot]) -> dict[str, Any]:
    """Compact chart + breadth + MTF read for entryContext (audit / milestone review)."""
    if not snap:
        return {}

    out: dict[str, Any] = {}
    if snap.spot is not None:
        out["spotAtEntry"] = round(float(snap.spot), 2)

    if snap.spotChart:
        chart = chart_summary_dict(snap.spotChart)
        out["spotChart"] = chart
        out["indexChart"] = chart

    if snap.chartAnalysis:
        ca = snap.chartAnalysis
        out["chartAnalysis"] = {
            "consensus": ca.consensus,
            "alignedCount": ca.alignedCount,
            "totalTimeframes": ca.totalTimeframes,
            "ichimoku": ca.ichimoku or {},
            "keySignals": (ca.keySignals or [])[:8],
        }

    if snap.breadth:
        out["breadth"] = {
            "bias": snap.breadth.bias,
            "score": snap.breadth.score,
            "aligned": snap.breadth.aligned,
            "source": getattr(snap.breadth, "source", None),
        }

    return out


def merge_execution_chart_context(
    base: dict[str, Any],
    execution_chart: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Prefer live execution-chart read over snapshot when gate ran."""
    if not execution_chart or not execution_chart.get("enabled"):
        return base
    out = dict(base)
    if execution_chart.get("indexChart"):
        out["indexChart"] = execution_chart["indexChart"]
        out["spotChart"] = execution_chart["indexChart"]
    full = execution_chart.get("indexChartFull")
    if isinstance(full, dict) and full:
        out["spotChartFull"] = full
    if execution_chart.get("indexMtf"):
        out["indexMtf"] = execution_chart["indexMtf"]
    out["executionChartSource"] = execution_chart.get("source", "unknown")
    return out


def annotate_breadth_bypass(
    ctx: dict[str, Any],
    *,
    side: Side | str,
    snap: Optional[SymbolSnapshot],
    score: float = 0.0,
) -> dict[str, Any]:
    from app.engines.aligned_side_guard import chart_mtf_breadth_bypass_active

    if not snap or not snap.breadth:
        return ctx
    bias = str(snap.breadth.bias or "NEUTRAL")
    bypassed, reason = chart_mtf_breadth_bypass_active(side, bias, snap, score=score)
    if bypassed:
        out = dict(ctx)
        out["chartMtfBreadthBypass"] = reason
        return out
    return ctx


def merge_close_context(
    entry_ctx: Optional[dict[str, Any]],
    snap: Optional[SymbolSnapshot],
    close_extra: dict[str, Any],
) -> dict[str, Any]:
    """Preserve entry chart snapshot on close — do not wipe audit fields."""
    ctx = dict(entry_ctx or {})
    if snap:
        ctx.update({
            "tqs": snap.tradeQualityScore,
            "regime": snap.regime.value if hasattr(snap.regime, "value") else snap.regime,
            "spot": snap.spot,
            "session": (
                snap.optimizedProfile.sessionLabel if snap.optimizedProfile else ctx.get("session", "")
            ),
        })
        if snap.psychology:
            ctx["psychology"] = snap.psychology.get("label")
    ctx.update(close_extra)
    return ctx
