"""Morning slow-bounce window + explosion exhaustion reset + near-expiry premium cap."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.explosion_detector import ExplosionEvent
from app.engines.expiry_day_guards import (
    in_morning_slow_bounce_window,
    slow_bounce_premium_max_inr,
    slow_bounce_session_active,
)
from app.engines.quick_sideways import detect_slow_bounce_signal
from app.engines.rally_capture import explosion_exhausted
from app.models.schemas import Breadth, MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _sensex_near_expiry_snap(**chart_kw) -> SymbolSnapshot:
    today = datetime.now(IST).strftime("%Y-%m-%d")
    chart = SpotChart(
        direction="NEUTRAL",
        spot=77800.0,
        momentum5Pct=0.15,
        trendStrength=30.0,
        emaBias="BEARISH",
        rsi=58.0,
        rsiBias="NEUTRAL",
        macd=6.7,
        macdSignal=6.88,
        macdHistogram=-0.5,
        macdBias="BEARISH",
        **chart_kw,
    )
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry=today,
        spot=77800.0,
        atmStrike=77800.0,
        tradeQualityScore=35.0,
        breadth=Breadth(bias="NEUTRAL", score=52, aligned=False),
        spotChart=chart,
    )


@patch("app.services.upstox.get_market_phase", return_value="LIVE_MARKET")
@patch("app.engines.expiry_day_guards._minutes_now", return_value=11 * 60 + 15)
@patch("app.engines.expiry_day_guards.get_settings")
def test_morning_slow_bounce_window_active(mock_settings, mock_minutes, mock_phase):
    s = mock_settings.return_value
    s.morning_slow_bounce_enabled = True
    s.morning_slow_bounce_start_hour = 10
    s.morning_slow_bounce_start_minute = 30
    s.morning_slow_bounce_end_hour = 13
    s.morning_slow_bounce_end_minute = 30
    assert in_morning_slow_bounce_window() is True


@patch("app.engines.expiry_day_guards.in_expiry_pm_itm_window", return_value=False)
@patch("app.engines.expiry_day_guards.in_morning_slow_bounce_window", return_value=True)
def test_slow_bounce_session_active_morning_near_expiry(mock_morning, mock_pm):
    snap = _sensex_near_expiry_snap()
    assert slow_bounce_session_active(snap) is True


@patch("app.engines.expiry_day_guards.is_near_expiry_day", return_value=True)
@patch("app.engines.expiry_day_guards.get_settings")
def test_premium_216_allowed_near_expiry(mock_settings, mock_near):
    s = mock_settings.return_value
    s.expiry_pm_itm_premium_max_inr = 280.0
    s.expiry_near_expiry_premium_max_inr = 300.0
    snap = _sensex_near_expiry_snap()
    assert slow_bounce_premium_max_inr(snap) == 300.0


@patch("app.engines.quick_sideways._is_morning_slow_bounce", return_value=True)
@patch("app.engines.quick_sideways.get_settings")
@patch("app.engines.expiry_day_guards.is_near_expiry_day", return_value=True)
@patch("app.engines.expiry_day_guards.slow_bounce_premium_max_inr", return_value=300.0)
def test_detect_slow_bounce_rsi_58_morning(mock_prem, mock_near, mock_settings, mock_morning):
    s = mock_settings.return_value
    s.quick_sideways_slow_bounce_enabled = True
    s.quick_sideways_slow_bounce_premium_min_inr = 90.0
    s.morning_slow_bounce_rsi_min = 45.0
    s.morning_slow_bounce_rsi_max = 60.0
    s.quick_sideways_slow_bounce_rsi_min = 40.0
    s.quick_sideways_slow_bounce_rsi_max = 55.0
    s.morning_slow_bounce_macd_hist_min = -20.0
    s.quick_sideways_slow_bounce_macd_hist_min = -15.0

    snap = _sensex_near_expiry_snap()
    with patch("app.engines.moneyness.classify_moneyness", return_value="ITM"):
        ok, reason, meta = detect_slow_bounce_signal(snap, Side.PUT, 77600.0, 216.0)
    assert ok is True
    assert reason == "slow_bounce"
    assert meta["rsi"] == 58.0


@patch("app.engines.rally_capture.get_settings")
def test_explosion_exhausted_resets_in_consolidation(mock_settings):
    s = mock_settings.return_value
    s.explosion_exhaustion_consolidation_reset_enabled = True
    s.explosion_exhaustion_v15_pct = 18.0
    s.explosion_exhaustion_consolidation_v3_max = 1.2
    s.explosion_exhaustion_consolidation_v9_max = 2.0
    s.explosion_exhaustion_reset_minutes = 12

    event = ExplosionEvent(
        symbol="SENSEX",
        side=Side.PUT,
        strike=77600.0,
        premium=216.0,
        velocity_3s=0.5,
        velocity_9s=0.8,
        velocity_15s=45.0,
        volume_surge=1.1,
        explosion_score=40.0,
        tier="BUILDING",
        reason="consolidation",
    )
    blocked, reason = explosion_exhausted(event)
    assert blocked is False
    assert reason == "ok"


@patch("app.engines.rally_capture.get_settings")
def test_explosion_exhausted_blocks_hot_chase(mock_settings):
    s = mock_settings.return_value
    s.explosion_exhaustion_consolidation_reset_enabled = True
    s.explosion_exhaustion_v15_pct = 18.0
    s.explosion_exhaustion_consolidation_v3_max = 1.2
    s.explosion_exhaustion_consolidation_v9_max = 2.0
    s.explosion_exhaustion_reset_minutes = 12

    event = ExplosionEvent(
        symbol="SENSEX",
        side=Side.PUT,
        strike=77600.0,
        premium=250.0,
        velocity_3s=1.0,
        velocity_9s=2.5,
        velocity_15s=40.0,
        volume_surge=1.0,
        explosion_score=55.0,
        tier="EXPLODING",
        reason="fading",
    )
    blocked, reason = explosion_exhausted(event)
    assert blocked is True
    assert reason.startswith("explosion_exhausted_v15")
