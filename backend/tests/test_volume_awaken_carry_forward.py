"""WS volume=0 must not wipe REST volume history or drop ICT volume_awakening."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.engines.explosion_detector import (
    ExplosionEvent,
    _history,
    _last_known_volume,
    _record,
    _strike_key,
    _volume_surge,
    reset_detector_state_for_tests,
)
from app.engines.ict_breakout_monitor import analyze_explosion_event_ict
from app.models.schemas import Side


def setup_function(_):
    reset_detector_state_for_tests()


def test_record_carries_forward_volume_when_ws_passes_zero():
    _record("NIFTY", 23900.0, Side.PUT, 100.0, 50_000)
    _record("NIFTY", 23900.0, Side.PUT, 110.0, 0)  # WS rescan
    key = _strike_key(23900.0, Side.PUT)
    hist = _history["NIFTY"][key]
    assert hist[-1][2] == 50_000
    assert _last_known_volume(hist) == 50_000


def test_ws_zeros_do_not_collapse_volume_surge():
    # Build rising volume history, then WS zeros — without carry-forward recent_vol→0
    # and surge collapses to 0; with carry-forward last volume stays and surge > 0.
    for i, vol in enumerate([10_000, 12_000, 15_000, 40_000, 55_000]):
        _record("SENSEX", 76300.0, Side.PUT, 30.0 + i, vol)
    for i in range(3):
        _record("SENSEX", 76300.0, Side.PUT, 40.0 + i, 0)
    hist = _history["SENSEX"][_strike_key(76300.0, Side.PUT)]
    assert hist[-1][2] == 55_000
    after = _volume_surge(hist)
    assert after > 0.5  # not collapsed to 0 by zero pollution


def _ict_settings(**overrides):
    s = MagicMock()
    s.ict_breakout_monitor_enabled = True
    s.explosion_volume_awaken_min = 25_000
    s.ict_volume_surge_awaken_min = 2.0
    s.ict_displacement_min_velocity_3s = 2.0
    s.ict_vertical_min_session_move_pct = 40.0
    s.ict_early_vertical_min_session_move_pct = 28.0
    s.ict_early_vertical_min_velocity_3s = 2.0
    s.ict_mega_rip_min_session_move_pct = 80.0
    s.ict_breakout_min_score = 20.0
    s.ict_fvg_score_bonus = 12.0
    s.ict_flat_vertical_score_bonus = 18.0
    s.ict_early_breakout_score_bonus = 16.0
    s.ict_mega_rip_score_bonus = 20.0
    s.explosion_immature_min_session_move_pct = 22.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_ict_sees_volume_from_event_field(mock_s):
    mock_s.return_value = _ict_settings()

    event = ExplosionEvent(
        symbol="SENSEX",
        side=Side.PUT,
        strike=76300.0,
        premium=40.0,
        velocity_3s=8.0,
        velocity_9s=10.0,
        velocity_15s=9.0,
        volume_surge=1.2,
        explosion_score=70.0,
        tier="ELITE",
        reason="momentum",
        daily_move_pct=33.0,
        peak_move_pct=33.0,
        volume=50_000,
    )
    ict = analyze_explosion_event_ict(event, snap=None)
    assert ict.volume_awakening is True
    assert any("volume" in r for r in ict.reasons)


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_ict_surge_awaken_at_2x_matches_detector_boost(mock_s):
    mock_s.return_value = _ict_settings()

    event = SimpleNamespace(
        symbol="NIFTY",
        side=Side.PUT,
        strike=23900.0,
        premium=150.0,
        velocity_3s=3.0,
        velocity_9s=4.0,
        volume_surge=2.0,  # detector volAwaken boost level
        daily_move_pct=32.0,
        peak_move_pct=32.0,
        tier="ELITE",
        reason="+3.0%/3s",
        volume=0,
    )
    ict = analyze_explosion_event_ict(event, snap=None)
    assert ict.volume_awakening is True
