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
