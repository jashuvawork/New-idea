"""Open premium explosion — NIFTY PE 60→160 style session-open rips."""

from unittest.mock import patch

from app.engines.explosion_detector import (
    ExplosionEvent,
    _session_open,
    _session_peak,
    _tier_sticky,
    scan_chain_explosions,
)
from app.engines.explosion_profit import check_explosion_entry
from app.engines.morning_premium_capture import (
    is_morning_capture_event,
    premium_led_explosion_bypass,
)
from app.models.schemas import (
    Breadth,
    MarketPhase,
    Side,
    SpotChart,
    StrategyType,
    SuggestedTrade,
    SymbolSnapshot,
)


def _chain_row(strike: float, put_ltp: float) -> dict:
    return {
        "strike_price": strike,
        "put_options": {"ltp": put_ltp, "volume": 50000},
    }


@patch("app.engines.session_timing.in_open_premium_window", return_value=True)
@patch("app.config.get_settings")
def test_open_move_detected_without_poll_history(mock_settings, mock_open):
    _session_open.clear()
    _session_peak.clear()
    _tier_sticky.clear()
    s = mock_settings.return_value
    s.open_premium_explosion_enabled = True
    s.open_premium_min_move_pct = 25.0
    s.min_option_premium_inr = 20.0
    s.explosion_max_premium_inr = 400.0
    s.explosion_scan_range = 500.0
    s.all_day_explosion_session_move_min_pct = 25.0

    chain = [_chain_row(24200, 60.0)]
    scan_chain_explosions("NIFTY", chain, spot=24050.0, atm=24050.0)
    events = scan_chain_explosions("NIFTY", chain, spot=24050.0, atm=24050.0)
    events = [e for e in events if e.strike == 24200 and e.side == Side.PUT]
    assert not events

    chain2 = [_chain_row(24200, 130.0)]
    events = scan_chain_explosions("NIFTY", chain2, spot=24050.0, atm=24050.0)
    pe = [e for e in events if e.strike == 24200 and e.side == Side.PUT]
    assert pe
    assert pe[0].daily_move_pct >= 100
    assert pe[0].tier in ("EXPLODING", "ELITE", "BUILDING")


