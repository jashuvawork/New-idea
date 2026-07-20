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
    s.morning_capture_start_hour = 9
    s.morning_capture_start_minute = 15
    s.morning_capture_end_hour = 11
    s.morning_capture_end_minute = 45
    s.morning_capture_min_rank_score = 48.0
    s.morning_capture_building_min_score = 38.0
    s.morning_capture_min_velocity_3s = 2.0
    s.morning_capture_min_velocity_9s = 2.8
    s.morning_capture_building_min_velocity_3s = 2.0
    s.morning_capture_min_vol_surge = 1.3
    s.morning_capture_skip_chart_on_extreme_velocity = True
    s.morning_capture_extreme_velocity_3s = 3.0
    s.morning_capture_extreme_velocity_9s = 4.0
    s.all_day_explosion_capture_enabled = True
    s.all_day_explosion_start_hour = 9
    s.all_day_explosion_start_minute = 20
    s.all_day_explosion_end_hour = 15
    s.all_day_explosion_end_minute = 25
    s.all_day_explosion_min_score = 38.0
    s.all_day_explosion_session_move_min_pct = 40.0
    s.all_day_explosion_extreme_move_min_pct = 80.0
    s.explosion_immature_min_session_move_pct = 22.0
    s.explosion_immature_block_enabled = True
    s.explosion_volume_awaken_min = 2.2
    s.explosion_chop_min_session_move_pct = 28.0
    s.explosion_early_window_max_move_pct = 55.0
    s.ict_breakout_monitor_enabled = True
    s.ict_fvg_min_gap_pct = 1.2
    s.ict_flat_base_max_range_pct = 8.0
    s.ict_flat_base_lookback_seconds = 180
    s.ict_displacement_min_velocity_3s = 2.8
    s.ict_vertical_min_session_move_pct = 35.0
    s.ict_early_vertical_min_session_move_pct = 28.0
    s.ict_early_vertical_min_velocity_3s = 2.0
    s.ict_mega_rip_min_session_move_pct = 90.0
    s.ict_volume_surge_awaken_min = 3.0
    s.ict_fvg_score_bonus = 18.0
    s.ict_flat_vertical_score_bonus = 22.0
    s.ict_early_breakout_score_bonus = 16.0
    s.ict_mega_rip_score_bonus = 28.0
    s.ict_breakout_min_score = 42.0
    s.ict_late_chase_block_enabled = True
    s.ict_late_chase_min_peak_pct = 75.0
    s.ict_late_chase_max_live_velocity_3s = 1.0
    s.afternoon_premium_capture_enabled = False
    s.premium_led_counter_breadth_enabled = True
    s.premium_led_min_velocity_3s = 2.8
    s.premium_led_min_velocity_9s = 3.5
    s.premium_led_min_explosion_score = 42.0
    s.premium_led_counter_breadth_min_score = 90.0
    s.premium_led_elite_counter_min_score = 90.0
    s.whipsaw_single_side_surge_bypass_enabled = True
    s.whipsaw_dominant_velocity_min = 2.5
    s.whipsaw_dominant_velocity_ratio = 1.6
    s.open_premium_min_move_pct = 25.0
    s.open_premium_bypass_min_score = 35.0
    s.open_premium_chart_bypass_move_pct = 20.0
    s.open_premium_relax_velocity_3s = 1.8
    s.open_premium_relax_velocity_9s = 2.5
    s.afternoon_capture_dominant_velocity_min = 1.6
    s.afternoon_capture_dominant_velocity_ratio = 1.4
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
@patch("app.engines.chop_day_guards._minutes_now", return_value=9 * 60 + 20)
@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
def test_morning_window_915_active_at_open(mock_settings, mock_mins, mock_phase):
    assert in_morning_premium_capture_window() is True


@patch("app.engines.morning_premium_capture.get_market_phase", return_value="LIVE_MARKET")
@patch("app.engines.chop_day_guards._minutes_now", return_value=10 * 60 + 20)
@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
def test_morning_window_1020_active(mock_settings, mock_mins, mock_phase):
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


@patch("app.engines.ict_breakout_monitor.get_settings", return_value=_settings())
@patch("app.config.get_settings", return_value=_settings())
@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
@patch("app.engines.morning_premium_capture.in_morning_premium_capture_window", return_value=True)
def test_event_to_dict_marks_building_tradeable(mock_window, mock_settings, mock_cfg, mock_ict):
    # Morning BUILDING capture stays tradeable even when session move is still small.
    d = event_to_dict(_building_event(daily_move_pct=12.0, peak_move_pct=12.0))
    assert d["morningCapture"] is True
    assert d["tradeable"] is True


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


@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
@patch("app.engines.morning_premium_capture.in_morning_premium_capture_window", return_value=True)
def test_extreme_velocity_bypasses_bearish_chart(mock_window, mock_settings):
    """NIFTY 24350 CE style — premium rips while index chart still bearish."""
    chart = SpotChart(direction="BEARISH", momentum5Pct=-0.05, macdBias="BEARISH", rsi=42)
    event = _building_event(velocity_3s=3.2, velocity_9s=4.5, explosion_score=48.0, tier="ELITE")
    assert is_morning_capture_event(event, chart=chart) is True


@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
@patch("app.engines.morning_premium_capture.in_morning_premium_capture_window", return_value=True)
def test_premium_led_allows_counter_breadth_ce(mock_window, mock_settings):
    from app.engines.morning_premium_capture import premium_led_entry_allowed

    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase="LIVE_MARKET",
        dataAvailable=True,
        explosionAlerts=[
            {
                "symbol": "NIFTY",
                "side": "CALL",
                "strike": 24350,
                "premium": 98.75,
                "velocity3s": 3.1,
                "velocity9s": 4.2,
                "explosionScore": 48.0,
                "tier": "ELITE",
            }
        ],
    )
    assert premium_led_entry_allowed(Side.CALL, snap) is True


@patch("app.engines.morning_premium_capture.get_settings", return_value=_settings())
def test_dominant_single_side_not_dual_whipsaw(mock_settings):
    from app.engines.morning_premium_capture import dominant_single_side_surge
    from app.models.schemas import Breadth, Regime

    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase="LIVE_MARKET",
        dataAvailable=True,
        regime=Regime.CHOP,
        breadth=Breadth(bias="BEARISH", score=65, aligned=False),
        explosiveRunnerWatchlist=[
            {"side": "CALL", "premiumVelocityPct": 3.5, "score": 72},
            {"side": "PUT", "premiumVelocityPct": 1.1, "score": 50},
        ],
    )
    assert dominant_single_side_surge(snap) is True
