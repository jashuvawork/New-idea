"""Elite moment calc — reject fake micro-baseline % and catch real V-bottom rips."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_detector import (
    ExplosionEvent,
    _session_low,
    _session_open,
    _session_open_move_pct,
    _session_peak,
    reset_detector_state_for_tests,
    session_low_relative_move_pct,
)
from app.engines.explosion_entry_guards import explosion_entry_window_blocked
from app.engines.ict_breakout_monitor import analyze_ict_breakout
from app.models.schemas import Side

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.session_move_min_baseline_premium = 5.0
    s.session_move_max_credible_pct = 500.0
    s.session_open_use_intraday_low = True
    s.session_open_low_backfill_pct = 5.0
    s.volume_spike_baseline_enabled = True
    s.volume_spike_baseline_min_surge = 3.5
    s.spike_velocity_baseline_min_pct = 12.0
    s.open_gap_prev_close_baseline_enabled = True
    s.open_gap_baseline_min_gap_pct = 15.0
    s.explosion_entry_window_hard_enabled = True
    s.explosion_early_window_min_move_pct = 28.0
    s.explosion_early_window_max_move_pct = 55.0
    s.explosion_chase_use_local_base = True
    s.explosion_local_base_trust_min_move_pct = 8.0
    s.ict_breakout_monitor_enabled = True
    s.ict_fvg_min_gap_pct = 12.0
    s.ict_flat_base_max_range_pct = 8.0
    s.ict_displacement_min_velocity_3s = 2.2
    s.ict_vertical_min_session_move_pct = 80.0
    s.ict_early_vertical_min_session_move_pct = 28.0
    s.ict_early_vertical_min_velocity_3s = 2.0
    s.ict_volume_surge_awaken_min = 3.0
    s.ict_mega_rip_min_session_move_pct = 200.0
    s.ict_breakout_min_score = 28.0
    s.ict_fvg_score_bonus = 14.0
    s.ict_flat_vertical_score_bonus = 18.0
    s.ict_early_breakout_score_bonus = 16.0
    s.ict_mega_rip_score_bonus = 22.0
    s.explosion_volume_awaken_min = 25000
    s.ict_local_base_lookback_polls = 16
    s.ict_local_base_min_dump_pct = 25.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _event(move: float, premium: float = 55.0) -> ExplosionEvent:
    return ExplosionEvent(
        symbol="SENSEX",
        side=Side.CALL,
        strike=77700.0,
        premium=premium,
        velocity_3s=4.0,
        velocity_9s=5.0,
        velocity_15s=6.0,
        volume_surge=3.0,
        explosion_score=95.0,
        tier="ELITE",
        reason="test",
        daily_move_pct=move,
        peak_move_pct=move,
    )


@patch("app.config.get_settings")
def test_micro_tick_baseline_not_seeded(mock_s):
    """₹0.28 → ₹25 must not become +8873% elite moment."""
    mock_s.return_value = _settings()
    reset_detector_state_for_tests()
    move0 = _session_open_move_pct("SENSEX", 77900, Side.CALL, 0.28)
    assert move0 == 0.0
    assert not _session_open
    # First meaningful print seeds; second computes real %.
    move1 = _session_open_move_pct("SENSEX", 77900, Side.CALL, 5.0)
    assert move1 == 0.0
    move2 = _session_open_move_pct("SENSEX", 77900, Side.CALL, 25.0)
    assert 300.0 <= move2 <= 450.0  # (25-5)/5 = 400%, not 8873%
    assert move2 < 1000.0


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.config.get_settings")
def test_uncredible_session_blocked_without_off_low(mock_cfg, mock_guard):
    mock_cfg.return_value = _settings()
    mock_guard.return_value = _settings()
    reset_detector_state_for_tests()
    blocked, reason = explosion_entry_window_blocked(_event(8873.0, premium=25.2))
    assert blocked is True
    assert "uncredible" in reason or "high" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.config.get_settings")
def test_vbottom_off_low_inside_window_allowed(mock_cfg, mock_guard):
    """After dump to ~40, reclaim to ~55 (~37% off low) must pass even if day % is huge."""
    mock_cfg.return_value = _settings()
    mock_guard.return_value = _settings()
    reset_detector_state_for_tests()
    from app.engines.explosion_detector import _open_key

    k = _open_key("SENSEX", 77700.0, Side.CALL)
    _session_open[k] = 105.0
    _session_low[k] = 40.0
    _session_peak[k] = 105.0
    off = session_low_relative_move_pct("SENSEX", 77700.0, Side.CALL, 55.0)
    assert 35.0 <= off <= 40.0
    blocked, reason = explosion_entry_window_blocked(
        _event(1626.0, premium=55.0), ict=None
    )
    assert blocked is False, reason


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.config.get_settings")
def test_vbottom_late_chase_off_low_blocked(mock_cfg, mock_guard):
    """222 from low 40 (~455%) is chase — must not enter."""
    mock_cfg.return_value = _settings()
    mock_guard.return_value = _settings()
    reset_detector_state_for_tests()
    from app.engines.explosion_detector import _open_key

    k = _open_key("SENSEX", 77700.0, Side.CALL)
    _session_open[k] = 105.0
    _session_low[k] = 40.0
    _session_peak[k] = 260.0
    blocked, reason = explosion_entry_window_blocked(
        _event(1626.0, premium=222.0), ict=None
    )
    assert blocked is True
    assert "off_low_high" in reason or "high" in reason


@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.config.get_settings")
def test_ict_rejects_uncredible_mega_without_local(mock_cfg, mock_ict):
    mock_cfg.return_value = _settings()
    mock_ict.return_value = _settings()
    reset_detector_state_for_tests()
    ict = analyze_ict_breakout(
        symbol="SENSEX",
        side=Side.CALL,
        strike=77900.0,
        premium=25.2,
        session_move_pct=8873.0,
        peak_move_pct=8873.0,
        velocity_3s=0.0,
        volume_surge=1.0,
        volume=0,
        tier="ELITE",
        reason="",
    )
    assert ict.mega_rip is False
    assert any("uncredible" in r for r in ict.reasons)


@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.config.get_settings")
def test_ict_seeds_session_low_for_vbottom(mock_cfg, mock_ict):
    mock_cfg.return_value = _settings()
    mock_ict.return_value = _settings()
    reset_detector_state_for_tests()
    from app.engines.explosion_detector import _open_key

    k = _open_key("SENSEX", 77700.0, Side.CALL)
    _session_low[k] = 40.0
    _session_open[k] = 105.0
    _session_peak[k] = 60.0
    ict = analyze_ict_breakout(
        symbol="SENSEX",
        side=Side.CALL,
        strike=77700.0,
        premium=55.0,
        session_move_pct=200.0,
        peak_move_pct=200.0,
        velocity_3s=3.0,
        volume_surge=4.0,
        volume=300000,
        tier="ELITE",
        reason="volAwaken",
    )
    assert ict.local_swing_base is True
    assert 35.0 <= ict.base_relative_move_pct <= 40.0
    assert ict.base_premium == 40.0
