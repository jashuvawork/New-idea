"""RSI and MACD chart indicator tests."""

from app.engines.chart_indicators import compute_macd, compute_rsi
from app.engines.spot_direction import analyze_premium_chart, analyze_spot_chart
from app.models.schemas import MarketProfile


def _trending_closes(start: float, step: float, count: int) -> list[float]:
    return [start + i * step for i in range(count)]


def _candles_from_closes(closes: list[float]) -> list[list[float]]:
    out: list[list[float]] = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        out.append([i, o, max(o, c) + 0.05, min(o, c) - 0.05, c])
    return out


def test_rsi_oversold_on_steep_decline():
    closes = _trending_closes(100.0, -0.5, 40)
    rsi = compute_rsi(closes)
    assert rsi.value < 35
    assert rsi.bias == "OVERSOLD"


def test_rsi_overbought_on_steep_rally():
    closes = _trending_closes(100.0, 0.5, 40)
    rsi = compute_rsi(closes)
    assert rsi.value > 65
    assert rsi.bias == "OVERBOUGHT"


def test_macd_bullish_on_uptrend():
    closes = _trending_closes(100.0, 0.3, 50)
    macd = compute_macd(closes)
    assert macd.line > macd.signal
    assert macd.bias == "BULLISH"


def test_macd_bearish_on_downtrend():
    closes = _trending_closes(100.0, -0.3, 50)
    macd = compute_macd(closes)
    assert macd.line < macd.signal
    assert macd.bias == "BEARISH"


def test_analyze_spot_chart_includes_rsi_macd():
    closes = _trending_closes(100.0, -0.15, 40)
    candles = _candles_from_closes(closes)
    spot = closes[-1]
    profile = MarketProfile(poc=spot + 2, openingRangeHigh=spot + 5, openingRangeLow=spot - 1)
    chart = analyze_spot_chart(candles, spot, profile)
    assert chart.rsi < 50
    assert chart.rsiBias in ("OVERSOLD", "NEUTRAL")
    assert chart.macdBias in ("BEARISH", "NEUTRAL", "BULLISH")


def test_analyze_premium_chart_live_ltp_patches_indicators():
    closes = _trending_closes(100.0, -0.4, 40)
    candles = _candles_from_closes(closes)
    for c in candles:
        c.append(1000)
    stale = closes[-1]
    live = stale + 6.0
    chart_stale = analyze_premium_chart(candles, stale)
    chart_live = analyze_premium_chart(candles, live)
    assert chart_live.rsi > chart_stale.rsi
    assert chart_live.momentum5Pct > chart_stale.momentum5Pct
    assert chart_live.macdBias in ("BULLISH", "BEARISH", "NEUTRAL")


def test_refresh_spot_chart_live_from_recent_closes():
    from app.engines.spot_direction import refresh_spot_chart_live
    from app.models.schemas import ChartAnalysis, SpotChart

    recent = [24000 + i * 2 for i in range(20)] + [24030.0]
    live = 24233.2
    chart = SpotChart(direction="BEARISH", spot=24030.0, rsi=22.0, macdBias="BEARISH")
    analysis = ChartAnalysis(consensus="NEUTRAL", recentCloses=recent, ichimoku={
        "cloudBias": "BULLISH", "priceVsCloud": "ABOVE", "tkCross": "BEARISH",
    })
    profile = MarketProfile(poc=24100, openingRangeHigh=24200, openingRangeLow=23900)
    out = refresh_spot_chart_live(
        chart, live_spot=live, profile=profile, chart_analysis=analysis, breadth_bias="BEARISH",
    )
    assert out.spot == live
    assert out.rsi > 50
    assert out.direction in ("BULLISH", "NEUTRAL")
