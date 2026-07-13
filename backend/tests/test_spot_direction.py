"""Spot chart analysis — CE/PE must align with index candle direction."""

from unittest.mock import MagicMock, patch

from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_profit import check_explosion_entry
from app.engines.simple_profit import check_entry_gate
from app.engines.spot_direction import (
    analyze_spot_chart,
    chart_blocks_side,
    chart_rank_adjustment,
    side_aligned_with_chart,
)
from app.models.schemas import Breadth, MarketProfile, Side, SpotChart, StrategyType, SuggestedTrade


def _declining_candles(start: float = 100.0, steps: int = 35) -> list[list[float]]:
    """1m candles with steady decline."""
    out: list[list[float]] = []
    price = start
    for i in range(steps):
        nxt = price - 0.15
        out.append([i, price, price + 0.05, nxt - 0.05, nxt])
        price = nxt
    return out


def _rising_candles(start: float = 100.0, steps: int = 35) -> list[list[float]]:
    out: list[list[float]] = []
    price = start
    for i in range(steps):
        nxt = price + 0.15
        out.append([i, price, nxt + 0.05, price - 0.05, nxt])
        price = nxt
    return out


def _settings():
    s = MagicMock()
    s.chart_alignment_enabled = True
    s.chart_min_trend_strength = 25.0
    s.chart_min_momentum_pct = 0.04
    s.chart_override_min_score = 75
    s.chart_alignment_rank_bonus = 10.0
    s.aggressive_lot_sizing = True
    s.aggressive_min_tqs = 50
    s.enhanced_tqs_entry = 50
    s.enhanced_velocity_threshold = 1.2
    s.midday_chop_block_scalps = False
    s.neutral_breadth_min_score = 60
    s.counter_breadth_min_score = 70
    return s


def test_analyze_spot_chart_bearish_on_decline():
    candles = _declining_candles()
    spot = candles[-1][4]
    profile = MarketProfile(poc=spot + 2, openingRangeHigh=spot + 5, openingRangeLow=spot - 1)
    chart = analyze_spot_chart(candles, spot, profile)
    assert chart.direction == "BEARISH"
    assert chart.momentum5Pct < 0
    assert chart.momentum15Pct < 0
    assert chart.trendStrength >= 25
    assert chart.rsi < 50
    assert chart.macdBias in ("BEARISH", "NEUTRAL")


def test_analyze_spot_chart_bullish_on_rally():
    candles = _rising_candles()
    spot = candles[-1][4]
    profile = MarketProfile(poc=spot - 2, openingRangeHigh=spot + 5, openingRangeLow=spot - 5)
    chart = analyze_spot_chart(candles, spot, profile)
    assert chart.direction == "BULLISH"
    assert chart.momentum5Pct > 0
    assert chart.momentum15Pct > 0
    assert chart.rsi > 50
    assert chart.macdBias in ("BULLISH", "NEUTRAL")


def test_oversold_bounce_does_not_flip_bearish_session_bullish():
    """5m micro-bounce on oversold RSI must not override bearish 15m/30m session."""
    from app.engines.spot_direction import build_spot_chart

    candles_5m: list[list[float]] = []
    price = 24000.0
    for i in range(14):
        nxt = price - 8.0
        candles_5m.append([i, price, price + 2, nxt - 2, nxt])
        price = nxt
    # Tiny 5m bounce — mimics Jul 8 screenshot (+0.16% on 5m, still down on 15m/30m)
    bounce = price + 12.0
    candles_5m.append([14, price, bounce + 3, price - 2, bounce])
    spot = bounce
    profile = MarketProfile(
        poc=spot + 40,
        openingRangeHigh=spot + 80,
        openingRangeLow=spot - 20,
        val=spot - 10,
        vah=spot + 30,
    )
    chart = build_spot_chart(candles_5m, spot, profile)
    assert chart.momentum5Pct > 0
    assert chart.momentum15Pct < 0
    assert chart.rsiBias == "OVERSOLD"
    assert chart.direction in ("BEARISH", "NEUTRAL")


@patch("app.engines.spot_direction.get_settings")
def test_chart_blocks_call_on_declining_index(mock_settings):
    mock_settings.return_value = _settings()
    chart = SpotChart(
        direction="BEARISH",
        momentum5Pct=-0.12,
        momentum15Pct=-0.18,
        trendStrength=40,
        orPosition="BELOW",
        belowPoc=True,
    )
    blocked, reason = chart_blocks_side(Side.CALL, chart, trade_score=60)
    assert blocked
    assert reason in ("chart_bearish_no_calls", "chart_declining_no_calls", "chart_below_poc_no_calls")


