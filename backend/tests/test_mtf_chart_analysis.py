"""Multi-timeframe scalp chart pre-test — 1m/5m/15m/1h/4h."""

from app.engines.mtf_chart_analysis import (
    SCALP_TIMEFRAMES,
    analyze_timeframe,
    mtf_summary,
    resample_candles,
    validate_mtf_scalp,
)
from app.models.schemas import Side
from tests.test_spot_direction import _declining_candles, _rising_candles


def _reads_from_1m(candles: list, price: float):
    reads = {"1m": analyze_timeframe(candles, price, "1m")}
    for frame in SCALP_TIMEFRAMES:
        if frame["label"] == "1m":
            continue
        resampled = resample_candles(candles, frame["resample"])
        reads[frame["label"]] = analyze_timeframe(resampled, price, frame["label"])
    return reads


def test_resample_5m_from_1m():
    candles = _rising_candles(steps=60)
    resampled = resample_candles(candles, 5)
    assert len(resampled) == 12
    assert resampled[-1][4] > resampled[0][4]


def test_declining_index_mtf_blocks_call():
    candles = _declining_candles(steps=300)
    price = candles[-1][4]
    reads = _reads_from_1m(candles, price)
    assert reads["1m"].direction == "BEARISH"
    passed, reason, meta = validate_mtf_scalp(Side.CALL, reads, trade_score=60)
    assert not passed
    assert "exec_mtf" in reason
    assert meta["index"]["alignedCount"] < 5


def test_rising_index_mtf_passes_call():
    candles = _rising_candles(steps=300)
    price = candles[-1][4]
    reads = _reads_from_1m(candles, price)
    passed, reason, _ = validate_mtf_scalp(Side.CALL, reads, trade_score=65)
    assert passed
    assert reason == "ok"


def test_declining_index_mtf_passes_put():
    candles = _declining_candles(steps=300)
    price = candles[-1][4]
    reads = _reads_from_1m(candles, price)
    passed, reason, meta = validate_mtf_scalp(Side.PUT, reads, trade_score=65)
    assert passed
    assert meta["index"]["consensus"] in ("BEARISH", "NEUTRAL")


def test_mtf_summary_counts():
    candles = _rising_candles(steps=300)
    price = candles[-1][4]
    reads = _reads_from_1m(candles, price)
    summary = mtf_summary(reads, Side.CALL)
    assert summary["total"] == 5
    assert "1m" in summary["timeframes"]
    assert summary["alignedCount"] >= 3


def test_pad_lane_bypass_allows_shallow_premium_5m_fade_on_put():
    from app.config import Settings
    from app.models.schemas import TimeframeChartRead
    from unittest.mock import patch

    candles = _declining_candles(steps=300)
    price = candles[-1][4]
    reads = _reads_from_1m(candles, price)
    premium_reads = {
        "1m": TimeframeChartRead(
            label="1m", price=30.0, direction="BEARISH", momentumPct=-0.5,
        ),
        "5m": TimeframeChartRead(
            label="5m", price=30.0, direction="BEARISH", momentumPct=-0.8,
        ),
    }
    settings = Settings()
    with patch("app.engines.mtf_chart_analysis.get_settings", return_value=settings):
        blocked, reason, _ = validate_mtf_scalp(
            Side.PUT,
            reads,
            premium_reads,
            trade_score=65,
            pad_lane_bypass=True,
        )
    assert blocked is True
    assert reason == "ok"


def test_reclaim_off_the_low_clears_5m_fade():
    """25-minute momentum still holds the open flush. The 15-minute leg is the lift."""
    from app.models.schemas import TimeframeChartRead

    candles = _rising_candles(steps=300)
    price = candles[-1][4]
    reads = _reads_from_1m(candles, price)
    premium = {
        "1m": TimeframeChartRead(
            label="1m", price=149.0, direction="BULLISH", momentumPct=0.4,
            momentum3Pct=0.2, offLowPct=15.0,
        ),
        "5m": TimeframeChartRead(
            label="5m", price=149.0, direction="BEARISH", momentumPct=-9.0,
            momentum3Pct=6.0, offLowPct=15.0,
        ),
    }
    passed, reason, _ = validate_mtf_scalp(
        Side.CALL, reads, premium, trade_score=60,
    )
    assert passed
    assert reason == "ok"


def test_fresh_5m_dump_still_fades_off_the_low():
    from app.models.schemas import TimeframeChartRead

    candles = _rising_candles(steps=300)
    price = candles[-1][4]
    reads = _reads_from_1m(candles, price)
    premium = {
        "1m": TimeframeChartRead(
            label="1m", price=200.0, direction="BEARISH", momentumPct=-6.0,
            momentum3Pct=-5.0, offLowPct=20.0,
        ),
        "5m": TimeframeChartRead(
            label="5m", price=200.0, direction="BEARISH", momentumPct=-12.0,
            momentum3Pct=-8.0, offLowPct=20.0,
        ),
    }
    passed, reason, _ = validate_mtf_scalp(
        Side.CALL, reads, premium, trade_score=60,
    )
    assert not passed
    assert reason == "exec_mtf_premium_1m_fading"


def test_5m_bars_measure_off_low_on_the_reclaim_window():
    """Four 5m bars is the 20-minute low, so the 09:20 flush is still in view at 09:39."""
    # Each bar: [ts, open, high, low, close]
    bars = [
        [0, 161, 162, 140, 142],
        [1, 142, 143, 127, 130],
        [2, 130, 146, 129, 145],
        [3, 145, 152, 144, 149],
    ]
    read = analyze_timeframe(bars, 149.0, "5m")
    assert read.offLowPct >= 8.0
