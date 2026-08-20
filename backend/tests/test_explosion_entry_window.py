"""Hard ELITE/EXPLODING entry window: 28% floor, capped at the local-base
ceiling (#262: ELITE/EXPLODING enter ≤40% off the local base — catch at the
base, not on the late chase)."""

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
    s.ict_structured_early_min_move_pct = 15.0
    s.ict_structured_early_max_move_pct = 45.0
    s.elite_local_base_max_move_pct = 40.0
    s.explosion_chase_use_local_base = True
    s.explosion_local_base_entry_min_move_pct = 15.0
    s.explosion_local_base_trust_min_move_pct = 8.0
    s.explosion_squeeze_early_base_enabled = True
    s.explosion_squeeze_early_base_min_move_pct = 8.0
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
def test_window_allows_28_to_elite_cap(mock_settings):
    """ELITE enters in-band up to the local-base cap (#262: ≤40% off base)."""
    mock_settings.return_value = _settings()
    for move in (28.0, 35.0, 39.9):
        blocked, reason = explosion_entry_window_blocked(_event(move))
        assert blocked is False, (move, reason)


@patch("app.engines.explosion_entry_guards.get_settings")
def test_window_blocks_elite_above_local_base_cap(mock_settings):
    """#262: ELITE beyond the local-base cap (40%) is a chase — refuse it."""
    mock_settings.return_value = _settings()
    for move in (45.0, 54.9):
        blocked, reason = explosion_entry_window_blocked(_event(move))
        assert blocked is True, (move, reason)
        assert "entry_window_" in reason and "high" in reason


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
def test_squeeze_early_base_lowers_floor(mock_settings):
    """A squeeze-fired ELITE at 10% off base is below the 15% floor — normally blocked, but
    a confirmed squeeze release lets it enter closer to the base."""
    mock_settings.return_value = _settings()
    ict = _structured_ict(10.0, session=10.0)
    blocked_no_sq, reason = explosion_entry_window_blocked(_event(10.0), ict=ict)
    assert blocked_no_sq is True and "low" in reason
    blocked_sq, _ = explosion_entry_window_blocked(
        _event(10.0), ict=ict, squeeze_early_base=True,
    )
    assert blocked_sq is False


@patch("app.engines.explosion_entry_guards.get_settings")
def test_structured_allows_38pct_inside_elite_cap(mock_settings):
    """Structured near-base ELITE enters inside the #262 local-base cap (≤40%)."""
    mock_settings.return_value = _settings()
    ict = _structured_ict(38.0, session=38.0)
    blocked, reason = explosion_entry_window_blocked(_event(38.0), ict=ict)
    assert blocked is False, reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_structured_blocks_42pct_above_elite_cap(mock_settings):
    """#262: even structured ELITE past the 40% local-base cap is a chase."""
    mock_settings.return_value = _settings()
    ict = _structured_ict(42.0, session=42.0)
    blocked, reason = explosion_entry_window_blocked(_event(42.0), ict=ict)
    assert blocked is True, reason
    assert "high" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_structured_blocks_late_54pct_chase(mock_settings):
    """Same rip at ~392 / ~54% — structured ceiling 45% refuses the late spike."""
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


