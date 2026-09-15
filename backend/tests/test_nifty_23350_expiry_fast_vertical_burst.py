"""Sep15 NIFTY 23350 PE — live mid-rip detect before post-peak radar (CE/PE symmetric)."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.expiry_day_guards import check_expiry_entry_allowed
from tests.mock_defaults import settings_mock
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


def _settings():
    """Production-aligned settings for Sep15 fast-vertical burst tests."""
    return settings_mock(
        explosion_scan_range=1500,
        explosion_sensex_scan_range=1500,
        velocity_peak_score_boost_enabled=False,
        ict_breakout_monitor_enabled=False,
        expiry_evening_block_enabled=False,
        expiry_fast_vertical_burst_halt_bypass_enabled=True,
        expiry_day_guards_enabled=True,
        expiry_worst_day_halt_entries=True,
        expiry_worst_day_score_threshold=55.0,
    )


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


@patch("app.engines.expiry_day_guards.snapshots_have_top_ftv_or_v", return_value=False)
@patch("app.engines.expiry_day_guards.snapshots_have_grade_a_ftv_first_lift", return_value=False)
@patch("app.engines.expiry_day_guards.snapshots_have_strict_rank_one_launch", return_value=False)
@patch("app.config.get_settings")
def test_expiry_worst_day_halt_bypasses_on_fast_vertical_radar(
    mock_get_settings,
    _strict_rank,
    _grade_a_ftv,
    _top_ftv_v,
):
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
    ), patch(
        "app.engines.expiry_day_guards.in_expiry_evening_block",
        return_value=False,
    ):
        ok, reason, meta = check_expiry_entry_allowed(AutoTraderState(), {"NIFTY": snap})
    assert ok is True
    assert meta.get("expiryFastVerticalBurstBypass") is True
