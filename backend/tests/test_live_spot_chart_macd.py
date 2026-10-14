"""Live tick spot-chart refresh must keep enough 5m bars for MACD (slow 26 + signal 9)."""

import pytest

from app.engines.chart_advanced_analysis import build_chart_analysis
from app.engines.spot_direction import refresh_spot_chart_live
from app.models.schemas import ChartAnalysis, MarketProfile, SpotChart
from tests.test_chart_advanced_analysis import _candles


def _turning_closes(side: str, n: int = 120) -> list[float]:
    """Flat base then an accelerating move — MACD line pulls away from its signal."""
    sign = 1.0 if side == "CE" else -1.0
    out: list[float] = []
    price = 24000.0
    for i in range(n):
        if i >= n - 25:
            price += sign * (2.0 + 0.4 * (i - (n - 25)))
        else:
            price += 0.5 if i % 2 else -0.5
        out.append(round(price, 2))
    return out


@pytest.mark.parametrize("side,bias", [("CE", "BULLISH"), ("PE", "BEARISH")])
def test_live_refresh_uses_indicator_closes_for_macd(side, bias):
    closes = _turning_closes(side)
    analysis = ChartAnalysis(recentCloses=closes[-30:], indicatorCloses=closes)
    live = closes[-1] + (3.0 if side == "CE" else -3.0)
    chart = refresh_spot_chart_live(
        SpotChart(direction="NEUTRAL", spot=closes[-1], timeframe="5m"),
        live_spot=live,
        profile=MarketProfile(poc=24000.0),
        chart_analysis=analysis,
    )
    assert chart.macdBias == bias
    assert chart.macdHistogram != 0.0
    assert (chart.macdHistogram > 0) == (side == "CE")


@pytest.mark.parametrize("side", ["CE", "PE"])
def test_live_refresh_without_indicator_closes_keeps_old_behaviour(side):
    closes = _turning_closes(side)
    analysis = ChartAnalysis(recentCloses=closes[-30:])
    chart = refresh_spot_chart_live(
        SpotChart(direction="NEUTRAL", spot=closes[-1], timeframe="5m"),
        live_spot=closes[-1],
        profile=MarketProfile(poc=24000.0),
        chart_analysis=analysis,
    )
    assert chart.macdBias == "NEUTRAL"
    assert chart.macdHistogram == 0.0


def test_live_refresh_reads_indicator_closes_from_dict():
    closes = _turning_closes("CE")
    chart = refresh_spot_chart_live(
        SpotChart(direction="NEUTRAL", spot=closes[-1], timeframe="5m"),
        live_spot=closes[-1],
        profile=MarketProfile(poc=24000.0),
        chart_analysis={"recentCloses": closes[-30:], "indicatorCloses": closes},
    )
    assert chart.macdBias == "BULLISH"


def test_build_chart_analysis_populates_indicator_closes():
    closes_1m = [100 + i * 0.2 for i in range(400)]
    candles_1m = _candles(closes_1m)
    candles_5m = candles_1m[::5]
    analysis = build_chart_analysis(
        candles_1m,
        candles_5m,
        closes_1m[-1],
        MarketProfile(poc=110, openingRangeHigh=115, openingRangeLow=105),
        prev_close=100.0,
        symbol="NIFTY",
    )
    assert len(analysis.recentCloses) == 30
    assert len(analysis.indicatorCloses) >= 35
    assert len(analysis.indicatorCloses) <= 120
