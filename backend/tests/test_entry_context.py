"""Entry context persistence — chart/MTF on open, merge on close."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.auto_trader import _build_context
from app.engines.entry_context import (
    merge_close_context,
    merge_execution_chart_context,
    snapshot_chart_context,
)
from app.models.schemas import (
    Breadth,
    ChartAnalysis,
    MarketPhase,
    OptimizedProfile,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24200.0,
        tradeQualityScore=55.0,
        regime=Regime.TREND_EXPANSION,
        spotChart=SpotChart(
            direction="BULLISH",
            spot=24200.0,
            rsi=65.0,
            macdBias="BULLISH",
            momentum5Pct=0.08,
            trendStrength=45.0,
        ),
        breadth=Breadth(bias="BEARISH", score=52.0, aligned=False, source="oi"),
        chartAnalysis=ChartAnalysis(
            consensus="BULLISH",
            alignedCount=4,
            totalTimeframes=4,
            ichimoku={"cloudBias": "BULLISH", "priceVsCloud": "ABOVE"},
            keySignals=["Fib 618 (PREMIUM)"],
        ),
        optimizedProfile=OptimizedProfile(sessionLabel="PM"),
    )


def test_snapshot_chart_context_includes_chart_and_mtf():
    ctx = snapshot_chart_context(_snap())
    assert ctx["indexChart"]["direction"] == "BULLISH"
    assert ctx["spotChart"]["rsi"] == 65.0
    assert ctx["chartAnalysis"]["consensus"] == "BULLISH"
    assert ctx["breadth"]["bias"] == "BEARISH"


def test_build_context_includes_chart_snapshot():
    ctx = _build_context(_snap(), {"selectionMode": "explosion", "selectionScore": 45.0})
    assert ctx["indexChart"]["direction"] == "BULLISH"
    assert ctx["chartAnalysis"]["alignedCount"] == 4
    assert ctx["selectionMode"] == "explosion"


def test_merge_execution_chart_prefers_live_read():
    base = snapshot_chart_context(_snap())
    live = {
        "enabled": True,
        "source": "upstox_live",
        "indexChart": {"direction": "NEUTRAL", "rsi": 50.0},
        "indexMtf": {"consensus": "NEUTRAL"},
    }
    out = merge_execution_chart_context(base, live)
    assert out["indexChart"]["direction"] == "NEUTRAL"
    assert out["executionChartSource"] == "upstox_live"


def test_merge_close_context_preserves_entry_chart():
    entry = _build_context(_snap(), {"selectionScore": 88.0, "selectionMode": "explosion"})
    closed = merge_close_context(entry, _snap(), {
        "exitReason": "explosion_time_stop",
        "bestPnlPoints": 11.5,
        "pnlPoints": -2.0,
        "pnlInr": -1500.0,
    })
    assert closed["indexChart"]["direction"] == "BULLISH"
    assert closed["selectionScore"] == 88.0
    assert closed["bestPnlPoints"] == 11.5
    assert closed["exitReason"] == "explosion_time_stop"


@patch("app.engines.aligned_side_guard.get_settings")
def test_annotate_breadth_bypass(mock_settings):
    from app.engines.entry_context import annotate_breadth_bypass

    s = mock_settings.return_value
    s.chart_mtf_breadth_bypass_enabled = True
    s.chart_mtf_breadth_bypass_min_explosion_score = 42.0
    s.chart_mtf_breadth_bypass_min_aligned = 3
    s.chart_mtf_breadth_bypass_min_rsi = 52.0

    base = snapshot_chart_context(_snap())
    out = annotate_breadth_bypass(base, side=Side.CALL, snap=_snap(), score=45.0)
    assert out.get("chartMtfBreadthBypass") == "chart_mtf_bullish_bypass_bearish_breadth"
