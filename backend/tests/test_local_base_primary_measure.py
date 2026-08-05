"""Entry/chase/must-take must measure from local pad, not day-peak %."""

from types import SimpleNamespace
from unittest.mock import patch

from app.engines.explosion_entry_guards import (
    effective_local_base_move_pct,
    extended_session_chase_blocked,
    trustworthy_local_base_move,
)
from app.engines.elite_never_block import _near_base_move_pct
from app.models.schemas import Side


def _settings(**kwargs):
    s = SimpleNamespace(
        explosion_chase_use_local_base=True,
        explosion_local_base_trust_min_move_pct=8.0,
        explosion_extended_chase_block_enabled=True,
        explosion_extended_chase_min_move_pct=65.0,
        explosion_early_window_max_move_pct=65.0,
        explosion_local_base_chase_max_move_pct=65.0,
        explosion_top_must_take_enabled=False,
        explosion_elite_never_block_enabled=False,
        ict_base_relative_chase_bypass_enabled=True,
        ict_base_relative_chase_max_move_pct=65.0,
        ict_base_relative_chase_abs_move_cap_pct=160.0,
        ict_base_relative_ignore_abs_cap=True,
    )
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


def _ict(base_rel: float, *, structured: bool = False):
    return SimpleNamespace(
        active=True,
        flat_then_vertical=structured,
        local_swing_base=structured,
        displacement=not structured,
        volume_awakening=False,
        premium_fvg=False,
        mega_rip=False,
        base_relative_move_pct=base_rel,
        session_move_pct=67.0,
        base_premium=66.0,
    )


def _event(*, daily=67.0, peak=67.0, premium=72.0):
    return SimpleNamespace(
        symbol="NIFTY",
        side=Side.PUT,
        strike=24500.0,
        premium=premium,
        daily_move_pct=daily,
        peak_move_pct=peak,
        tier="EXPLODING",
        velocity_3s=2.0,
    )


@patch("app.engines.explosion_entry_guards.get_settings")
def test_trustworthy_local_accepts_displacement_pad(mock_s):
    mock_s.return_value = _settings()
    # No flat→vertical — still a real pad print (≥8%).
    assert trustworthy_local_base_move(_ict(11.0, structured=False)) == 11.0
    assert trustworthy_local_base_move(_ict(2.0, structured=False)) == 0.0


@patch("app.engines.explosion_entry_guards.get_settings")
def test_effective_prefers_local_over_day(mock_s):
    mock_s.return_value = _settings()
    pad = effective_local_base_move_pct(_event(daily=67.0), _ict(9.5))
    assert pad == 9.5


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.elite_never_block.get_settings")
def test_chase_uses_local_not_day_peak(mock_enb, mock_s):
    """Aug5 24500: day ~67% must not chase-block when pad is only ~9%."""
    s = _settings()
    mock_s.return_value = s
    mock_enb.return_value = s
    blocked, reason = extended_session_chase_blocked(
        _event(daily=67.0, peak=67.0, premium=72.0),
        ict=_ict(9.5, structured=False),
    )
    assert blocked is False
    assert reason == ""


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.elite_never_block.get_settings")
def test_chase_blocks_when_local_past_ceiling(mock_enb, mock_s):
    s = _settings()
    mock_s.return_value = s
    mock_enb.return_value = s
    blocked, reason = extended_session_chase_blocked(
        _event(daily=90.0, peak=90.0, premium=127.0),
        ict=_ict(92.0, structured=False),
    )
    assert blocked is True
    assert "chase_local_92" in reason


@patch("app.engines.explosion_entry_guards.session_low_relative_move_pct", create=True)
@patch("app.engines.explosion_detector.session_low_relative_move_pct", return_value=0.0)
@patch("app.engines.explosion_entry_guards.get_settings")
def test_must_take_move_ignores_day_peak(mock_s, _off_low, _off_low2):
    mock_s.return_value = _settings()
    move = _near_base_move_pct(
        _event(daily=67.0, peak=67.0),
        {"dailyMovePct": 67.0, "peakMovePct": 67.0},
        ict=_ict(11.0),
    )
    assert move == 11.0
    # No pad → 0 (do not invent must-take from day%).
    move2 = _near_base_move_pct(
        _event(daily=40.0, peak=40.0),
        {"dailyMovePct": 40.0},
        ict=_ict(0.0),
    )
    assert move2 == 0.0
