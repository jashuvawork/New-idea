"""Live explosion confirmation — block Jul23 wrong-timing entries.

Day book patterns these gates must stop:
1. NIFTY 23900 PE ELITE v3=0.26 ict=watch (stale sticky tier)
2. NIFTY 23900 PE ELITE v3=2.35 displacement-only
3. SENSEX 76200 PE midday displacement spike (no flat→vertical)
4. Still ALLOW SENSEX 76300 PE ICT flat→vertical + hot velocity
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.engines.explosion_entry_guards import (
    detect_fake_explosion_trap,
    live_explosion_confirmation_blocked,
)
from app.models.schemas import Side


def _settings(**overrides):
    s = MagicMock()
    s.explosion_live_confirm_enabled = True
    s.explosion_live_confirm_min_velocity_3s = 2.0
    s.explosion_live_confirm_ict_min_velocity_3s = 1.5
    s.explosion_live_confirm_require_structure = True
    s.explosion_live_confirm_hot_velocity_3s = 8.0
    s.explosion_live_confirm_premium_capture_bypass = True
    s.explosion_live_confirm_premium_min_vol_surge = 1.3
    s.explosion_early_window_min_move_pct = 28.0
    s.fake_explosion_trap_enabled = True
    s.fake_explosion_trap_midday_require_structure = True
    s.fake_explosion_trap_block_on_conflict = True
    s.fake_explosion_trap_min_session_move_pct = 28.0
    s.fake_explosion_trap_extended_move_pct = 55.0
    s.fake_explosion_trap_min_conflict_flags = 3
    s.fake_explosion_trap_chop_elite_lot_cap = 6
    s.fake_explosion_trap_post_win_lot_cap = 8
    s.fake_explosion_trap_otm_requires_or_breakout = True
    s.fake_explosion_trap_skip_soft_cut_base_window = True
    s.fake_explosion_trap_psychology_escalate = True
    s.midday_chop_start_hour = 11
    s.midday_chop_start_minute = 30
    s.midday_chop_end_hour = 13
    s.midday_chop_end_minute = 30
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _event(*, tier="ELITE", v3=0.26, v9=0.5, move=27.0, vol_surge=2.5):
    return SimpleNamespace(
        tier=tier,
        velocity_3s=v3,
        velocity_9s=v9,
        daily_move_pct=move,
        peak_move_pct=move,
        volume_surge=vol_surge,
        symbol="NIFTY",
        strike=23900.0,
        side=Side.PUT,
        premium=150.0,
    )


def _ict(**kwargs):
    base = dict(
        active=True,
        flat_then_vertical=False,
        mega_rip=False,
        premium_fvg=False,
        volume_awakening=False,
        displacement=True,
        session_move_pct=27.0,
        pattern="displacement",
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


@patch("app.engines.explosion_entry_guards.get_settings")
def test_stale_elite_dead_velocity_blocked(mock_s):
    mock_s.return_value = _settings()
    blocked, reason = live_explosion_confirmation_blocked(
        _event(v3=0.26, move=27.0), ict=_ict(active=False, displacement=False),
        midday_chop=False,
    )
    assert blocked is True
    assert "stale_live_velocity" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_lukewarm_displacement_only_blocked(mock_s):
    mock_s.return_value = _settings()
    blocked, reason = live_explosion_confirmation_blocked(
        _event(v3=2.35, move=26.0), ict=_ict(displacement=True),
        midday_chop=False,
    )
    assert blocked is True
    assert "no_ict_structure" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_midday_hot_displacement_blocked(mock_s):
    mock_s.return_value = _settings()
    blocked, reason = live_explosion_confirmation_blocked(
        _event(tier="ELITE", v3=22.0, move=22.0),
        ict=_ict(displacement=True, session_move_pct=22.0),
        midday_chop=True,
    )
    assert blocked is True
    assert "midday_no_ict_structure" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_ict_flat_vertical_hot_allowed(mock_s):
    """Jul23 76300 PE profile — structure + heat must pass."""
    mock_s.return_value = _settings()
    blocked, reason = live_explosion_confirmation_blocked(
        _event(tier="ELITE", v3=20.9, move=33.0),
        ict=_ict(
            flat_then_vertical=True,
            volume_awakening=True,
            displacement=True,
            session_move_pct=33.0,
            pattern="flat_then_vertical",
        ),
        midday_chop=True,
    )
    assert blocked is False


@patch("app.engines.explosion_entry_guards.get_settings")
def test_hot_non_ict_outside_midday_allowed(mock_s):
    """Extreme hot + early-window move can pass without ICT outside midday."""
    mock_s.return_value = _settings()
    blocked, reason = live_explosion_confirmation_blocked(
        _event(v3=12.0, move=35.0), ict=None, midday_chop=False,
    )
    assert blocked is False


@patch("app.engines.explosion_entry_guards.get_settings")
def test_premium_capture_slow_grind_allowed(mock_s):
    """NIFTY 24250 PE 1pm profile — slow volume-backed afternoon consolidation
    breakout (low velocity, no ICT structure) is live-confirmed by its capture
    classification + volume surge and must not be blocked on the velocity floor."""
    mock_s.return_value = _settings()
    blocked, reason = live_explosion_confirmation_blocked(
        _event(tier="BUILDING", v3=1.1, v9=1.35, move=0.0, vol_surge=1.62),
        ict=_ict(active=False, displacement=False, flat_then_vertical=False),
        midday_chop=False,
        premium_capture=True,
    )
    assert blocked is False


@patch("app.engines.explosion_entry_guards.get_settings")
def test_premium_capture_low_volume_still_blocked(mock_s):
    """A structure-less, low-volume slow spike cannot ride the premium bypass —
    without a real volume surge it is still blocked on the velocity floor."""
    mock_s.return_value = _settings()
    blocked, reason = live_explosion_confirmation_blocked(
        _event(tier="BUILDING", v3=1.1, v9=1.35, move=0.0, vol_surge=1.0),
        ict=_ict(active=False, displacement=False, flat_then_vertical=False),
        midday_chop=False,
        premium_capture=True,
    )
    assert blocked is True
    assert "stale_live_velocity" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
def test_premium_capture_flag_off_no_bypass(mock_s):
    """Bypass is opt-in — with premium_capture=False the slow grind is still blocked."""
    mock_s.return_value = _settings()
    blocked, reason = live_explosion_confirmation_blocked(
        _event(tier="BUILDING", v3=1.1, v9=1.35, move=0.0, vol_surge=1.62),
        ict=_ict(active=False, displacement=False, flat_then_vertical=False),
        midday_chop=False,
        premium_capture=False,
    )
    assert blocked is True


@patch("app.engines.explosion_entry_guards._midday_chop_active", return_value=True)
@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.resolve_preferred_moneyness", return_value="ATM")
def test_trap_midday_no_structure_hard_blocks(mock_money, mock_s, _mid):
    mock_s.return_value = _settings()
    snap = MagicMock()
    snap.regime = "TREND"
    snap.spotChart = None
    snap.spot = 76200.0
    snap.atmStrike = 76200.0
    cand = MagicMock()
    cand.mode = "explosion"
    cand.side = Side.PUT
    cand.strike = 76200.0
    cand.score = 100.0
    cand.tier = "ELITE"
    cand.explosion_event = _event(tier="ELITE", v3=22.0, move=22.0)
    cand.explosion_event.symbol = "SENSEX"
    cand.explosion_event.strike = 76200.0

    blocked, reason, meta = detect_fake_explosion_trap(
        cand, snap, ict=_ict(displacement=True, flat_then_vertical=False),
    )
    assert blocked is True
    assert reason == "fake_explosion_trap_midday_no_structure"
    assert meta.get("action") == "block"


@patch("app.engines.explosion_entry_guards._midday_chop_active", return_value=True)
@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.moneyness.resolve_preferred_moneyness", return_value="ATM")
def test_trap_midday_with_structure_not_hard_blocked(mock_money, mock_s, _mid):
    mock_s.return_value = _settings()
    snap = MagicMock()
    snap.regime = "TREND"
    snap.spotChart = None
    snap.spot = 76300.0
    snap.atmStrike = 76300.0
    cand = MagicMock()
    cand.mode = "explosion"
    cand.side = Side.PUT
    cand.strike = 76300.0
    cand.score = 190.0
    cand.tier = "ELITE"
    cand.explosion_event = _event(tier="ELITE", v3=20.9, move=33.0)
    cand.explosion_event.symbol = "SENSEX"
    cand.explosion_event.strike = 76300.0

    blocked, reason, meta = detect_fake_explosion_trap(
        cand,
        snap,
        ict=_ict(
            flat_then_vertical=True,
            volume_awakening=True,
            displacement=True,
            session_move_pct=33.0,
        ),
    )
    # Structure present → must not hard-block via midday_no_structure
    assert reason != "fake_explosion_trap_midday_no_structure"
    if blocked:
        assert meta.get("action") != "block" or "no_structure" not in reason
