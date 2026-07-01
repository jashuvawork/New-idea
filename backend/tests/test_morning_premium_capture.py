"""Morning premium capture tests — SENSEX 77800 CE style rallies."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_detector import ExplosionEvent, event_to_dict
from app.engines.morning_premium_capture import (
    in_morning_premium_capture_window,
    is_morning_capture_event,
    morning_capture_active,
)
from app.models.schemas import Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = MagicMock()
    s.morning_premium_capture_enabled = True
    s.morning_capture_start_hour = 10
    s.morning_capture_start_minute = 0
    s.morning_capture_end_hour = 11
    s.morning_capture_end_minute = 45
    s.morning_capture_min_rank_score = 48.0
    s.morning_capture_building_min_score = 38.0
    s.morning_capture_min_velocity_3s = 2.0
    s.morning_capture_min_velocity_9s = 2.8
    s.morning_capture_building_min_velocity_3s = 2.0
    s.morning_capture_min_vol_surge = 1.3
    return s


def _building_event(**kwargs) -> ExplosionEvent:
    defaults = dict(
        symbol="SENSEX",
        side=Side.CALL,
        strike=77800.0,
        premium=51.55,
        velocity_3s=2.57,
        velocity_9s=3.2,
        velocity_15s=4.0,
        volume_surge=1.6,
        explosion_score=46.5,
        tier="BUILDING",
        reason="+2.6%/3s vol×1.6",
    )
    defaults.update(kwargs)
    return ExplosionEvent(**defaults)


@patch("app.engines.morning_premium_capture.get_market_phase", return_value="LIVE_MARKET")
@patch("app.engines.chop_day_guards._minutes_now", return_value=10 * 60 + 20)
@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
def test_morning_window_10_20_active(mock_settings, mock_mins, mock_phase):
    assert in_morning_premium_capture_window() is True


@patch("app.engines.morning_premium_capture.get_market_phase", return_value="LIVE_MARKET")
@patch("app.engines.chop_day_guards._minutes_now", return_value=12 * 60)
@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
def test_morning_window_closed_after_1145(mock_settings, mock_mins, mock_phase):
    assert in_morning_premium_capture_window() is False


@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
@patch("app.engines.morning_premium_capture.in_morning_premium_capture_window", return_value=True)
def test_building_event_qualifies_like_sensex_77800_ce(mock_window, mock_settings):
    chart = SpotChart(direction="BULLISH", momentum5Pct=0.05, macdBias="BULLISH", rsi=58)
    assert is_morning_capture_event(_building_event(), chart=chart) is True


@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
@patch("app.engines.morning_premium_capture.in_morning_premium_capture_window", return_value=True)
def test_watch_tier_rejected(mock_window, mock_settings):
    assert is_morning_capture_event(_building_event(tier="WATCH", explosion_score=30)) is False


@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
@patch("app.engines.morning_premium_capture.in_morning_premium_capture_window", return_value=True)
def test_event_to_dict_marks_building_tradeable(mock_window, mock_settings):
    d = event_to_dict(_building_event())
    assert d["tradeable"] is True
    assert d["morningCapture"] is True


@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
@patch("app.engines.morning_premium_capture.in_morning_premium_capture_window", return_value=True)
def test_morning_capture_active_from_snapshots(mock_window, mock_settings):
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase="LIVE_MARKET",
        dataAvailable=True,
        explosionAlerts=[
            {
                "symbol": "SENSEX",
                "side": "CALL",
                "strike": 77800,
                "premium": 51.55,
                "velocity3s": 2.57,
                "velocity9s": 3.2,
                "velocity15s": 4.0,
                "volumeSurge": 1.6,
                "explosionScore": 46.5,
                "tier": "BUILDING",
            }
        ],
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.05, macdBias="BULLISH"),
    )
    assert morning_capture_active({"SENSEX": snap}) is True
