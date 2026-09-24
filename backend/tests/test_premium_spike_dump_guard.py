"""Post-spike premium dump guard — Sep 24 SENSEX 73700 PE falling-knife entry."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.engines.explosion_detector import ExplosionEvent
from app.engines.premium_spike_dump_guard import (
    alert_premium_spike_dump_meta,
    live_execution_trade_score,
    post_spike_premium_dump_blocked,
    premium_chart_spike_dump_read,
)
from app.models.schemas import PremiumChart, Side


def _make_candles_spike_dump(*, base: float = 50.0, peak: float = 240.0, ltp: float = 150.0):
    """Ramp up then large red candles into ltp."""
    candles = []
    p = base
    for i in range(10):
        nxt = base + (peak - base) * (i + 1) / 10
        candles.append([0, p, nxt, p, nxt, 1000])
        p = nxt
    for drop in (0.85, 0.72, 0.63):
        hi = p
        lo = p * drop
        cl = lo
        candles.append([0, hi, hi, lo, cl, 2000])
        p = cl
    candles[-1][4] = ltp
    candles[-1][2] = max(candles[-1][2], ltp)
    return candles


@patch("app.engines.premium_spike_dump_guard.get_settings")
def test_chart_read_detects_post_spike_dump(mock_settings):
    s = MagicMock()
    s.premium_post_spike_dump_chart_bars = 24
    s.premium_post_spike_dump_min_drawdown_pct = 12.0
    s.premium_post_spike_dump_min_spike_run_pct = 35.0
    s.premium_post_spike_dump_near_low_frac = 0.18
    s.premium_post_spike_dump_min_big_red_bars = 2
    s.premium_post_spike_dump_big_body_mult = 1.1
    mock_settings.return_value = s

    candles = _make_candles_spike_dump(ltp=150.0)
    read = premium_chart_spike_dump_read(candles, 150.0, settings=s)
    assert read["active"] is True
    assert read["drawdownFromHighPct"] <= -12.0


@patch("app.engines.premium_spike_dump_guard.get_settings")
def test_alert_meta_blocks_mid_collapse(mock_settings):
    s = MagicMock()
    s.premium_post_spike_dump_min_drawdown_pct = 12.0
    s.premium_post_spike_dump_min_spike_run_pct = 35.0
    s.premium_post_spike_dump_near_low_frac = 0.18
    s.premium_post_spike_dump_min_velocity_3s = -0.15
    s.premium_post_spike_dump_min_velocity_9s = -0.25
    mock_settings.return_value = s

    alert = {
        "premium": 150.0,
        "sessionPeakPremium": 240.0,
        "sessionLowPremium": 45.0,
        "velocity3s": -0.5,
        "velocity9s": -1.2,
    }
    meta = alert_premium_spike_dump_meta(alert, settings=s)
    assert meta["active"] is True


@patch("app.engines.premium_spike_dump_guard.get_settings")
def test_near_session_low_not_dump(mock_settings):
    s = MagicMock()
    s.premium_post_spike_dump_min_drawdown_pct = 12.0
    s.premium_post_spike_dump_min_spike_run_pct = 35.0
    s.premium_post_spike_dump_near_low_frac = 0.18
    s.premium_post_spike_dump_min_velocity_3s = -0.15
    s.premium_post_spike_dump_min_velocity_9s = -0.25
    mock_settings.return_value = s

    alert = {
        "premium": 48.0,
        "sessionPeakPremium": 240.0,
        "sessionLowPremium": 45.0,
        "velocity3s": 0.8,
        "velocity9s": 1.0,
    }
    assert alert_premium_spike_dump_meta(alert, settings=s)["active"] is False


@patch("app.engines.explosion_detector.get_session_peak_premium")
@patch("app.engines.explosion_detector.get_session_low_premium")
@patch("app.engines.premium_spike_dump_guard.get_settings")
def test_post_spike_blocked_on_event(mock_settings, mock_low, mock_peak):
    s = MagicMock()
    s.premium_post_spike_dump_guard_enabled = True
    s.premium_post_spike_dump_min_drawdown_pct = 12.0
    s.premium_post_spike_dump_min_spike_run_pct = 35.0
    s.premium_post_spike_dump_near_low_frac = 0.18
    s.premium_post_spike_dump_min_velocity_3s = -0.15
    s.premium_post_spike_dump_min_velocity_9s = -0.25
    mock_settings.return_value = s
    mock_peak.return_value = 240.0
    mock_low.return_value = 45.0

    event = ExplosionEvent(
        symbol="SENSEX",
        side=Side.PUT,
        strike=73700.0,
        premium=150.0,
        velocity_3s=-0.6,
        velocity_9s=-1.0,
        velocity_15s=0.0,
        volume_surge=2.0,
        explosion_score=100.0,
        tier="ELITE",
        reason="test",
        daily_move_pct=80.0,
    )
    blocked, reason, _ = post_spike_premium_dump_blocked(event, settings=s)
    assert blocked
    assert reason == "premium_post_spike_dump"


@patch("app.engines.premium_spike_dump_guard.get_settings")
def test_live_execution_score_decays_on_dump(mock_settings):
    s = MagicMock()
    s.live_execution_trade_score_enabled = True
    s.live_execution_trade_score_dump_penalty = 45.0
    s.live_execution_trade_score_mom_factor = 8.0
    mock_settings.return_value = s

    prem = PremiumChart(
        direction="BEARISH",
        momentum5Pct=-2.0,
        postSpikeDump=True,
        drawdownFromHighPct=-30.0,
    )
    live, meta = live_execution_trade_score(100.0, prem, settings=s)
    assert live < 60.0
    assert meta["liveScorePenalty"] >= 45.0


@patch("app.engines.spot_direction.get_settings")
def test_premium_blocks_entry_on_post_spike_dump(mock_settings):
    from app.engines.spot_direction import premium_blocks_entry

    s = MagicMock()
    s.execution_chart_premium_check_enabled = True
    mock_settings.return_value = s

    prem = PremiumChart(postSpikeDump=True, direction="BEARISH", momentum5Pct=-1.5)
    blocked, reason = premium_blocks_entry(Side.PUT, prem, trade_score=100.0)
    assert blocked
    assert reason == "premium_post_spike_dump"
