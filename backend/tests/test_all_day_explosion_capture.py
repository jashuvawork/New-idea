"""All-day explosive capture — 14:00 PE rips, premium-led vs bullish chart."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_profit import check_explosion_entry
from app.engines.morning_premium_capture import (
    in_all_day_explosion_window,
    is_all_day_explosion_event,
    premium_led_explosion_bypass,
)
from app.engines.rally_capture import cross_side_chase_blocked, dominant_explosion_alert
from app.models.schemas import (
    Breadth,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    SuggestedTrade,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _pe_rip_event() -> ExplosionEvent:
    return ExplosionEvent(
        symbol="NIFTY",
        side=Side.PUT,
        strike=23850.0,
        premium=183.35,
        velocity_3s=45.0,
        velocity_9s=120.0,
        velocity_15s=8.0,
        volume_surge=3.5,
        explosion_score=72.0,
        tier="EXPLODING",
        reason="open+358%",
        daily_move_pct=358.0,
    )


def _bullish_chart() -> SpotChart:
    return SpotChart(direction="BULLISH", momentum5Pct=0.15, trendStrength=55)


def _snap_with_alerts() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry="2026-07-14",
        spot=24200.0,
        atmStrike=24200.0,
        regime=Regime.CHOP,
        tradeQualityScore=35.0,
        breadth=Breadth(bias="BEARISH", score=50, aligned=True),
        spotChart=_bullish_chart(),
        explosionAlerts=[
            {
                "symbol": "NIFTY",
                "side": "PUT",
                "strike": 23850.0,
                "premium": 183.35,
                "velocity3s": 45.0,
                "velocity9s": 120.0,
                "explosionScore": 72.0,
                "tier": "EXPLODING",
                "dailyMovePct": 358.0,
                "tradeable": True,
            },
            {
                "symbol": "NIFTY",
                "side": "CALL",
                "strike": 24200.0,
                "premium": 140.0,
                "velocity3s": 1.2,
                "velocity9s": 1.5,
                "explosionScore": 28.0,
                "tier": "WATCH",
                "tradeable": False,
            },
        ],
    )


@patch("app.engines.morning_premium_capture.get_market_phase", return_value="LIVE_MARKET")
@patch("app.engines.chop_day_guards._minutes_now", return_value=14 * 60 + 10)
def test_all_day_window_covers_14_00(mock_min, mock_phase):
    assert in_all_day_explosion_window() is True


@patch("app.engines.morning_premium_capture.in_all_day_explosion_window", return_value=True)
@patch("app.engines.morning_premium_capture.get_settings")
def test_all_day_event_detects_session_rip(mock_settings, mock_window):
    s = mock_settings.return_value
    s.all_day_explosion_capture_enabled = True
    s.all_day_explosion_session_move_min_pct = 40.0
    s.all_day_explosion_extreme_move_min_pct = 80.0
    s.all_day_explosion_min_score = 38.0
    s.all_day_explosion_building_min_velocity_3s = 2.0
    s.all_day_explosion_min_velocity_9s = 2.5
    s.all_day_explosion_chart_bypass_move_pct = 50.0
    s.morning_capture_extreme_velocity_3s = 4.0
    s.morning_capture_extreme_velocity_9s = 6.0
    s.afternoon_capture_chart_bypass_vol_surge = 1.5

    event = _pe_rip_event()
    assert is_all_day_explosion_event(event, chart=_bullish_chart()) is True


@patch("app.engines.morning_premium_capture.in_premium_capture_window", return_value=True)
@patch("app.engines.morning_premium_capture.get_settings")
def test_premium_led_bypass_put_vs_bullish_chart(mock_settings, mock_window):
    s = mock_settings.return_value
    s.premium_led_explosion_bypass_enabled = True
    s.premium_led_counter_breadth_enabled = True
    s.premium_led_elite_counter_min_score = 90.0
    s.chart_min_trend_strength = 25.0
    s.open_premium_min_move_pct = 25.0
    s.open_premium_bypass_min_score = 35.0
    s.all_day_explosion_extreme_move_min_pct = 80.0
    s.premium_led_min_velocity_3s = 2.8
    s.premium_led_min_velocity_9s = 3.5
    s.premium_led_min_explosion_score = 42.0

    # Bearish breadth but bullish chart — still blocks non-elite PUT
    assert premium_led_explosion_bypass(_pe_rip_event(), _bullish_chart(), "BEARISH") is False
    elite = _pe_rip_event()
    elite.tier = "ELITE"
    elite.explosion_score = 95.0
    assert premium_led_explosion_bypass(elite, _bullish_chart(), "BEARISH") is True


@patch("app.engines.morning_premium_capture.get_settings")
def test_dominant_put_blocks_ce_chase(mock_settings):
    s = mock_settings.return_value
    s.all_day_explosion_dominant_min_score = 40.0
    s.all_day_explosion_session_move_min_pct = 40.0
    s.explosion_single_side_per_symbol = True
    s.explosion_dominant_side_min_score = 50.0

    snap = _snap_with_alerts()
    dom = dominant_explosion_alert(snap)
    assert dom is not None
    assert dom["side"] == "PUT"

    ce_event = ExplosionEvent(
        symbol="NIFTY", side=Side.CALL, strike=24200.0, premium=140.0,
        velocity_3s=1.2, velocity_9s=1.5, velocity_15s=1.0,
        volume_surge=1.1, explosion_score=28.0, tier="WATCH", reason="",
    )
    blocked, reason = cross_side_chase_blocked(ce_event, snap)
    assert blocked is True
    assert "put_blocks_call" in reason


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.morning_premium_capture.is_premium_capture_event", return_value=True)
@patch("app.engines.morning_premium_capture.is_all_day_explosion_event", return_value=True)
@patch("app.engines.morning_premium_capture.premium_led_explosion_bypass", return_value=True)
@patch("app.engines.morning_premium_capture.get_settings")
def test_check_explosion_entry_accepts_building_all_day(
    mock_settings, mock_bypass, mock_all_day, mock_capture, mock_exp_settings,
):
    s = mock_settings.return_value
    mock_exp_settings.return_value = s
    s.aggressive_min_explosion_score = 45.0
    s.all_day_explosion_min_score = 38.0
    s.all_day_explosion_session_move_min_pct = 40.0
    s.explosion_breadth_alignment_enabled = True
    s.index_pin_put_block_enabled = False
    s.explosion_exhaustion_v15_pct = 18.0
    s.explosion_exhaustion_consolidation_reset_enabled = True
    s.explosion_exhaustion_reset_minutes = 12.0
    s.explosion_exhaustion_consolidation_v3_max = 0.8
    s.explosion_exhaustion_consolidation_v9_max = 1.2
    s.neutral_breadth_min_score = 55.0
    s.chop_day_guards_enabled = True

    event = _pe_rip_event()
    event.tier = "BUILDING"
    event.explosion_score = 43.0
    trade = SuggestedTrade(
        id="x", symbol="NIFTY", side=Side.PUT, strike=23850.0,
        lastPremium=183.35, tqs=35.0, strategyType="EXPLOSIVE", confidence=43.0,
    )
    breadth = Breadth(bias="BEARISH", score=50, aligned=True)
    ok, reason = check_explosion_entry(
        event, trade, breadth, False, chart=_bullish_chart(),
    )
    assert ok is True
    assert "building" in reason or "premium" in reason
