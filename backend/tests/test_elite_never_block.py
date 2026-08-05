"""ELITE explosions must not be blocked by trap/chase/stand-down gates."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.elite_never_block import elite_never_block_active
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
def test_fake_trap_skips_elite(mock_elite_s, mock_guard_s):
    s = _enb_settings()
    mock_elite_s.return_value = s
    mock_guard_s.return_value = s
    blocked, reason, meta = detect_fake_explosion_trap(_cand("ELITE"), _snap())
    assert blocked is False
    assert meta.get("eliteNeverBlock") is True


@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.engines.elite_never_block.get_settings")
def test_late_fade_skips_elite(mock_elite_s, mock_ict_s):
    s = _enb_settings()
    mock_elite_s.return_value = s
    mock_ict_s.return_value = s
    blocked, reason = late_fade_chase_blocked(_event(tier="ELITE", peak=250.0, v3=0.2))
    assert blocked is False


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