@patch("app.engines.spot_direction.get_settings")
def test_chart_blocks_put_on_rallying_index(mock_settings):
    mock_settings.return_value = _settings()
    chart = SpotChart(
        direction="BULLISH",
        momentum5Pct=0.12,
        momentum15Pct=0.18,
        trendStrength=40,
        orPosition="ABOVE",
        abovePoc=True,
    )
    blocked, reason = chart_blocks_side(Side.PUT, chart, trade_score=60)
    assert blocked
    assert reason in ("chart_bullish_no_puts", "chart_rallying_no_puts", "chart_above_poc_no_puts")


@patch("app.engines.spot_direction.get_settings")
def test_chart_override_allows_high_score_counter_trend(mock_settings):
    mock_settings.return_value = _settings()
    # Override applies to soft momentum conflicts, not explicit opposite direction.
    chart = SpotChart(
        direction="NEUTRAL",
        momentum5Pct=-0.2,
        momentum15Pct=-0.3,
        trendStrength=50,
        orPosition="BELOW",
        belowPoc=True,
    )
    blocked, reason = chart_blocks_side(Side.CALL, chart, trade_score=78)
    assert not blocked
    assert reason == "ok"


@patch("app.engines.spot_direction.get_settings")
def test_expiry_explosion_bypass_hard_bearish_chart(mock_settings):
    mock_settings.return_value = _settings()
    chart = SpotChart(
        direction="BEARISH",
        momentum5Pct=-0.12,
        momentum15Pct=-0.18,
        trendStrength=42,
    )
    blocked, reason = chart_blocks_side(
        Side.CALL, chart, trade_score=60, expiry_explosion_bypass=True,
    )
    assert not blocked
    assert reason == "ok"


@patch("app.engines.spot_direction.get_settings")
def test_high_score_cannot_override_bearish_chart_direction(mock_settings):
    mock_settings.return_value = _settings()
    chart = SpotChart(
        direction="BEARISH",
        momentum5Pct=0.04,
        momentum15Pct=-0.06,
        trendStrength=42,
        emaBias="BEARISH",
        macdBias="BEARISH",
    )
    blocked, reason = chart_blocks_side(Side.CALL, chart, trade_score=91)
    assert blocked
    assert reason == "chart_bearish_no_calls"


@patch("app.engines.spot_direction.get_settings")
def test_breadth_bypass_allows_pm_itm_call_on_bearish_chart(mock_settings):
    mock_settings.return_value = _settings()
    chart = SpotChart(
        direction="BEARISH",
        momentum5Pct=-0.04,
        momentum15Pct=-0.06,
        trendStrength=42,
        emaBias="BEARISH",
        macdBias="BEARISH",
    )
    blocked, reason = chart_blocks_side(
        Side.CALL, chart, trade_score=55, breadth_aligned_bypass=True,
    )
    assert not blocked
    assert reason == "ok"


@patch("app.engines.spot_direction.get_settings")
def test_chart_rank_bonus_for_aligned_side(mock_settings):
    mock_settings.return_value = _settings()
    chart = SpotChart(direction="BEARISH", momentum5Pct=-0.1, momentum15Pct=-0.15, trendStrength=35)
    assert chart_rank_adjustment(Side.PUT, chart) == 10.0
    assert chart_rank_adjustment(Side.CALL, chart) == -10.0


@patch("app.engines.simple_profit.get_settings")
def test_scalp_gate_blocks_call_when_chart_declining(mock_settings):
    mock_settings.return_value = _settings()
    trade = SuggestedTrade(
        id="x",
        symbol="NIFTY",
        side=Side.CALL,
        strike=23900,
        lastPremium=80.0,
        tqs=62,
        confidence=62,
        strategyType=StrategyType.SCALP,
    )
    chart = SpotChart(
        direction="BEARISH",
        momentum5Pct=-0.1,
        momentum15Pct=-0.15,
        trendStrength=40,
        orPosition="BELOW",
        belowPoc=True,
    )
    ok, reason = check_entry_gate(
        trade,
        Breadth(bias="NEUTRAL", score=50, aligned=False),
        62,
        2.5,
        False,
        chart=chart,
    )
    assert not ok
    assert "chart_" in reason


@patch("app.engines.simple_profit.get_settings")
@patch("app.engines.directional_lock.check_directional_side_lock_simple", return_value=(False, "ok"))
def test_alignment_override_cannot_bypass_hard_chart_direction(mock_dir, mock_settings):
    mock_settings.return_value = _settings()
    trade = SuggestedTrade(
        id="x",
        symbol="NIFTY",
        side=Side.CALL,
        strike=23900,
        lastPremium=80.0,
        tqs=90,
        confidence=90,
        strategyType=StrategyType.SCALP,
    )
    chart = SpotChart(
        direction="BEARISH",
        momentum5Pct=0.04,
        momentum15Pct=-0.06,
        trendStrength=42,
    )
    ok, reason = check_entry_gate(
        trade,
        Breadth(bias="NEUTRAL", score=50, aligned=False),
        90,
        2.5,
        False,
        alignment_override=True,
        chart=chart,
    )
    assert not ok
    assert reason == "chart_bearish_no_calls"


