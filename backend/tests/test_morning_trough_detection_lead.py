"""Aug26 SENSEX 77800 PE morning — detect V-lift off chain day-low before velocity history."""

from unittest.mock import MagicMock, patch

import pytest

from app.engines.explosion_detector import (
    _expiry_trough_first_tick_scan_ok,
    _open_key,
    _session_low,
    apply_day_extremes_baseline,
    reset_detector_state_for_tests,
    scan_chain_explosions,
)
from app.models.schemas import Side


def _settings() -> MagicMock:
    s = MagicMock()
    s.explosion_scan_range = 1500
    s.explosion_sensex_scan_range = 1500
    s.explosion_scan_atm_itm_only = True
    s.min_option_premium_inr = 18.0
    s.explosion_max_premium_inr = 650.0
    s.max_option_premium_inr = 300.0
    s.explosion_ict_max_premium_inr = 800.0
    s.expiry_itm_explosion_scan_max_premium_inr = 900.0
    s.expiry_day_min_option_premium_inr = 15.0
    s.open_premium_explosion_enabled = True
    s.open_premium_min_move_pct = 25.0
    s.all_day_explosion_session_move_min_pct = 40.0
    s.all_day_explosion_min_score = 45.0
    s.explosion_exhaustion_v15_pct = 18.0
    s.explosion_cheap_rip_min_premium_inr = 12.0
    s.explosion_cheap_rip_min_peak_pct = 28.0
    s.expiry_trough_scan_enabled = True
    s.expiry_trough_first_tick_min_off_low_pct = 3.0
    s.expiry_trough_first_tick_max_off_low_pct = 18.0
    s.expiry_trough_first_tick_min_score_boost = 10.0
    s.expiry_atm_tier_velocity_mult = 1.0
    s.peak_move_explosion_min_pct = 35.0
    s.session_day_ohlc_extremes_enabled = True
    s.session_day_ohlc_max_dev_mult = 8.0
    s.session_open_use_intraday_low = True
    s.session_open_low_backfill_pct = 5.0
    s.session_move_min_baseline_premium = 5.0
    s.explosion_atm_proximity_bonus_max = 8.0
    s.explosion_otm_depth_penalty_per_step = 3.0
    s.velocity_peak_score_boost_enabled = False
    s.ict_first_lift_appear_enabled = True
    s.building_rip_local_base_lift_enabled = True
    s.building_rip_local_base_min_velocity_3s = 1.2
    s.building_rip_local_base_max_move_pct = 15.0
    s.building_rip_promote_to_exploding = True
    s.building_rip_min_velocity_3s = 1.5
    s.building_rip_min_velocity_9s = 0.8
    s.building_rip_min_volume_surge = 1.8
    s.building_rip_min_move_pct = 2.0
    s.building_rip_max_move_pct = 55.0
    s.explosion_volume_awaken_min = 25000
    s.explosion_volume_awaken_min_velocity_3s = 1.0
    s.moneyness_atm_tolerance_points = 50.0
    s.nifty_strike_step = 50.0
    s.sensex_strike_step = 100.0
    s.banknifty_strike_step = 100.0
    s.explosion_shallow_otm_history_steps = 1
    s.explosion_shallow_otm_history_min_volume = 25000
    return s


def test_expiry_trough_first_tick_ok_at_five_pct_off_low():
    reset_detector_state_for_tests()
    ok, off = _expiry_trough_first_tick_scan_ok(
        symbol="SENSEX",
        strike=77800.0,
        side=Side.PUT,
        premium=100.0,
        hist=None,
        expiry_day=True,
        near_atm=True,
        moneyness="ATM",
        day_low=95.0,
        settings=_settings(),
    )
    assert ok is True
    assert off == pytest.approx(5.263, rel=0.01)


def test_expiry_trough_first_tick_rejects_without_day_low():
    reset_detector_state_for_tests()
    ok, _ = _expiry_trough_first_tick_scan_ok(
        symbol="SENSEX",
        strike=77800.0,
        side=Side.PUT,
        premium=100.0,
        hist=None,
        expiry_day=True,
        near_atm=True,
        moneyness="ATM",
        day_low=0.0,
        settings=_settings(),
    )
    assert ok is False


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
@patch("app.config.get_settings")
def test_scan_detects_aug26_77800_pe_lift_off_trough_first_tick(mock_get_settings, _open):
    """₹95 trough → ₹105 lift on first poll must emit WATCH, not wait for 25% open_move."""
    reset_detector_state_for_tests()
    mock_get_settings.return_value = _settings()

    chain = [{
        "strike_price": 77800,
        "put_options": {
            "ltp": 105.0,
            "volume": 80_000,
            "day_low": 95.0,
            "day_high": 108.0,
        },
        "call_options": {"ltp": 140.0, "volume": 50_000},
    }]
    events = scan_chain_explosions(
        "SENSEX", chain, spot=77700.0, atm=77800.0, expiry_day=True,
    )
    puts = [e for e in events if e.side == Side.PUT and e.strike == 77800]
    assert puts, "77800 PE must appear on first trough-lift scan"
    ev = puts[0]
    assert ev.tier in ("WATCH", "BUILDING", "EXPLODING")
    assert ev.explosion_score >= 10.0
    assert "trough" in ev.reason.lower()


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
@patch("app.config.get_settings")
def test_scan_uses_seeded_session_low_on_ws_rescan(mock_get_settings, _open):
    """After REST seeds day-low, WS heatmap rescan without OHLC still detects lift."""
    reset_detector_state_for_tests()
    mock_get_settings.return_value = _settings()

    key = _open_key("SENSEX", 77800.0, Side.PUT)
    apply_day_extremes_baseline(key, 108.0, day_low=95.0, day_high=108.0)
    assert _session_low[key] == 95.0

    chain = [{
        "strike_price": 77800,
        "put_options": {"ltp": 108.0, "volume": 0},
        "call_options": {"ltp": 140.0, "volume": 0},
    }]
    events = scan_chain_explosions(
        "SENSEX", chain, spot=77700.0, atm=77800.0, expiry_day=True,
    )
    puts = [e for e in events if e.side == Side.PUT and e.strike == 77800]
    assert puts
    assert puts[0].tier in ("WATCH", "BUILDING", "EXPLODING")


def test_first_poll_preserves_chain_day_low_trough():
    """First LTP poll must not clobber chain day-low already on the session key."""
    reset_detector_state_for_tests()
    key = _open_key("SENSEX", 77800.0, Side.PUT)
    apply_day_extremes_baseline(key, 198.0, day_low=95.0, day_high=220.0)
    from app.engines.explosion_detector import _session_open_move_pct, _history, _record

    _record("SENSEX", 77800.0, Side.PUT, 108.0, 0)
    hist = _history["SENSEX"]["PUT:77800.0"]
    move = _session_open_move_pct("SENSEX", 77800.0, Side.PUT, 108.0, hist)
    assert _session_low[key] == 95.0
    assert move >= 10.0
