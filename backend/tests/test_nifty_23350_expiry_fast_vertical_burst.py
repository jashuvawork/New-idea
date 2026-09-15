"""Sep15 NIFTY 23350 PE — live mid-rip detect before post-peak radar (CE/PE symmetric)."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.expiry_day_guards import check_expiry_entry_allowed
from app.engines.expiry_fast_vertical_burst import expiry_fast_vertical_burst_from_run
from app.engines.explosion_detector import (
    LOCAL_BASE_HIST_MAXLEN,
    _history,
    _local_base_hist,
    _open_key,
    _strike_key,
    event_to_dict,
    key_for_symbol,
    recent_premium_run,
    reset_detector_state_for_tests,
    scan_chain_explosions,
)
from app.models.schemas import AutoTraderState, MarketPhase, Side, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


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
    s.expiry_trough_first_tick_max_off_low_pct = 35.0
    s.expiry_trough_first_tick_min_score_boost = 10.0
    s.expiry_fast_vertical_burst_enabled = True
    s.expiry_fast_vertical_burst_lookback_seconds = 180.0
    s.expiry_fast_vertical_burst_min_run_pct = 28.0
    s.expiry_fast_vertical_burst_min_off_extreme_pct = 3.0
    s.expiry_fast_vertical_burst_max_off_extreme_pct = 50.0
    s.expiry_fast_vertical_burst_max_hist_len = 12
    s.expiry_fast_vertical_burst_min_volume = 15000.0
    s.expiry_fast_vertical_burst_volume_bypass_run_pct = 45.0
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
    s.explosion_immature_min_session_move_pct = 28.0
    s.ict_structured_early_min_move_pct = 15.0
    s.ict_structured_early_max_move_pct = 65.0
    s.elite_local_base_max_move_pct = 40.0
    s.expiry_fast_vertical_burst_halt_bypass_enabled = True
    s.expiry_day_guards_enabled = True
    s.expiry_worst_day_halt_entries = True
    s.expiry_worst_day_score_threshold = 55.0
    s.ict_breakout_monitor_enabled = False
    return s


def test_fast_vertical_burst_ok_mid_rip_off_base():
    ok, off, run = expiry_fast_vertical_burst_from_run(
        {"low": 20.0, "high": 28.0, "current": 27.0, "run": 0.40, "off_low": 0.35},
        hist=None,
        effective_volume=40_000,
        settings=_settings(),
    )
    assert ok is True
    assert off == pytest.approx(35.0, rel=0.01)
    assert run == pytest.approx(40.0, rel=0.01)


def test_fast_vertical_burst_call_mirror_mid_rip():
    """CE mirror — CALL off window low during expiry vertical."""
    ok, off, run = expiry_fast_vertical_burst_from_run(
        {"low": 80.0, "high": 108.0, "current": 105.0, "run": 0.35, "off_low": 0.3125},
        hist=None,
        effective_volume=40_000,
        settings=_settings(),
    )
    assert ok is True
    assert off == pytest.approx(31.25, rel=0.01)
    assert run == pytest.approx(35.0, rel=0.01)


def test_fast_vertical_burst_rejects_post_peak_chase():
    ok, _, _ = expiry_fast_vertical_burst_from_run(
        {"low": 20.0, "high": 53.0, "current": 52.0, "run": 1.65, "off_low": 1.60},
        hist=None,
        effective_volume=40_000,
        settings=_settings(),
    )
    assert ok is False


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
@patch("app.config.get_settings")
def test_scan_detects_nifty_23350_pe_mid_vertical(mock_get_settings, _open):
    """Sep15-style ₹20→₹28 mid-rip must emit fastVerticalBurst before post-peak detect."""
    reset_detector_state_for_tests()
    mock_get_settings.return_value = _settings()

    base = datetime(2026, 9, 15, 10, 0, tzinfo=IST)
    premiums = [20.0, 20.2, 21.0, 22.5, 24.0, 27.5]
    strike_key = _strike_key(23350.0, Side.PUT)
    lb_key = key_for_symbol("NIFTY", strike_key)
    lb_dq = deque(maxlen=LOCAL_BASE_HIST_MAXLEN)
    hist_dq = deque(maxlen=20)
    for i, prem in enumerate(premiums):
        ts = base + timedelta(seconds=i * 25)
        lb_dq.append((ts, prem))
        hist_dq.append((ts, prem, 35_000))
    _local_base_hist[lb_key] = lb_dq
    _history.setdefault("NIFTY", {})[strike_key] = hist_dq

    run = recent_premium_run("NIFTY", 23350.0, Side.PUT, lookback_seconds=180.0)
    assert run["run"] >= 0.28

    chain = [{
        "strike_price": 23350,
        "put_options": {
            "ltp": 27.5,
            "volume": 35_000,
            "day_low": 10.4,
            "day_high": 28.0,
        },
        "call_options": {"ltp": 140.0, "volume": 50_000},
    }]
    events = scan_chain_explosions(
        "NIFTY", chain, spot=23340.0, atm=23350.0, expiry_day=True,
    )
    puts = [e for e in events if e.side == Side.PUT and e.strike == 23350]
    assert puts, "23350 PE must appear on mid-rip fast burst scan"
    ev = puts[0]
    assert ev.expiry_fast_vertical_burst is True
    assert "fastVerticalBurst" in ev.reason
    assert ev.tier in ("BUILDING", "EXPLODING", "ELITE")

    alert = event_to_dict(ev)
    assert alert.get("expiryFastVerticalBurst") is True


@patch("app.config.get_settings")
def test_expiry_worst_day_halt_bypasses_on_fast_vertical_radar(mock_get_settings):
    mock_get_settings.return_value = _settings()
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime(2026, 9, 15, 10, 5, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=23340.0,
        atmStrike=23350.0,
        explosionAlerts=[{
            "symbol": "NIFTY",
            "side": "PUT",
            "strike": 23350.0,
            "tier": "EXPLODING",
            "expiryFastVerticalBurst": True,
            "tradeable": True,
            "explosionScore": 45.0,
            "premium": 27.5,
        }],
    )
    with patch(
        "app.engines.expiry_day_guards.is_expiry_session",
        return_value=True,
    ), patch(
        "app.engines.expiry_day_guards.predict_worst_expiry_day",
        return_value=(True, 65.0, ["chop_regime", "declining_session"]),
    ), patch(
        "app.engines.expiry_day_guards._session_declining",
        return_value=True,
    ), patch(
        "app.engines.expiry_day_guards.in_expiry_morning_window",
        return_value=True,
    ):
        ok, reason, meta = check_expiry_entry_allowed(AutoTraderState(), {"NIFTY": snap})
    assert ok is True
    assert meta.get("expiryFastVerticalBurstBypass") is True