@patch("app.engines.explosion_entry_guards.get_settings")
def test_aug7_building_13pct_blocked_under_15_floor(mock_settings):
    """Aug7 NIFTY 24550 PE BUILDING entered at ~13% off base — now below 15% floor."""
    mock_settings.return_value = _settings()
    move = 13.2
    ict = _structured_ict(move, session=20.8)
    ev = ExplosionEvent(
        symbol="NIFTY",
        side=Side.PUT,
        strike=24550.0,
        premium=115.8,
        velocity_3s=1.69,
        velocity_9s=2.0,
        velocity_15s=2.0,
        volume_surge=2.0,
        explosion_score=56.2,
        tier="BUILDING",
        reason="test",
        daily_move_pct=move,
        peak_move_pct=20.79,
    )
    blocked, reason = explosion_entry_window_blocked(ev, ict=ict)
    assert blocked is True
    assert "local_low" in reason or "weak_local" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_structured_allows_16pct_after_15_floor(mock_settings):
    """Clearer base break (≥15%) still enters on structured ICT."""
    mock_settings.return_value = _settings()
    move = (271.0 - 235.0) / 235.0 * 100.0  # ≈15.3
    assert 15.0 <= move < 16.0
    ict = ICTBreakoutSignal(
        active=True,
        pattern="flat_then_vertical",
        score=50.0,
        reasons=["moment_base", "volume_awakening"],
        session_move_pct=move,
        base_relative_move_pct=move,
        base_premium=235.0,
        flat_then_vertical=True,
        local_swing_base=True,
        displacement=True,
        volume_awakening=True,
    )
    ev = ExplosionEvent(
        symbol="SENSEX",
        side=Side.PUT,
        strike=78700.0,
        premium=271.0,
        velocity_3s=2.5,
        velocity_9s=3.0,
        velocity_15s=3.5,
        volume_surge=2.0,
        explosion_score=95.0,
        tier="ELITE",
        reason="test",
        daily_move_pct=move,
        peak_move_pct=move,
    )
    blocked, reason = explosion_entry_window_blocked(ev, ict=ict)
    assert blocked is False, reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_structured_still_blocks_below_15pct(mock_settings):
    mock_settings.return_value = _settings()
    ict = _structured_ict(8.5, session=8.5)
    blocked, reason = explosion_entry_window_blocked(_event(8.5), ict=ict)
    assert blocked is True
    assert "weak_local" in reason or "local_low" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_must_take_uses_near_base_band_without_ict_heat(mock_settings):
    """Must-take at ~15% pad must not re-raise the unstructured 28% floor."""
    mock_settings.return_value = _settings(
        explosion_early_window_max_move_pct=65.0,
        ict_structured_early_max_move_pct=65.0,
    )
    # Unstructured ICT — no flat→vertical heat, but pad is real.
    ict = ICTBreakoutSignal(
        active=True,
        pattern="displacement",
        score=30.0,
        reasons=["volume_awakening"],
        session_move_pct=40.0,
        base_relative_move_pct=15.0,
        base_premium=90.0,
        flat_then_vertical=False,
        local_swing_base=False,
        displacement=True,
        volume_awakening=True,
    )
    blocked, reason = explosion_entry_window_blocked(
        _event(40.0), ict=ict, top_must_take=False,
    )
    assert blocked is True
    assert "local_low" in reason or "weak_local" in reason

    blocked_mt, reason_mt = explosion_entry_window_blocked(
        _event(40.0), ict=ict, top_must_take=True,
    )
    assert blocked_mt is False, reason_mt


@patch("app.engines.explosion_detector.session_low_relative_move_pct", return_value=22.0)
@patch("app.engines.explosion_entry_guards.get_settings")
def test_weak_raw_ict_does_not_override_trusted_off_low(mock_settings, _off_low):
    """Raw ICT baseRel 7.4% must not block when off-low pad is already 22%."""
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
    assert blocked is True  # 22% still below unstructured 28% floor
    assert "local_low" in reason
    assert "weak_local" not in reason

    # With must-take / structured floor, 22% off-low is inside 15–65.
    blocked_mt, reason_mt = explosion_entry_window_blocked(
        _event(28.9), ict=ict, top_must_take=True,
    )
    assert blocked_mt is False, reason_mt


@patch("app.engines.eod_ftv_learning.learned_ftv_profile")
@patch("app.engines.explosion_entry_guards.get_settings")
def test_learned_near_base_tightens_elite_ceiling(mock_settings, mock_prof):
    """EOD-learned near-base max tightens the ELITE ceiling (tighten-only, floored)."""
    mock_settings.return_value = _settings(
        eod_learning_apply_enabled=True,
        eod_learning_apply_min_samples=5,
        eod_learning_near_base_floor_pct=25.0,
    )
    mock_prof.return_value = {"count": 10, "recommendedNearBaseMaxPct": 22.0}
    # Learned ceiling = max(floor 25, learned 22) = 25: a 30% pad chase is now blocked...
    b30, _ = explosion_entry_window_blocked(_event(30.0), ict=_structured_ict(30.0))
    assert b30 is True
    # ...but a genuine near-base 20% first lift still passes.
    b20, _ = explosion_entry_window_blocked(_event(20.0), ict=_structured_ict(20.0))
    assert b20 is False


@patch("app.engines.eod_ftv_learning.learned_ftv_profile")
@patch("app.engines.explosion_entry_guards.get_settings")
def test_learned_tighten_skipped_below_min_samples(mock_settings, mock_prof):
    """Not enough learned samples -> no tightening (falls back to the 40% cap)."""
    mock_settings.return_value = _settings(
        eod_learning_apply_enabled=True, eod_learning_apply_min_samples=5,
        eod_learning_near_base_floor_pct=25.0,
    )
    mock_prof.return_value = {"count": 2, "recommendedNearBaseMaxPct": 22.0}
    b30, _ = explosion_entry_window_blocked(_event(30.0), ict=_structured_ict(30.0))
    assert b30 is False  # within the untightened 40% cap
