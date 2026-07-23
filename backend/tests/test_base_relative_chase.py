"""Base-relative chase bypass — fresh flat->vertical break off a consolidation base.

SENSEX 76300 PE: ranged 30-100 then broke 100->144. Day-move reads +113% (chase),
but the move FROM THE BASE is early — should not be blocked as extended chase.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.engines.explosion_entry_guards import extended_session_chase_blocked


def _settings(**overrides):
    s = MagicMock()
    s.explosion_extended_chase_block_enabled = True
    s.explosion_extended_chase_min_move_pct = 70.0
    s.explosion_early_window_max_move_pct = 55.0
    s.ict_base_relative_chase_bypass_enabled = True
    s.ict_base_relative_chase_max_move_pct = 55.0
    s.ict_base_relative_chase_abs_move_cap_pct = 160.0
    s.ict_base_relative_ignore_abs_cap = True
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _event(day_move=113.0):
    return SimpleNamespace(daily_move_pct=day_move, peak_move_pct=day_move)


def _ict(*, flat=True, active=True, vol=True, base_move=44.0):
    return SimpleNamespace(
        flat_then_vertical=flat, active=active, volume_awakening=vol,
        displacement=False, session_move_pct=113.0, base_relative_move_pct=base_move,
    )


@patch("app.engines.explosion_entry_guards.get_settings")
def test_base_break_allowed_despite_high_day_move(mock_s):
    mock_s.return_value = _settings()
    blocked, reason = extended_session_chase_blocked(_event(113.0), ict=_ict(base_move=44.0))
    assert blocked is False


@patch("app.engines.explosion_entry_guards.get_settings")
def test_extended_base_move_still_blocked(mock_s):
    mock_s.return_value = _settings()
    # base-relative move also extended (70%) → still a chase
    blocked, reason = extended_session_chase_blocked(_event(113.0), ict=_ict(base_move=70.0))
    assert blocked is True
    assert "extended_chase" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_parabolic_abs_cap_blocks_when_ignore_disabled(mock_s):
    mock_s.return_value = _settings(ict_base_relative_ignore_abs_cap=False)
    # base move looks early but absolute day-move is parabolic (>160%) → block
    blocked, reason = extended_session_chase_blocked(_event(220.0), ict=_ict(base_move=40.0))
    assert blocked is True


@patch("app.engines.explosion_entry_guards.get_settings")
def test_low_base_rip_ignores_abs_cap(mock_s):
    """30→140 style: session % is huge, but base-relative is still early — allow."""
    mock_s.return_value = _settings()
    blocked, reason = extended_session_chase_blocked(_event(340.0), ict=_ict(base_move=44.0))
    assert blocked is False


@patch("app.engines.explosion_entry_guards.get_settings")
def test_no_volume_no_bypass(mock_s):
    mock_s.return_value = _settings()
    blocked, reason = extended_session_chase_blocked(
        _event(113.0), ict=_ict(vol=False, base_move=44.0),
    )
    assert blocked is True


@patch("app.engines.explosion_entry_guards.get_settings")
def test_not_flat_then_vertical_no_bypass(mock_s):
    mock_s.return_value = _settings()
    blocked, reason = extended_session_chase_blocked(
        _event(113.0), ict=_ict(flat=False, base_move=44.0),
    )
    assert blocked is True


@patch("app.engines.explosion_entry_guards.get_settings")
def test_bypass_disabled(mock_s):
    mock_s.return_value = _settings(ict_base_relative_chase_bypass_enabled=False)
    blocked, reason = extended_session_chase_blocked(_event(113.0), ict=_ict(base_move=44.0))
    assert blocked is True


@patch("app.engines.explosion_entry_guards.get_settings")
def test_normal_early_move_not_affected(mock_s):
    mock_s.return_value = _settings()
    # day-move below hard floor → never blocked regardless
    blocked, reason = extended_session_chase_blocked(_event(40.0), ict=_ict(base_move=40.0))
    assert blocked is False
