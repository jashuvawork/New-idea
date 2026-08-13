"""5m spot chart — live snapshot index chart analysis."""

from app.engines.mtf_chart_analysis import resample_candles
from app.engines.spot_direction import _indicator_closes, build_spot_chart
from app.models.schemas import MarketProfile
from tests.test_spot_direction import _declining_candles, _rising_candles


def test_build_spot_chart_uses_5m_timeframe():
    candles_1m = _rising_candles(steps=100)
    candles_5m = resample_candles(candles_1m, 5)
    spot = candles_1m[-1][4]
    profile = MarketProfile(poc=spot - 2, openingRangeHigh=spot + 5, openingRangeLow=spot - 5)
    chart = build_spot_chart(candles_5m, spot, profile, indicator_candles_1m=candles_1m)
    assert chart.timeframe == "5m"
    assert chart.barCount == len(candles_5m)
    assert chart.direction == "BULLISH"
    assert chart.ema9 > 0
    assert chart.ema21 > 0
    assert chart.rsi > 50


def test_build_spot_chart_bearish_on_5m_decline():
    candles_1m = _declining_candles(steps=60)
    candles_5m = resample_candles(candles_1m, 5)
    spot = candles_1m[-1][4]
    profile = MarketProfile(poc=spot + 2, openingRangeHigh=spot + 5, openingRangeLow=spot - 1)
    chart = build_spot_chart(candles_5m, spot, profile, indicator_candles_1m=candles_1m)
    assert chart.direction == "BEARISH"
    assert chart.momentum5Pct < 0
    assert chart.macdBias in ("BEARISH", "NEUTRAL")


def test_build_spot_chart_empty_candles_neutral():
    chart = build_spot_chart([], 24400.0, MarketProfile())
    assert chart.direction == "NEUTRAL"
    assert chart.timeframe == "5m"
    assert chart.barCount == 0


def test_indicator_closes_uses_true_5m_when_enough_bars():
    """>=20 resampled 5m bars → RSI/MACD use true 5m closes, not 1m (the old bug kept
    the 5m chart on 1m data until ~35 bars / ~12:10 IST)."""
    candles_1m = _rising_candles(steps=120)  # ~120 min → 24 5m bars
    candles_5m = resample_candles(candles_1m, 5)
    assert len(candles_5m) >= 20
    closes = _indicator_closes(candles_5m, candles_1m)
    assert len(closes) == len(candles_5m)  # true 5m
    assert len(closes) != len(candles_1m)  # not the 1m series


def test_indicator_closes_falls_back_to_1m_when_5m_thin():
    """Early open (only a handful of 5m bars) still uses 1m so RSI is not undefined."""
    candles_1m = _rising_candles(steps=60)  # ~60 min → 12 5m bars (< 20)
    candles_5m = resample_candles(candles_1m, 5)
    assert len(candles_5m) < 20
    closes = _indicator_closes(candles_5m, candles_1m)
    assert len(closes) == len(candles_1m)  # 1m fallback
