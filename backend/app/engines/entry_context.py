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
        mtf_out: dict[str, Any] | None = None
        if ca.timeframes or ca.alignedCount:
            tf_summary: dict[str, Any] = {}
            for label, tf in (ca.timeframes or {}).items():
                if isinstance(tf, dict):
                    tf_summary[label] = {
                        "direction": tf.get("direction"),
                        "rsi": tf.get("rsi"),
                        "macdBias": tf.get("macdBias"),
                    }
            mtf_out = {
                "consensus": ca.consensus,
                "alignedCount": ca.alignedCount,
                "totalTimeframes": ca.totalTimeframes,
                "timeframes": tf_summary,
            }
        out["chartAnalysis"] = {
            "consensus": ca.consensus,
            "alignedCount": ca.alignedCount,
            "totalTimeframes": ca.totalTimeframes,
            "ichimoku": ca.ichimoku or {},
            "keySignals": (ca.keySignals or [])[:8],
            "mtf": mtf_out,
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
        ca = out.get("chartAnalysis")
        if isinstance(ca, dict):
            im = execution_chart["indexMtf"]
            tf_summary: dict[str, Any] = {}
            for label, tf in (im.get("timeframes") or {}).items():
                if isinstance(tf, dict):
                    tf_summary[label] = {
                        "direction": tf.get("direction"),
                        "rsi": tf.get("rsi"),
                        "macdBias": tf.get("macdBias"),
                    }
            ca = dict(ca)
            ca["mtf"] = {
                "consensus": im.get("consensus"),
                "alignedCount": im.get("alignedCount"),
                "totalTimeframes": im.get("total"),
                "timeframes": tf_summary,
            }
            out["chartAnalysis"] = ca
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
