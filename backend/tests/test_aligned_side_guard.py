"""Hard breadth side alignment — no PUT on BULLISH / CALL on BEARISH."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.aligned_side_guard import breadth_hard_blocks_side, counter_breadth_side_blocked
from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_profit import check_explosion_entry
from app.engines.morning_premium_capture import (
    counter_trend_entry_allowed,
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

IST = ZoneInfo("Asia/Kolkata")


def _elite_put_event() -> ExplosionEvent:
    return ExplosionEvent(
        symbol="SENSEX",
        side=Side.PUT,
        strike=77100.0,
        premium=120.0,
        velocity_3s=5.0,
        velocity_9s=7.0,
        velocity_15s=10.0,
        volume_surge=2.5,
        explosion_score=95.0,
        tier="ELITE",
        reason="+5%/3s",
        daily_move_pct=45.0,
    )


def _bullish_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=77200.0,
        spotChart=SpotChart(
            direction="BULLISH",
            spot=77200.0,
            momentum5Pct=0.12,
            trendStrength=40.0,
            emaBias="BULLISH",
            macdBias="BULLISH",
        ),
        breadth=Breadth(score=68, bias="BULLISH", aligned=True),
    )


def _trade() -> SuggestedTrade:
    return SuggestedTrade(
        id="t1",
        symbol="SENSEX",
        side=Side.PUT,
        strike=77100.0,
        lastPremium=120.0,
        tqs=55,
        strategyType=StrategyType.EXPLOSIVE,
        confidence=95,
    )


def test_hard_block_put_on_bullish_breadth():
    blocked, reason = breadth_hard_blocks_side(Side.PUT, "BULLISH")
    assert blocked is True
    assert reason == "hard_block_put_vs_bullish_breadth"
    assert counter_breadth_side_blocked(Side.CALL, "BULLISH") is False


def test_hard_block_call_on_bearish_breadth():
    blocked, reason = breadth_hard_blocks_side(Side.CALL, "BEARISH")
    assert blocked is True
    assert reason == "hard_block_call_vs_bearish_breadth"


def test_neutral_breadth_allows_both_sides():
    assert breadth_hard_blocks_side(Side.PUT, "NEUTRAL") == (False, "ok")
    assert breadth_hard_blocks_side(Side.CALL, "NEUTRAL") == (False, "ok")


@patch("app.engines.morning_premium_capture.in_premium_capture_window", return_value=True)
@patch("app.engines.morning_premium_capture.get_settings")
def test_elite_put_blocked_on_bullish_breadth(mock_settings, _window):
    s = mock_settings.return_value
    s.premium_led_explosion_bypass_enabled = True
    s.premium_led_counter_breadth_enabled = True
    s.premium_led_elite_counter_min_score = 90.0
    s.breadth_hard_side_block_enabled = True

    event = _elite_put_event()
    chart = _bullish_snap().spotChart
    assert premium_led_explosion_bypass(event, chart, "BULLISH") is False
    assert counter_trend_entry_allowed(Side.PUT, _bullish_snap(), explosion_event=event) is False


@patch("app.engines.morning_premium_capture.in_premium_capture_window", return_value=True)
@patch("app.engines.morning_premium_capture.get_settings")
@patch("app.engines.explosion_profit.get_settings")
def test_explosion_entry_blocks_elite_put_on_rally(mock_explosion_settings, mock_morning_settings, _window):
    s = mock_morning_settings.return_value
    s.premium_led_explosion_bypass_enabled = True
    s.premium_led_counter_breadth_enabled = True
    s.breadth_hard_side_block_enabled = True
    s.explosion_breadth_alignment_enabled = True
    s.aggressive_min_explosion_score = 45
    mock_explosion_settings.return_value = s

    snap = _bullish_snap()
    ok, reason = check_explosion_entry(
        _elite_put_event(),
        _trade(),
        snap.breadth,
        False,
        chart=snap.spotChart,
        snap=snap,
    )
    assert ok is False
    assert reason == "hard_block_put_vs_bullish_breadth"
