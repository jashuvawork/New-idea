"""Hard ELITE/EXPLODING entry window 28–55% (book: only profitable band)."""

from unittest.mock import MagicMock, patch

from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_entry_guards import explosion_entry_window_blocked
from app.engines.ict_breakout_monitor import ICTBreakoutSignal
from app.models.schemas import Side


def _event(move: float, peak: float | None = None, tier: str = "ELITE") -> ExplosionEvent:
    return ExplosionEvent(
        symbol="SENSEX",
        side=Side.CALL,
        strike=77700.0,
        premium=105.0,
        velocity_3s=3.0,
        velocity_9s=4.0,
        velocity_15s=5.0,
        volume_surge=2.0,
        explosion_score=95.0,
        tier=tier,
        reason="test",
        daily_move_pct=move,
        peak_move_pct=peak if peak is not None else move,
    )


def _settings(**overrides):
    s = MagicMock()
    s.explosion_entry_window_hard_enabled = True
    s.explosion_early_window_min_move_pct = 28.0
    s.explosion_early_window_max_move_pct = 55.0
    s.ict_structured_early_entry_enabled = True
    s.ict_structured_early_min_move_pct = 12.0
    s.ict_structured_early_max_move_pct = 40.0
    s.explosion_chase_use_local_base = True
    s.explosion_local_base_trust_min_move_pct = 8.0
    s.session_move_max_credible_pct = 500.0
    s.session_move_min_baseline_premium = 5.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _structured_ict(base_rel: float, *, session: float = 40.0) -> ICTBreakoutSignal:
    return ICTBreakoutSignal(
        active=True,
        pattern="flat_then_vertical",
        score=44.0,
        reasons=["early_flat_break", "volume_awakening"],
        session_move_pct=session,
        base_relative_move_pct=base_rel,
        base_premium=253.7,
        flat_then_vertical=True,
        local_swing_base=True,
        displacement=True,
        volume_awakening=True,
    )


@patch("app.engines.explosion_entry_guards.get_settings")
def test_window_allows_28_to_55(mock_settings):
    mock_settings.return_value = _settings()
    for move in (28.0, 35.0, 45.0, 54.9):
        blocked, reason = explosion_entry_window_blocked(_event(move))
        assert blocked is False, (move, reason)


@patch("app.engines.explosion_entry_guards.get_settings")
def test_window_blocks_below_28(mock_settings):
    mock_settings.return_value = _settings()
    blocked, reason = explosion_entry_window_blocked(_event(22.0))
    assert blocked is True
    assert "entry_window_low" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_window_blocks_chase_above_55(mock_settings):
    mock_settings.return_value = _settings()
    blocked, reason = explosion_entry_window_blocked(_event(70.0))
    assert blocked is True
    assert "entry_window_high" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_jul30_77700_weak_local_blocked(mock_settings):
    """Day ~29% but local base only +7.4% — must not enter."""
    mock_settings.return_value = _settings()
    ict = ICTBreakoutSignal(
        active=True,
        pattern="displacement",
        score=36.0,
        reasons=["flat_base_breaking"],
        session_move_pct=28.9,
        base_relative_move_pct=7.4,
        base_premium=96.52,
        flat_then_vertical=False,
        local_swing_base=False,
        displacement=True,
        volume_awakening=True,
    )
    blocked, reason = explosion_entry_window_blocked(_event(28.9), ict=ict)
    assert blocked is True
    assert "weak_local" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_local_base_inside_window_ok(mock_settings):
    mock_settings.return_value = _settings()
    ict = ICTBreakoutSignal(
        active=True,
        pattern="flat_then_vertical",
        score=40.0,
        reasons=["flat_then_vertical"],
        session_move_pct=120.0,  # day looks like chase
        base_relative_move_pct=35.0,  # local still early
        base_premium=90.0,
        flat_then_vertical=True,
        local_swing_base=True,
        displacement=True,
        volume_awakening=True,
    )
    blocked, reason = explosion_entry_window_blocked(_event(120.0), ict=ict)
    assert blocked is False, reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_structured_allows_near_base_26pct(mock_settings):
    """Aug4 SENSEX 78700 PE first lift ~320 / ~26% off base 253.7 — must enter."""
    mock_settings.return_value = _settings()
    ict = _structured_ict(26.0, session=26.0)
    blocked, reason = explosion_entry_window_blocked(_event(26.0), ict=ict)
    assert blocked is False, reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_unstructured_still_blocks_26pct(mock_settings):
    """Without ICT structure+heat, keep the book 28% floor."""
    mock_settings.return_value = _settings()
    blocked, reason = explosion_entry_window_blocked(_event(26.0))
    assert blocked is True
    assert "entry_window_low" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_structured_blocks_late_54pct_chase(mock_settings):
    """Same rip at ~392 / ~54% — structured ceiling 40% refuses the late spike."""
    mock_settings.return_value = _settings()
    ict = _structured_ict(54.5, session=54.5)
    blocked, reason = explosion_entry_window_blocked(_event(54.5), ict=ict)
    assert blocked is True
    assert "entry_window_local_high" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_structured_allows_18pct_first_displacement(mock_settings):
    mock_settings.return_value = _settings()
    ict = _structured_ict(18.0, session=18.0)
    blocked, reason = explosion_entry_window_blocked(_event(18.0), ict=ict)
    assert blocked is False, reason
