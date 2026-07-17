"""Distribution fixes — block late EXPLOSIVE chases that kill PF (Jul17 24250)."""

from unittest.mock import MagicMock, patch

from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_entry_guards import (
    cap_extended_chase_lots,
    extended_session_chase_blocked,
)
from app.engines.extreme_explosion_moment import (
    is_extreme_explosion_all_in_bypass,
    is_high_mover_elite_bypass,
)
from app.engines.ict_breakout_monitor import late_fade_chase_blocked
from app.models.schemas import Side


def _settings(**overrides):
    s = MagicMock()
    s.explosion_extended_chase_block_enabled = True
    s.explosion_extended_chase_min_move_pct = 70.0
    s.explosion_extended_soft_min_move_pct = 50.0
    s.explosion_extended_soft_lot_cap = 6
    s.explosion_hard_lot_cap = 10
    s.explosion_early_window_min_move_pct = 28.0
    s.explosion_early_window_max_move_pct = 55.0
    s.ict_late_chase_block_enabled = True
    s.ict_late_chase_min_peak_pct = 75.0
    s.ict_late_chase_max_live_velocity_3s = 1.0
    s.high_mover_bypass_max_move_pct = 70.0
    s.extreme_all_in_bypass_max_move_pct = 70.0
    s.extreme_explosion_all_in_enabled = True
    s.extreme_explosion_elite_move_min_pct = 100.0
    s.extreme_explosion_all_in_move_min_pct = 150.0
    s.extreme_explosion_all_in_min_score = 35.0
    s.all_day_explosion_min_score = 38.0
    s.all_day_explosion_session_move_min_pct = 40.0
    s.vertical_rip_bypass_min_peak_pct = 30.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _event(*, daily: float, peak: float | None = None, v3: float = 31.0) -> ExplosionEvent:
    return ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24250.0,
        premium=162.0,
        velocity_3s=v3,
        velocity_9s=v3,
        velocity_15s=v3,
        volume_surge=3.0,
        explosion_score=100.0,
        tier="ELITE",
        reason="premium_fvg",
        daily_move_pct=daily,
        peak_move_pct=peak if peak is not None else daily,
    )


@patch("app.engines.explosion_entry_guards.get_settings")
def test_blocks_24250_style_91pct_hot_chase(mock_settings):
    mock_settings.return_value = _settings()
    blocked, reason = extended_session_chase_blocked(_event(daily=91.27, v3=31.42))
    assert blocked is True
    assert "extended_chase" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_allows_early_window_45pct(mock_settings):
    mock_settings.return_value = _settings()
    blocked, _ = extended_session_chase_blocked(_event(daily=45.0, v3=3.5))
    assert blocked is False


@patch("app.engines.explosion_entry_guards.get_settings")
def test_soft_zone_lot_cap(mock_settings):
    mock_settings.return_value = _settings()
    capped = cap_extended_chase_lots(17, _event(daily=55.0))
    assert capped == 6
    hard = cap_extended_chase_lots(20, _event(daily=30.0))
    assert hard == 10


@patch("app.engines.extreme_explosion_moment.get_settings")
def test_high_mover_bypass_denied_past_70(mock_settings):
    mock_settings.return_value = _settings()
    assert is_high_mover_elite_bypass(event=_event(daily=91.0)) is False
    assert is_extreme_explosion_all_in_bypass(event=_event(daily=105.0)) is False


@patch("app.engines.extreme_explosion_moment.get_settings")
def test_high_mover_bypass_ok_in_early_soft_window(mock_settings):
    mock_settings.return_value = _settings()
    # 45% ELITE still qualifies via vertical_rip / session-move path
    assert is_high_mover_elite_bypass(event=_event(daily=45.0, v3=3.0)) is True


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_late_fade_at_75_with_cooling_velocity(mock_settings):
    mock_settings.return_value = _settings()
    blocked, reason = late_fade_chase_blocked(_event(daily=80.0, peak=85.0, v3=0.5))
    assert blocked is True
    assert "late_fade" in reason
