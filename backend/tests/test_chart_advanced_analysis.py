"""Advanced chart analysis — MTF, Fibonacci, patterns, SMC."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.engines.chart_advanced_analysis import (
    build_chart_analysis,
    compute_fibonacci_levels,
    compute_ichimoku,
    compute_pivot_points,
    detect_candlestick_patterns,
    detect_smt_divergence,
    analyze_smc_ict,
)
from app.models.schemas import MarketProfile

IST = ZoneInfo("Asia/Kolkata")


def _candles(closes: list[float]) -> list[list[float]]:
    out: list[list[float]] = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        out.append([i, o, max(o, c) + 1, min(o, c) - 1, c])
    return out


def test_fibonacci_levels_and_zone():
    fib = compute_fibonacci_levels(100.0, 200.0, 160.0, trend="UP")
    assert fib["zone"] == "PREMIUM"
    assert "618" in fib["retracement"]
    assert fib["extension"]["1.618"] > 200.0


def test_pivot_points():
    pivots = compute_pivot_points(105.0, 95.0, 100.0)
    assert pivots["P"] == 100.0
    assert pivots["R1"] > pivots["P"]
    assert pivots["S1"] < pivots["P"]


def test_bullish_engulfing_pattern():
    opens = [100, 99, 98]
    highs = [101, 100, 102]
    lows = [98, 97, 97]
    closes = [99, 98, 101]
    patterns = detect_candlestick_patterns(opens, highs, lows, closes, timeframe="5m")
    names = [p["name"] for p in patterns]
    assert "Bullish Engulfing" in names


def test_smc_stop_hunt_detection():
    opens = [100.0] * 20
    highs = [101.0] * 18 + [105.0, 102.0]
    lows = [99.0] * 20
    closes = [100.0] * 18 + [104.0, 100.5]
    smc = analyze_smc_ict(opens, highs, lows, closes, 100.5)
    assert smc["sessionHigh"] == 105.0
    assert smc["premiumDiscount"] in ("PREMIUM", "DISCOUNT", "EQUILIBRIUM")


def test_smt_divergence_bearish():
    primary = [100 + i * 0.5 for i in range(20)] + [110.0]
    compare = [100 + i * 0.5 for i in range(20)] + [108.0]
    smt = detect_smt_divergence(primary, compare, primary_symbol="NIFTY", compare_symbol="SENSEX")
    assert smt is not None
    assert smt["type"] == "bearish_smt"


def test_build_chart_analysis_mtf():
    closes = [100 + i * 0.2 for i in range(80)]
    candles_1m = _candles(closes)
    candles_5m = candles_1m[::5]
    profile = MarketProfile(poc=110, openingRangeHigh=115, openingRangeLow=105)
    analysis = build_chart_analysis(
        candles_1m,
        candles_5m,
        closes[-1],
        profile,
        prev_close=100.0,
        day_high=115.0,
        day_low=99.0,
        symbol="NIFTY",
    )
    assert analysis.consensus in ("BULLISH", "BEARISH", "NEUTRAL")
    assert "5m" in analysis.timeframes
    assert analysis.ichimoku.get("cloudBias")
    assert len(analysis.recentCloses) > 0


def test_build_chart_analysis_mtf_fallback_from_5m_only():
    closes = [100 + i * 0.25 for i in range(40)]
    candles_5m = _candles(closes)
    profile = MarketProfile(poc=108, openingRangeHigh=112, openingRangeLow=102)
    analysis = build_chart_analysis(
        [],
        candles_5m,
        closes[-1],
        profile,
        prev_close=100.0,
        day_high=112.0,
        day_low=99.0,
        symbol="NIFTY",
    )
    assert analysis.totalTimeframes >= 4
    assert "5m" in analysis.timeframes
    assert "15m" in analysis.timeframes
    assert analysis.consensus in ("BULLISH", "BEARISH", "NEUTRAL")


def test_ichimoku_cloud_bias():
    highs = [110 + i * 0.1 for i in range(60)]
    lows = [108 + i * 0.1 for i in range(60)]
    closes = [109 + i * 0.1 for i in range(60)]
    ich = compute_ichimoku(highs, lows, closes, closes[-1])
    assert ich["tenkan"] > 0
    assert ich["cloudBias"] in ("BULLISH", "BEARISH", "NEUTRAL")
