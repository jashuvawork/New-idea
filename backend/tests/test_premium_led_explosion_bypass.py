"""Premium-led explosion bypass — PE rips when index chart/breadth still bullish."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_profit import check_explosion_entry
from app.engines.morning_premium_capture import premium_led_explosion_bypass
from app.engines.session_timing import explosion_entries_allowed_now
from app.models.schemas import (
    Breadth,
    ConstituentHeatmap,
    MarketPhase,
    Side,
    SpotChart,
    StrategyType,
    SuggestedTrade,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _put_event(**kwargs) -> ExplosionEvent:
    base = dict(
        symbol="NIFTY",
        side=Side.PUT,
        strike=24050.0,
        premium=45.0,
        velocity_3s=4.5,
        velocity_9s=6.0,
        velocity_15s=8.0,
        volume_surge=2.2,
        explosion_score=52.0,
        tier="EXPLODING",
        reason="+4.5%/3s",
    )
    base.update(kwargs)
    return ExplosionEvent(**base)


def _trade() -> SuggestedTrade:
    return SuggestedTrade(
        id="t1",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24050.0,
        lastPremium=45.0,
        tqs=50,
        strategyType=StrategyType.EXPLOSIVE,
        confidence=52,
    )


def _bullish_chart() -> SpotChart:
    return SpotChart(
        direction="BULLISH",
        spot=24500.0,
        momentum5Pct=0.08,
        momentum15Pct=0.05,
        trendStrength=35.0,
        emaBias="BULLISH",
        macdBias="BULLISH",
    )


@patch("app.engines.morning_premium_capture.in_premium_capture_window", return_value=True)
@patch("app.engines.morning_premium_capture.get_settings")
def test_premium_led_bypass_detects_put_vs_bullish(mock_settings, mock_window):
    s = mock_settings.return_value
    s.premium_led_explosion_bypass_enabled = True
    s.premium_led_counter_breadth_enabled = True
    s.morning_capture_extreme_velocity_3s = 3.0
    s.morning_capture_extreme_velocity_9s = 4.0
    s.premium_led_min_velocity_3s = 2.8
    s.premium_led_min_velocity_9s = 3.5
    s.premium_led_min_explosion_score = 42.0
    s.morning_capture_building_min_velocity_3s = 2.0
    s.morning_capture_min_velocity_9s = 2.8
    s.morning_capture_min_vol_surge = 1.3
    s.morning_capture_building_min_score = 38.0

    event = _put_event()
    assert premium_led_explosion_bypass(event, _bullish_chart(), "BULLISH") is True


@patch("app.engines.morning_premium_capture.in_premium_capture_window", return_value=True)
@patch("app.engines.morning_premium_capture.get_settings")
def test_put_explosion_passes_bullish_breadth_and_chart(mock_settings, mock_window):
    s = mock_settings.return_value
    s.premium_led_explosion_bypass_enabled = True
    s.premium_led_counter_breadth_enabled = True
    s.morning_capture_extreme_velocity_3s = 3.0
    s.morning_capture_extreme_velocity_9s = 4.0
    s.premium_led_min_velocity_3s = 2.8
    s.premium_led_min_velocity_9s = 3.5
    s.premium_led_min_explosion_score = 42.0
    s.morning_capture_building_min_velocity_3s = 2.0
    s.morning_capture_min_velocity_9s = 2.8
    s.morning_capture_min_vol_surge = 1.3
    s.morning_capture_building_min_score = 38.0
    s.aggressive_min_explosion_score = 45
    s.explosion_breadth_alignment_enabled = True
    s.chart_alignment_enabled = True
    s.chart_min_trend_strength = 25.0
    s.index_pin_put_block_enabled = True
    s.index_pin_min_stock_breadth_pct = 58.0

    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry="2026-07-14",
        spot=24500.0,
        spotChart=_bullish_chart(),
        marketProfile=__import__("app.models.schemas", fromlist=["MarketProfile"]).MarketProfile(
            openingRangeHigh=24480.0,
        ),
        constituentHeatmap=ConstituentHeatmap(
            symbol="NIFTY",
            dataAvailable=True,
            breadthPct=62.0,
        ),
    )
    event = _put_event()
    ok, reason = check_explosion_entry(
        event,
        _trade(),
        Breadth(score=62, bias="BULLISH", aligned=True),
        False,
        chart=_bullish_chart(),
        snap=snap,
    )
    assert ok is True
    assert reason.startswith("premium_led_")


@patch("app.engines.morning_premium_capture.in_premium_capture_window", return_value=False)
@patch("app.engines.morning_premium_capture.get_settings")
def test_put_explosion_still_blocked_without_bypass_window(mock_settings, mock_window):
    s = mock_settings.return_value
    s.premium_led_explosion_bypass_enabled = True
    s.premium_led_counter_breadth_enabled = True
    s.explosion_breadth_alignment_enabled = True
    s.aggressive_min_explosion_score = 45

    event = _put_event()
    ok, reason = check_explosion_entry(
        event,
        _trade(),
        Breadth(score=62, bias="BULLISH", aligned=True),
        False,
        chart=_bullish_chart(),
    )
    assert not ok
    assert reason == "explosion_put_vs_bullish_breadth"


@patch("app.engines.session_timing._minutes_now", return_value=9 * 60 + 17)
@patch("app.engines.session_timing.get_settings")
@patch("app.engines.session_timing.get_market_phase", return_value="LIVE_MARKET")
def test_explosion_entries_allowed_915_to_920(mock_phase, mock_settings, mock_minutes):
    s = mock_settings.return_value
    s.explosion_open_entry_enabled = True
    s.explosion_entry_earliest_hour = 9
    s.explosion_entry_earliest_minute = 15
    s.entry_earliest_hour = 9
    s.entry_earliest_minute = 20

    ok, reason = explosion_entries_allowed_now()
    assert ok is True
    assert "explosion_open_window" in reason