def test_explosion_blocks_call_on_bearish_chart():
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=23900,
        premium=80,
        velocity_3s=3.5,
        velocity_9s=4.0,
        velocity_15s=5.0,
        volume_surge=1.6,
        explosion_score=55,
        tier="EXPLODING",
        reason="test",
    )
    trade = SuggestedTrade(
        id="t1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=23900,
        lastPremium=80,
        tqs=55,
        strategyType=StrategyType.EXPLOSIVE,
        confidence=55,
    )
    chart = SpotChart(
        direction="BEARISH",
        momentum5Pct=-0.1,
        momentum15Pct=-0.2,
        trendStrength=45,
        orPosition="BELOW",
        belowPoc=True,
    )
    with patch("app.engines.spot_direction.get_settings") as mock_settings, patch(
        "app.engines.morning_premium_capture.in_premium_capture_window", return_value=False,
    ):
        mock_settings.return_value = _settings()
        ok, reason = check_explosion_entry(
            event, trade, Breadth(score=50, bias="NEUTRAL", aligned=False), False, chart=chart,
        )
    assert not ok
    assert "bearish" in reason.lower() or "chart" in reason.lower()


def test_side_aligned_with_chart():
    bull = SpotChart(direction="BULLISH", momentum5Pct=0.1)
    bear = SpotChart(direction="BEARISH", momentum5Pct=-0.1)
    assert side_aligned_with_chart(Side.CALL, bull)
    assert not side_aligned_with_chart(Side.CALL, bear)
    assert side_aligned_with_chart(Side.PUT, bear)
    assert not side_aligned_with_chart(Side.PUT, bull)


def test_reconcile_spot_chart_overrides_bullish_5m_on_bearish_mtf():
    from app.engines.spot_direction import reconcile_spot_chart_with_mtf
    from app.models.schemas import ChartAnalysis

    spot = SpotChart(
        direction="BULLISH",
        momentum5Pct=0.1,
        momentum15Pct=-0.2,
        momentum30Pct=-0.25,
    )
    analysis = ChartAnalysis(
        consensus="BEARISH",
        alignedCount=4,
        totalTimeframes=5,
        timeframes={
            "1m": {"direction": "BEARISH"},
            "5m": {"direction": "BEARISH"},
            "15m": {"direction": "BEARISH"},
            "1h": {"direction": "BEARISH"},
            "4h": {"direction": "NEUTRAL"},
        },
    )
    out = reconcile_spot_chart_with_mtf(spot, analysis, breadth_bias="BEARISH", from_open_pct=-0.5)
    assert out.direction == "BEARISH"


def test_live_spot_patch_fixes_stale_rsi_on_afternoon_rally():
    """Morning dip leaves stale 5m close; live spot rally should lift RSI like broker charts."""
    from app.engines.spot_direction import build_spot_chart

    candles_5m: list[list[float]] = []
    price = 24000.0
    for i in range(20):
        nxt = price - 6.0
        candles_5m.append([i, price, price + 2, nxt - 2, nxt])
        price = nxt
    stale_close = price + 30.0
    candles_5m.append([20, price, stale_close + 5, price - 2, stale_close])
    live_spot = 24233.2
    profile = MarketProfile(
        poc=live_spot - 40,
        openingRangeHigh=live_spot + 80,
        openingRangeLow=live_spot - 120,
    )
    chart_stale = build_spot_chart(candles_5m, stale_close, profile)
    chart_live = build_spot_chart(candles_5m, live_spot, profile)
    assert chart_stale.rsi < 35
    assert chart_live.rsi > 50
    assert chart_live.macdBias in ("BULLISH", "NEUTRAL")
    assert chart_live.direction in ("BULLISH", "NEUTRAL")


def test_reconcile_ichimoku_flips_bearish_spot_on_live_rally():
    from app.engines.spot_direction import reconcile_spot_chart_with_mtf
    from app.models.schemas import ChartAnalysis

    spot = SpotChart(
        direction="BEARISH",
        momentum5Pct=0.02,
        momentum15Pct=0.01,
        momentum30Pct=-0.05,
        rsi=58.0,
        macdBias="BULLISH",
    )
    analysis = ChartAnalysis(
        consensus="NEUTRAL",
        alignedCount=0,
        totalTimeframes=0,
        timeframes={},
        ichimoku={
            "cloudBias": "BULLISH",
            "priceVsCloud": "ABOVE",
            "tkCross": "BEARISH",
        },
    )
    out = reconcile_spot_chart_with_mtf(spot, analysis, breadth_bias="BEARISH")
    assert out.direction == "BULLISH"