@patch("app.engines.morning_premium_capture.in_morning_premium_capture_window", return_value=True)
@patch("app.engines.morning_premium_capture.get_settings")
def test_morning_capture_accepts_open_rip_put(mock_settings, mock_win):
    s = mock_settings.return_value
    s.morning_premium_capture_enabled = True
    s.morning_capture_building_min_score = 38.0
    s.morning_capture_min_velocity_3s = 2.0
    s.morning_capture_min_velocity_9s = 2.8
    s.morning_capture_building_min_velocity_3s = 2.0
    s.morning_capture_min_vol_surge = 1.3
    s.morning_capture_skip_chart_on_extreme_velocity = True
    s.morning_capture_extreme_velocity_3s = 3.0
    s.morning_capture_extreme_velocity_9s = 4.0
    s.open_premium_min_move_pct = 25.0
    s.open_premium_chart_bypass_move_pct = 20.0

    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.PUT,
        strike=24200.0,
        premium=130.0,
        velocity_3s=35.0,
        velocity_9s=116.0,
        velocity_15s=116.0,
        volume_surge=1.5,
        explosion_score=72.0,
        tier="EXPLODING",
        reason="open+117%",
        daily_move_pct=116.0,
    )
    chart = SpotChart(direction="BULLISH", spot=24050.0, momentum5Pct=0.05, emaBias="BULLISH")
    assert is_morning_capture_event(event, chart=chart) is True


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.morning_premium_capture.in_premium_capture_window", return_value=True)
@patch("app.engines.morning_premium_capture.get_settings")
def test_open_rip_put_blocked_on_bullish_without_elite(mock_settings, mock_window, mock_ep_settings):
    s = mock_settings.return_value
    ep = mock_ep_settings.return_value
    for cfg in (s, ep):
        cfg.premium_led_explosion_bypass_enabled = True
        cfg.premium_led_counter_breadth_enabled = True
        cfg.premium_led_elite_counter_min_score = 90.0
        cfg.chart_min_trend_strength = 25.0
        cfg.open_premium_min_move_pct = 25.0
        cfg.aggressive_min_explosion_score = 45
        cfg.explosion_breadth_alignment_enabled = True
        cfg.chart_alignment_enabled = True

    chart = SpotChart(direction="BULLISH", spot=24050.0, trendStrength=35.0, emaBias="BULLISH")
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.PUT,
        strike=24200.0,
        premium=130.0,
        velocity_3s=35.0,
        velocity_9s=116.0,
        velocity_15s=116.0,
        volume_surge=2.0,
        explosion_score=72.0,
        tier="EXPLODING",
        reason="open+117%",
        daily_move_pct=116.0,
    )
    assert premium_led_explosion_bypass(event, chart, "BULLISH") is False


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.morning_premium_capture.in_premium_capture_window", return_value=True)
@patch("app.engines.morning_premium_capture.get_settings")
def test_open_rip_put_passes_explosion_entry_elite_on_bullish(mock_settings, mock_window, mock_ep_settings):
    s = mock_settings.return_value
    ep = mock_ep_settings.return_value
    for cfg in (s, ep):
        cfg.premium_led_explosion_bypass_enabled = True
        cfg.premium_led_counter_breadth_enabled = True
        cfg.premium_led_elite_counter_min_score = 90.0
        cfg.open_premium_min_move_pct = 25.0
        cfg.open_premium_bypass_min_score = 35.0
        cfg.morning_capture_extreme_velocity_3s = 3.0
        cfg.morning_capture_extreme_velocity_9s = 4.0
        cfg.premium_led_min_velocity_3s = 2.8
        cfg.premium_led_min_velocity_9s = 3.5
        cfg.premium_led_min_explosion_score = 42.0
        cfg.morning_capture_building_min_velocity_3s = 2.0
        cfg.morning_capture_min_velocity_9s = 2.8
        cfg.morning_capture_min_vol_surge = 1.3
        cfg.morning_capture_building_min_score = 38.0
        cfg.aggressive_min_explosion_score = 45
        cfg.explosion_breadth_alignment_enabled = True
        cfg.chart_alignment_enabled = True
        cfg.chart_min_trend_strength = 25.0
        cfg.index_pin_put_block_enabled = False
        cfg.explosion_exhaustion_consolidation_reset_enabled = True
        cfg.explosion_exhaustion_v15_pct = 18.0
        cfg.explosion_exhaustion_consolidation_v3_max = 1.2
        cfg.explosion_exhaustion_consolidation_v9_max = 2.0
        cfg.explosion_exhaustion_reset_minutes = 12
        cfg.neutral_breadth_min_score = 60
        cfg.neutral_breadth_explosion_min_score = 55

    chart = SpotChart(direction="BULLISH", spot=24050.0, trendStrength=35.0, emaBias="BULLISH")
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.PUT,
        strike=24200.0,
        premium=130.0,
        velocity_3s=35.0,
        velocity_9s=116.0,
        velocity_15s=116.0,
        volume_surge=2.0,
        explosion_score=95.0,
        tier="ELITE",
        reason="open+117%",
        daily_move_pct=116.0,
    )
    assert premium_led_explosion_bypass(event, chart, "BULLISH") is False

    trade = SuggestedTrade(
        id="t1", symbol="NIFTY", side=Side.PUT, strike=24200.0,
        lastPremium=130.0, tqs=50, strategyType=StrategyType.EXPLOSIVE, confidence=95,
    )
    ok, reason = check_explosion_entry(
        event, trade, Breadth(bias="BULLISH", score=62, aligned=True), False,
        chart=chart,
    )
    assert ok is True
    assert reason == "extreme_all_in_explosion_confirmed"
