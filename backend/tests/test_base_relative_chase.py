"""Local-base chase — measure from flat base or dump→V-bottom, not day-session %.

SENSEX 76300 PE: ranged 30-100 then broke 100->144. Day-move reads +113% (chase),
but the move FROM THE BASE is early — should not be blocked as extended chase.

SENSEX 76400 PE Jul23: dumped 110→42 at 14:35 then ripped to 240. Day-move +471%
always looks like a chase; local-base window 15–40% is the real gate.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_entry_guards import (
    extended_session_chase_blocked,
    immature_explosion_blocked,
)
from app.engines.ict_breakout_monitor import (
    _detect_local_swing_base,
    late_fade_chase_blocked,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.explosion_extended_chase_block_enabled = True
    s.explosion_extended_chase_min_move_pct = 70.0
    s.explosion_early_window_max_move_pct = 55.0
    s.ict_base_relative_chase_bypass_enabled = True
    s.ict_base_relative_chase_max_move_pct = 55.0
    s.ict_base_relative_chase_abs_move_cap_pct = 160.0
    s.ict_base_relative_ignore_abs_cap = True
    s.explosion_chase_use_local_base = True
    s.explosion_local_base_chase_max_move_pct = 40.0
    s.explosion_local_base_entry_min_move_pct = 15.0
    s.explosion_local_base_trust_min_move_pct = 8.0
    s.ict_local_base_lookback_polls = 16
    s.ict_local_base_min_dump_pct = 25.0
    s.explosion_immature_block_enabled = True
    s.explosion_immature_min_session_move_pct = 22.0
    s.ict_early_vertical_min_session_move_pct = 28.0
    s.ict_late_chase_block_enabled = True
    s.ict_late_chase_min_peak_pct = 75.0
    s.ict_late_chase_max_live_velocity_3s = 1.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _event(day_move=113.0):
    return SimpleNamespace(daily_move_pct=day_move, peak_move_pct=day_move)


def _ict(*, flat=True, active=True, vol=True, base_move=44.0, local_swing=False):
    return SimpleNamespace(
        flat_then_vertical=flat,
        active=active,
        volume_awakening=vol,
        displacement=False,
        session_move_pct=113.0,
        base_relative_move_pct=base_move,
        local_swing_base=local_swing,
    )


@patch("app.engines.explosion_entry_guards.get_settings")
def test_base_break_allowed_despite_high_day_move(mock_s):
    mock_s.return_value = _settings()
    blocked, reason = extended_session_chase_blocked(_event(113.0), ict=_ict(base_move=35.0))
    assert blocked is False


@patch("app.engines.explosion_entry_guards.get_settings")
def test_extended_local_base_still_blocked(mock_s):
    mock_s.return_value = _settings()
    # local-base move past 40% → chase from the local launch
    blocked, reason = extended_session_chase_blocked(_event(113.0), ict=_ict(base_move=41.0))
    assert blocked is True
    assert "extended_chase_local" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_local_base_allows_parabolic_day_move(mock_s):
    """Day +220% is fine when local-base expansion is still early (≤40%)."""
    mock_s.return_value = _settings()
    blocked, reason = extended_session_chase_blocked(_event(220.0), ict=_ict(base_move=40.0))
    assert blocked is False


@patch("app.engines.explosion_entry_guards.get_settings")
def test_low_base_rip_ignores_day_chase(mock_s):
    """30→140 style: session % is huge, but base-relative is still early — allow."""
    mock_s.return_value = _settings()
    blocked, reason = extended_session_chase_blocked(_event(340.0), ict=_ict(base_move=35.0))
    assert blocked is False


@patch("app.engines.explosion_entry_guards.get_settings")
def test_local_base_allows_without_flat_or_volume(mock_s):
    """V-bottom reclaim: no flat consolidation — local base alone is enough for chase."""
    mock_s.return_value = _settings()
    blocked, reason = extended_session_chase_blocked(
        _event(471.0),
        ict=_ict(flat=False, vol=False, base_move=35.0, local_swing=True),
    )
    assert blocked is False


@patch("app.engines.explosion_entry_guards.get_settings")
def test_local_primary_disabled_falls_back_to_legacy(mock_s):
    mock_s.return_value = _settings(
        explosion_chase_use_local_base=False,
        ict_base_relative_chase_bypass_enabled=False,
    )
    blocked, reason = extended_session_chase_blocked(_event(113.0), ict=_ict(base_move=35.0))
    assert blocked is True


@patch("app.engines.explosion_entry_guards.get_settings")
def test_normal_early_move_not_affected(mock_s):
    mock_s.return_value = _settings()
    # day-move below hard floor → never blocked regardless
    blocked, reason = extended_session_chase_blocked(_event(40.0), ict=_ict(base_move=40.0))
    assert blocked is False


@patch("app.engines.explosion_entry_guards.get_settings")
def test_immature_waits_for_15pct_from_local_base(mock_s):
    mock_s.return_value = _settings()
    # Day move looks mature (+471%) but local V-bottom only +12% — wait.
    blocked, reason = immature_explosion_blocked(
        _event(471.0),
        ict=_ict(flat=False, base_move=12.0, local_swing=True),
    )
    assert blocked is True
    assert "immature_local_base" in reason

    blocked2, _ = immature_explosion_blocked(
        _event(471.0),
        ict=_ict(flat=False, base_move=18.0, local_swing=True),
    )
    assert blocked2 is False


@patch("app.engines.explosion_entry_guards.get_settings")
def test_noise_baserel_does_not_false_immature(mock_s):
    """Jul24 PUTs: baseRel≈1.5% noise must not hold a day-mature +28% rip."""
    mock_s.return_value = _settings()
    blocked, reason = immature_explosion_blocked(
        _event(28.0),
        ict=_ict(flat=False, base_move=1.5, local_swing=True),
    )
    assert blocked is False
    assert reason == ""


@patch("app.engines.explosion_entry_guards.get_settings")
def test_unstructured_baserel_ignored_for_immature(mock_s):
    """baseRel without swing/flat→vertical is not a launch pad."""
    mock_s.return_value = _settings()
    blocked, reason = immature_explosion_blocked(
        _event(28.0),
        ict=_ict(flat=False, base_move=12.0, local_swing=False),
    )
    assert blocked is False


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_late_fade_skips_when_local_base_early(mock_s):
    mock_s.return_value = _settings()
    event = SimpleNamespace(
        peak_move_pct=471.0, daily_move_pct=188.0, velocity_3s=0.4,
    )
    ict = _ict(flat=False, base_move=35.0, local_swing=True)
    ict.session_move_pct = 471.0
    blocked, reason = late_fade_chase_blocked(event, ict)
    assert blocked is False


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_detect_local_swing_base_76400_vbottom(mock_s):
    """Dump 110→42 then reclaim to ~54 (~28% from local low)."""
    mock_s.return_value = _settings()
    now = datetime.now(IST)
    # Simulate polls: elevated → dump → V-bottom → early reclaim
    history = []
    prices = [120, 115, 110, 95, 80, 60, 48, 42.45, 45.75, 51.0, 54.0]
    for i, p in enumerate(prices):
        history.append((now + timedelta(seconds=i * 3), p, 1.0))
    found, low, rel = _detect_local_swing_base(history, premium=54.0, settings=_settings())
    assert found is True
    assert low == 42.45
    assert 27.0 <= rel <= 30.0


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_detect_local_swing_rejects_quiet_range(mock_s):
    mock_s.return_value = _settings()
    now = datetime.now(IST)
    history = [(now + timedelta(seconds=i * 3), 30 + i * 0.2, 1.0) for i in range(10)]
    found, _, _ = _detect_local_swing_base(history, premium=32.0, settings=_settings())
    assert found is False
