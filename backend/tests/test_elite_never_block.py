"""ELITE explosions must not be blocked by trap/chase/stand-down gates."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.elite_never_block import (
    elite_must_take_bypass_allowed,
    elite_never_block_active,
)
from app.engines.explosion_entry_guards import (
    detect_fake_explosion_trap,
    extended_session_chase_blocked,
    live_explosion_confirmation_blocked,
)
from app.engines.ict_breakout_monitor import late_fade_chase_blocked
from app.models.schemas import Breadth, MarketPhase, Regime, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _enb_settings(**kwargs):
    """Legacy ELITE bypass tests: hot-timing gate off, must-take off (isolate path)."""
    s = MagicMock()
    s.explosion_elite_never_block_enabled = True
    s.entry_timing_elite_bypass_requires_hot = False
    s.explosion_top_must_take_enabled = False
    s.explosion_extended_chase_block_enabled = True
    s.explosion_chase_use_local_base = False
    s.explosion_extended_chase_min_move_pct = 70.0
    s.fake_explosion_trap_enabled = True
    s.ict_late_chase_block_enabled = True
    s.explosion_live_confirm_enabled = True
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


def _event(tier="ELITE", peak=250.0, v3=0.4):
    return SimpleNamespace(
        tier=tier,
        peak_move_pct=peak,
        daily_move_pct=peak,
        velocity_3s=v3,
        velocity_9s=0.2,
        volume_surge=1.0,
        side=Side.PUT,
        strike=24000.0,
        symbol="NIFTY",
        premium=37.0,
        explosion_score=100.0,
    )


def _snap():
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=23970.0,
        atmStrike=24000.0,
        regime=Regime.RANGE_BOUND,
        tradeQualityScore=50.0,
        breadth=Breadth(bias="BEARISH", score=44, aligned=True),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=-0.1),
    )


def _cand(tier="ELITE"):
    ev = _event(tier=tier)
    return SimpleNamespace(
        mode="explosion",
        tier=tier,
        side=Side.PUT,
        strike=24000.0,
        score=100.0,
        explosion_event=ev,
        alert={"tier": tier, "peakMovePct": 250.0},
    )


@patch("app.engines.elite_never_block.get_settings")
def test_elite_never_block_active(mock_s):
    mock_s.return_value = _enb_settings()
    assert elite_never_block_active(tier="ELITE") is True
    assert elite_never_block_active(tier="EXPLODING") is False
    assert elite_never_block_active(event=_event(tier="ELITE")) is True


@patch("app.engines.elite_never_block.get_settings")
def test_elite_never_block_disabled(mock_s):
    mock_s.return_value = _enb_settings(explosion_elite_never_block_enabled=False)
    assert elite_never_block_active(tier="ELITE") is False


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.elite_never_block.get_settings")
def test_extended_chase_skips_elite(mock_elite_s, mock_guard_s):
    s = _enb_settings()
    mock_elite_s.return_value = s
    mock_guard_s.return_value = s
    blocked, reason = extended_session_chase_blocked(_event(tier="ELITE", peak=250.0))
    assert blocked is False
    assert reason == ""


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.elite_never_block.get_settings")
def test_extended_chase_still_blocks_exploding(mock_elite_s, mock_guard_s):
    s = _enb_settings()
    mock_elite_s.return_value = s
    mock_guard_s.return_value = s
    blocked, reason = extended_session_chase_blocked(_event(tier="EXPLODING", peak=250.0))
    assert blocked is True
    assert "explosion_extended_chase" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.elite_never_block.get_settings")
def test_fake_trap_does_not_short_circuit_on_elite(mock_elite_s, mock_guard_s):
    """ELITE / must-take must not skip fake-trap evaluation."""
    s = _enb_settings()
    # Enough attrs for detect_fake_explosion_trap to run without MagicMock noise.
    s.fake_explosion_trap_min_session_move_pct = 28.0
    s.fake_explosion_trap_extended_move_pct = 55.0
    s.fake_explosion_trap_max_premium_mom_pct = 0.15
    s.fake_explosion_trap_block_on_conflict = True
    s.fake_explosion_trap_min_conflict_flags = 3
    s.fake_explosion_trap_chop_elite_lot_cap = 6
    s.fake_explosion_trap_otm_requires_or_breakout = True
    s.fake_explosion_trap_post_win_lot_cap = 8
    s.fake_explosion_trap_post_win_max_pnl_inr = 3000.0
    s.fake_explosion_trap_post_win_lookback = 1
    s.fake_explosion_trap_psychology_escalate = True
    s.fake_explosion_trap_midday_require_structure = True
    s.fake_explosion_trap_skip_soft_cut_base_window = True
    s.fake_explosion_trap_skip_soft_cut_near_otm = True
    s.explosion_early_window_max_move_pct = 65.0
    s.explosion_chase_use_local_base = True
    s.nifty_strike_step = 50.0
    s.sensex_strike_step = 100.0
    s.banknifty_strike_step = 100.0
    s.moneyness_atm_tolerance_points = 50.0
    mock_elite_s.return_value = s
    mock_guard_s.return_value = s
    blocked, reason, meta = detect_fake_explosion_trap(_cand("ELITE"), _snap())
    assert meta.get("eliteNeverBlock") is not True
    assert meta.get("topMustTake") is not True


@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.engines.elite_never_block.get_settings")
def test_late_fade_still_blocks_elite(mock_elite_s, mock_ict_s):
    """Cooling ELITE after a hard peak must still late-fade block."""
    s = _enb_settings()
    s.ict_late_chase_min_peak_pct = 75.0
    s.ict_late_chase_max_live_velocity_3s = 1.0
    s.explosion_early_window_max_move_pct = 65.0
    s.explosion_local_base_chase_max_move_pct = 40.0
    s.explosion_chase_use_local_base = True
    mock_elite_s.return_value = s
    mock_ict_s.return_value = s
    blocked, reason = late_fade_chase_blocked(_event(tier="ELITE", peak=250.0, v3=0.2))
    assert blocked is True
    assert "late_fade" in reason


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.elite_never_block.get_settings")
def test_live_confirm_skips_elite(mock_elite_s, mock_guard_s):
    s = _enb_settings()
    mock_elite_s.return_value = s
    mock_guard_s.return_value = s
    blocked, reason = live_explosion_confirmation_blocked(_event(tier="ELITE", v3=0.2))
    assert blocked is False


def test_default_config_enables_elite_never_block():
    from app.config import Settings

    assert Settings().explosion_elite_never_block_enabled is True
    assert Settings().explosion_top_must_take_enabled is True
    assert Settings().explosion_top_must_take_require_expansion_confirm_enabled is True


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.elite_never_block.get_settings")
def test_must_take_bypass_blocked_on_anti_chase(mock_elite_s, mock_guard_s):
    from app.config import Settings
    from app.engines.explosion_detector import ExplosionEvent

    settings = Settings(
        explosion_top_must_take_enabled=True,
        explosion_top_must_take_min_score=50.0,
        explosion_top_must_take_require_chart_align=False,
        ict_structured_early_min_move_pct=10.0,
        ict_structured_early_max_move_pct=65.0,
    )
    mock_elite_s.return_value = settings
    mock_guard_s.return_value = settings
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24200.0,
        atmStrike=24200.0,
        tradeQualityScore=70.0,
        breadth=Breadth(bias="BULLISH", score=70.0, aligned=True),
        spotChart=SpotChart(direction="BULLISH"),
    )
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24200.0,
        premium=104.55,
        velocity_3s=0.87,
        velocity_9s=0.5,
        velocity_15s=0.0,
        volume_surge=1.0,
        explosion_score=100.0,
        tier="ELITE",
        reason="test",
        daily_move_pct=15.0,
        peak_move_pct=15.0,
    )
    ict = SimpleNamespace(
        base_relative_move_pct=15.0,
        base_armed=True,
        active=True,
        flat_then_vertical=False,
        volume_awakening=False,
    )
    alert = {
        "explosionScore": 100.0,
        "localBaseMovePct": 15.0,
        "ictBaseRelativeMovePct": 15.0,
    }
    assert elite_never_block_active(event=event, alert=alert, snap=snap) is True
    assert elite_must_take_bypass_allowed(event=event, alert=alert, snap=snap, ict=ict) is False
