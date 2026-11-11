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


def test_index_turn_waives_shallow_premium_5m_fade_on_bounce():
    """Nov 11 SENSEX 81300 CE miss: 5m premium dip before vertical — shallow fade OK."""
    from app.config import Settings
    from app.models.schemas import TimeframeChartRead
    from unittest.mock import patch

    candles = _rising_candles(steps=300)
    price = candles[-1][4]
    reads = _reads_from_1m(candles, price)
    premium_reads = {
        "1m": TimeframeChartRead(
            label="1m", price=576.0, direction="BULLISH", momentumPct=0.05,
        ),
        "5m": TimeframeChartRead(
            label="5m", price=576.0, direction="BEARISH", momentumPct=-0.28,
        ),
    }
    settings = Settings()
    with patch("app.engines.mtf_chart_analysis.get_settings", return_value=settings):
        ok, reason, _ = validate_mtf_scalp(
            Side.CALL,
            reads,
            premium_reads,
            trade_score=207.0,
            index_turn_fade_bypass=True,
        )
    assert ok is True
    assert reason == "ok"

    with patch("app.engines.mtf_chart_analysis.get_settings", return_value=settings):
        ok, reason, _ = validate_mtf_scalp(
            Side.CALL,
            reads,
            premium_reads,
            trade_score=60.0,
            index_turn_fade_bypass=False,
        )
    assert ok is False
    assert reason == "exec_mtf_premium_5m_fading"


def test_index_turn_waives_5m_fade_when_1m_premium_already_bullish():
    from app.config import Settings
    from app.models.schemas import TimeframeChartRead
    from unittest.mock import patch

    candles = _rising_candles(steps=300)
    price = candles[-1][4]
    reads = _reads_from_1m(candles, price)
    premium_reads = {
        "1m": TimeframeChartRead(
            label="1m", price=590.0, direction="BULLISH", momentumPct=1.2,
        ),
        "5m": TimeframeChartRead(
            label="5m", price=576.0, direction="BEARISH", momentumPct=-2.5,
        ),
    }
    settings = Settings()
    with patch("app.engines.mtf_chart_analysis.get_settings", return_value=settings):
        ok, reason, _ = validate_mtf_scalp(
            Side.CALL,
            reads,
            premium_reads,
            trade_score=60.0,
            index_turn_fade_bypass=True,
        )
    assert ok is True
    assert reason == "ok"


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


def test_pad_lane_bypass_blocked_when_premium_htf_opposes_call():
    from app.config import Settings
    from app.models.schemas import TimeframeChartRead
    from unittest.mock import patch

    candles = _rising_candles(steps=300)
    price = candles[-1][4]
    reads = _reads_from_1m(candles, price)
    premium_reads = {
        "1m": TimeframeChartRead(
            label="1m", price=180.0, direction="BULLISH", momentumPct=50.0, trendStrength=100.0,
        ),
        "5m": TimeframeChartRead(
            label="5m", price=180.0, direction="BULLISH", momentumPct=40.0, trendStrength=100.0,
        ),
        "1h": TimeframeChartRead(
            label="1h", price=180.0, direction="BEARISH", momentumPct=-1.0, trendStrength=100.0,
        ),
        "4h": TimeframeChartRead(
            label="4h", price=180.0, direction="BEARISH", momentumPct=-1.0, trendStrength=64.0,
        ),
    }
    settings = Settings()
    settings.execution_premium_htf_oppose_block_enabled = True
    with patch("app.engines.mtf_chart_analysis.get_settings", return_value=settings):
        passed, reason, _ = validate_mtf_scalp(
            Side.CALL,
            reads,
            premium_reads,
            trade_score=65,
            pad_lane_bypass=True,
        )
    assert passed is False
    assert reason == "exec_mtf_premium_htf_opposes"


def test_pad_lane_bypass_blocked_when_premium_htf_opposes_put():
    from app.config import Settings
    from app.models.schemas import TimeframeChartRead
    from unittest.mock import patch

    candles = _declining_candles(steps=300)
    price = candles[-1][4]
    reads = _reads_from_1m(candles, price)
    premium_reads = {
        "1m": TimeframeChartRead(
            label="1m", price=30.0, direction="NEUTRAL", momentumPct=-0.4, trendStrength=100.0,
        ),
        "5m": TimeframeChartRead(
            label="5m", price=30.0, direction="NEUTRAL", momentumPct=-0.3, trendStrength=100.0,
        ),
        "1h": TimeframeChartRead(
            label="1h", price=30.0, direction="BULLISH", momentumPct=1.0, trendStrength=100.0,
        ),
        "4h": TimeframeChartRead(
            label="4h", price=30.0, direction="BULLISH", momentumPct=1.0, trendStrength=64.0,
        ),
    }
    settings = Settings()
    settings.execution_premium_htf_oppose_block_enabled = True
    with patch("app.engines.mtf_chart_analysis.get_settings", return_value=settings):
        passed, reason, _ = validate_mtf_scalp(
            Side.PUT,
            reads,
            premium_reads,
            trade_score=65,
            pad_lane_bypass=True,
        )
    assert passed is False
    assert reason == "exec_mtf_premium_htf_opposes"


def test_nifty_expiry_1m_relief_allows_shallow_premium_retest():
    from app.config import Settings
    from app.models.schemas import TimeframeChartRead
    from unittest.mock import patch

    candles = _rising_candles(steps=300)
    price = candles[-1][4]
    reads = _reads_from_1m(candles, price)
    premium_reads = {
        "1m": TimeframeChartRead(
            label="1m", price=120.0, direction="BEARISH", momentumPct=-0.5,
        ),
        "5m": TimeframeChartRead(
            label="5m", price=120.0, direction="BULLISH", momentumPct=2.0,
        ),
    }
    settings = Settings()
    with patch("app.engines.mtf_chart_analysis.get_settings", return_value=settings):
        passed_strict, reason_strict, _ = validate_mtf_scalp(
            Side.CALL,
            reads,
            premium_reads,
            trade_score=65,
        )
        assert not passed_strict
        assert reason_strict == "exec_mtf_premium_1m_fading"

        passed, reason, meta = validate_mtf_scalp(
            Side.CALL,
            reads,
            premium_reads,
            trade_score=65,
            nifty_expiry_1m_relief=True,
        )
        assert passed is True
        assert reason == "ok"
        assert meta.get("niftyExpiry1mFadeRelief") is True


def test_nifty_expiry_1m_relief_still_blocks_deep_1m_dump():
    from app.config import Settings
    from app.models.schemas import TimeframeChartRead
    from unittest.mock import patch

    candles = _rising_candles(steps=300)
    price = candles[-1][4]
    reads = _reads_from_1m(candles, price)
    premium_reads = {
        "1m": TimeframeChartRead(
            label="1m", price=120.0, direction="BEARISH", momentumPct=-3.0,
        ),
        "5m": TimeframeChartRead(
            label="5m", price=120.0, direction="BULLISH", momentumPct=2.0,
        ),
    }
    settings = Settings()
    with patch("app.engines.mtf_chart_analysis.get_settings", return_value=settings):
        passed, reason, _ = validate_mtf_scalp(
            Side.CALL,
            reads,
            premium_reads,
            trade_score=65,
            nifty_expiry_1m_relief=True,
        )
    assert not passed
    assert reason == "exec_mtf_premium_1m_fading"
