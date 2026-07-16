"""Vertical rip bypass — chart/breadth/MTF gates for premium-led explosions."""

from unittest.mock import MagicMock, patch

from app.engines.explosion_detector import ExplosionEvent
from app.engines.rally_capture import breadth_blocks_explosion_side, chart_blocks_explosion_side
from app.engines.vertical_rip_bypass import (
    qualifies_for_vertical_rip_bypass,
    vertical_rip_bypasses_hard_breadth,
)
from app.models.schemas import Breadth, Side, SpotChart, SymbolSnapshot


def _settings() -> MagicMock:
    s = MagicMock()
    s.vertical_rip_bypass_enabled = True
    s.vertical_rip_bypass_min_peak_pct = 30.0
    s.vertical_rip_bypass_min_tier = "EXPLODING"
    s.vertical_rip_bypass_min_score = 38.0
    s.vertical_rip_bypass_min_peak_velocity_3s = 2.0
    s.vertical_rip_bypass_min_volume_surge = 3.0
    s.vertical_rip_hard_breadth_bypass_enabled = True
    s.extreme_explosion_all_in_enabled = True
    s.extreme_explosion_elite_move_min_pct = 100.0
    s.extreme_explosion_all_in_move_min_pct = 150.0
    s.extreme_explosion_all_in_min_score = 35.0
    return s


def _event(**kwargs) -> ExplosionEvent:
    defaults = dict(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24150.0,
        premium=132.0,
        velocity_3s=-1.0,
        velocity_9s=0.5,
        velocity_15s=1.0,
        volume_surge=4.5,
        explosion_score=85.0,
        tier="ELITE",
        reason="peak rip",
        daily_move_pct=25.0,
        peak_move_pct=40.0,
    )
    defaults.update(kwargs)
    return ExplosionEvent(**defaults)


@patch("app.config.get_settings")
def test_qualifies_on_peak_move_and_score(mock_settings):
    mock_settings.return_value = _settings()
    assert qualifies_for_vertical_rip_bypass(_event()) is True


@patch("app.config.get_settings")
def test_does_not_qualify_on_weak_rip(mock_settings):
    mock_settings.return_value = _settings()
    assert qualifies_for_vertical_rip_bypass(_event(peak_move_pct=15.0, explosion_score=30.0)) is False


@patch("app.config.get_settings")
def test_chart_block_bypassed_for_vertical_rip(mock_settings):
    mock_settings.return_value = _settings()
    chart = SpotChart(direction="BEARISH", trendStrength=40.0, momentum5Pct=-0.1)
    blocked, _ = chart_blocks_explosion_side(Side.CALL, chart, "ELITE", event=_event())
    assert blocked is False


@patch("app.config.get_settings")
def test_breadth_block_bypassed_for_vertical_rip(mock_settings):
    mock_settings.return_value = _settings()
    blocked, _ = breadth_blocks_explosion_side(Side.PUT, "BULLISH", "ELITE", event=_event(side=Side.PUT))
    assert blocked is False


@patch("app.config.get_settings")
def test_hard_breadth_bypass_call_on_bearish(mock_settings):
    mock_settings.return_value = _settings()
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp="2026-07-16T12:00:00+05:30",
        marketPhase="LIVE_MARKET",
        spot=24100,
        dataAvailable=True,
        breadth=Breadth(bias="BEARISH"),
    )
    ok = vertical_rip_bypasses_hard_breadth(Side.CALL, "BEARISH", event=_event(), snap=snap)
    assert ok is True


@patch("app.config.get_settings")
def test_spike_baseline_raises_peak_move(mock_settings):
    from app.engines.explosion_detector import (
        _history,
        _open_key,
        _roll_session,
        _session_open,
        _session_peak_move_pct,
    )

    mock_settings.return_value = _settings()
    mock_settings.return_value.session_open_use_intraday_low = True
    mock_settings.return_value.session_open_low_backfill_pct = 5.0
    mock_settings.return_value.volume_spike_baseline_enabled = True
    mock_settings.return_value.volume_spike_baseline_min_surge = 3.5
    mock_settings.return_value.spike_velocity_baseline_min_pct = 12.0

    _roll_session()
    _session_open.clear()
    _history.clear()

    from collections import deque
    from datetime import datetime
    from zoneinfo import ZoneInfo

    IST = ZoneInfo("Asia/Kolkata")
    hist = deque(maxlen=40)
    hist.append((datetime.now(IST), 100.0, 1000))
    hist.append((datetime.now(IST), 168.0, 8000000))
    _history["NIFTY"] = {"CALL:24000": hist}
    key = _open_key("NIFTY", 24000.0, Side.CALL)
    _session_open[key] = 123.0

    peak = _session_peak_move_pct(
        "NIFTY", 24000.0, Side.CALL, 168.0, hist, v3=45.0, vol_surge=8.0,
    )
    assert peak >= 65.0
    assert _session_open[key] <= 100.0
