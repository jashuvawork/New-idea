"""Per-trade entry timing — block cold ELITE fills like Aug4 NIFTY 24550 PUT."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.elite_never_block import elite_never_block_active
from app.engines.entry_timing import (
    assess_entry_timing,
    cap_lots_for_timing,
    elite_bypass_allowed_for_timing,
    timing_allows_full_size,
    timing_blocks_entry,
)
from app.engines.explosion_confidence import is_high_conviction_entry
from app.engines.ict_breakout_monitor import ICTBreakoutSignal
from app.models.schemas import Breadth, MarketPhase, Regime, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.entry_timing_assessment_enabled = True
    s.entry_timing_cold_max_velocity_3s = 1.5
    s.entry_timing_ok_min_velocity_3s = 1.5
    s.entry_timing_good_min_velocity_3s = 2.0
    s.entry_timing_late_min_peak_pct = 55.0
    s.entry_timing_late_max_live_velocity_3s = 1.0
    s.entry_timing_cold_block_on_chop = True
    s.entry_timing_cold_lot_cap = 3
    s.entry_timing_elite_bypass_requires_hot = True
    s.entry_timing_structured_cold_base_allow = True
    s.entry_timing_structured_cold_max_lots = True
    s.entry_timing_structured_cold_require_heat = True
    s.entry_timing_structured_cold_require_aligned = True
    s.explosion_elite_never_block_enabled = True
    s.explosion_early_window_min_move_pct = 28.0
    s.explosion_early_window_max_move_pct = 55.0
    s.ict_structured_early_entry_enabled = True
    s.ict_structured_early_min_move_pct = 10.0
    s.ict_structured_early_max_move_pct = 45.0
    s.explosion_chase_use_local_base = True
    s.explosion_local_base_trust_min_move_pct = 8.0
    s.high_conviction_sizing_enabled = True
    s.high_conviction_min_score = 90.0
    s.high_conviction_min_chart_confidence = 56.9
    s.high_conviction_min_velocity_3s = 2.0
    s.missed_explosion_promote_min_move_pct = 28.0
    s.missed_explosion_promote_max_move_pct = 55.0
    s.structured_near_atm_max_otm_steps = 3
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _event(*, v3: float = 0.8, daily: float = 384.0, peak: float = 384.0, tier: str = "ELITE"):
    return SimpleNamespace(
        symbol="NIFTY",
        side=Side.PUT,
        strike=24550.0,
        premium=71.0,
        velocity_3s=v3,
        velocity_9s=0.5,
        daily_move_pct=daily,
        peak_move_pct=peak,
        tier=tier,
        explosion_score=100.0,
    )


def _ict(*, base_rel: float = 28.8, flat: bool = True) -> ICTBreakoutSignal:
    return ICTBreakoutSignal(
        active=True,
        pattern="mega_rip",
        score=79.0,
        reasons=["local_swing_base_53.8", "early_local_break_29%"],
        session_move_pct=384.0,
        base_relative_move_pct=base_rel,
        base_premium=53.8,
        flat_then_vertical=flat,
        local_swing_base=True,
        displacement=True,
        volume_awakening=True,
        mega_rip=True,
    )


def _snap(regime: str = "CHOP") -> SymbolSnapshot:
    reg = Regime.CHOP if regime == "CHOP" else Regime.TREND_EXPANSION
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        spot=24509.0,
        atmStrike=24500.0,
        regime=reg,
        tradeQualityScore=52.0,
        breadth=Breadth(bias="BEARISH", score=28.0, aligned=True),
        spotChart=SpotChart(
            direction="BEARISH",
            timeframe="5m",
            barCount=20,
            momentum5Pct=-0.4,
            momentum15Pct=-0.3,
            trendStrength=80.0,
        ),
    )


@patch("app.engines.entry_timing.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
def test_aug4_structured_cold_base_allowed_full_size(mock_g1, mock_g2):
    """24550 PE: cold v3 but local base still in window → take at max lots."""
    s = _settings()
    mock_g1.return_value = s
    mock_g2.return_value = s
    timing = assess_entry_timing(
        _event(v3=0.8),
        ict=_ict(),
        snap=_snap("CHOP"),
        midday_chop=True,
    )
    assert timing["assessment"] == "COLD_BASE"
    assert timing["action"] == "allow"
    assert timing.get("structuredColdBase") is True
    blocked, _ = timing_blocks_entry(timing)
    assert blocked is False
    assert cap_lots_for_timing(41, timing) == 41  # no lot_cap action
    assert timing_allows_full_size(timing)
    # Elite never-block still needs GOOD (hot) — max lots is separate.
    assert not elite_bypass_allowed_for_timing(timing)


@patch("app.engines.entry_timing.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
def test_cold_unstructured_still_blocked_on_chop(mock_g1, mock_g2):
    """No local-base structure → chop cold block still applies."""
    s = _settings()
    mock_g1.return_value = s
    mock_g2.return_value = s
    ict = ICTBreakoutSignal(
        active=True,
        pattern="watch",
        score=20.0,
        reasons=[],
        session_move_pct=40.0,
        base_relative_move_pct=0.0,
        flat_then_vertical=False,
        local_swing_base=False,
        displacement=False,
        volume_awakening=False,
    )
    timing = assess_entry_timing(
        _event(v3=0.8, daily=40.0, peak=42.0),
        ict=ict,
        snap=_snap("CHOP"),
        midday_chop=True,
    )
    assert timing["assessment"] in ("COLD", "LATE", "CHASE")
    blocked, reason = timing_blocks_entry(timing)
    assert blocked is True
    assert "entry_timing_" in reason


@patch("app.engines.entry_timing.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
def test_hot_near_base_is_good(mock_g1, mock_g2):
    s = _settings()
    mock_g1.return_value = s
    mock_g2.return_value = s
    timing = assess_entry_timing(
        _event(v3=2.8, daily=30.0, peak=32.0),
        ict=_ict(base_rel=30.0),
        snap=_snap("TRENDING"),
        midday_chop=False,
    )
    assert timing["assessment"] == "GOOD"
    blocked, _ = timing_blocks_entry(timing)
    assert blocked is False
    assert timing_allows_full_size(timing)
    assert elite_bypass_allowed_for_timing(timing)


@patch("app.engines.entry_timing.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
def test_late_chase_blocked(mock_g1, mock_g2):
    s = _settings()
    mock_g1.return_value = s
    mock_g2.return_value = s
    # No trustworthy local base — session already extended, live cold.
    ict = ICTBreakoutSignal(
        active=True,
        pattern="displacement",
        score=30.0,
        reasons=[],
        session_move_pct=90.0,
        base_relative_move_pct=0.0,
        flat_then_vertical=False,
        local_swing_base=False,
        displacement=True,
    )
    timing = assess_entry_timing(
        _event(v3=0.6, daily=90.0, peak=95.0),
        ict=ict,
        snap=_snap("TRENDING"),
    )
    assert timing["assessment"] in ("LATE", "CHASE", "COLD")
    blocked, _ = timing_blocks_entry(timing)
    assert blocked is True


@patch("app.engines.entry_timing.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
def test_cold_lot_cap_when_not_chop_block(mock_g1, mock_g2):
    s = _settings(entry_timing_cold_block_on_chop=False)
    mock_g1.return_value = s
    mock_g2.return_value = s
    # Unstructured ELITE — pure COLD soft-cap (not structured cold-base).
    ict = ICTBreakoutSignal(
        active=True,
        pattern="displacement",
        score=30.0,
        reasons=[],
        session_move_pct=32.0,
        base_relative_move_pct=0.0,
        flat_then_vertical=False,
        local_swing_base=False,
        displacement=True,
        volume_awakening=False,
    )
    timing = assess_entry_timing(
        _event(v3=0.8, daily=32.0, peak=35.0),
        ict=ict,
        snap=_snap("TRENDING"),
        midday_chop=False,
    )
    assert timing["assessment"] == "COLD"
    assert timing["action"] == "lot_cap"
    assert cap_lots_for_timing(41, timing) == 3


@patch("app.engines.entry_timing.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
def test_structured_cold_base_requires_alignment(mock_g1, mock_g2):
    s = _settings()
    mock_g1.return_value = s
    mock_g2.return_value = s
    snap = _snap("CHOP")
    snap.breadth = Breadth(bias="BULLISH", score=40.0, aligned=False)
    snap.spotChart = SpotChart(
        direction="BULLISH",
        timeframe="5m",
        barCount=20,
        momentum5Pct=0.2,
        momentum15Pct=0.1,
        trendStrength=40.0,
    )
    timing = assess_entry_timing(
        _event(v3=0.8),
        ict=_ict(),
        snap=snap,
        midday_chop=True,
    )
    # PUT vs BULLISH → no cold-base allow; chop cold/late still blocks.
    assert timing["assessment"] != "COLD_BASE"
    blocked, _ = timing_blocks_entry(timing)
    assert blocked is True


@patch("app.engines.elite_never_block.get_settings")
@patch("app.engines.entry_timing.get_settings")
@patch("app.engines.explosion_entry_guards.get_settings")
def test_elite_bypass_refuses_cold(mock_g1, mock_g2, mock_elite):
    s = _settings()
    mock_g1.return_value = s
    mock_g2.return_value = s
    mock_elite.return_value = s
    ev = _event(v3=0.8)
    assert elite_never_block_active(event=ev, snap=_snap("CHOP")) is False


@patch("app.engines.elite_never_block.get_settings")
@patch("app.engines.entry_timing.get_settings")
def test_elite_bypass_allows_hot(mock_et, mock_elite):
    s = _settings()
    mock_et.return_value = s
    mock_elite.return_value = s
    ev = _event(v3=3.0, daily=32.0, peak=35.0)
    assert elite_never_block_active(
        event=ev,
        snap=_snap("TRENDING"),
        timing={"assessment": "GOOD", "action": "allow", "reasons": ["hot"]},
    ) is True


@patch("app.engines.explosion_confidence.get_settings")
def test_high_conviction_requires_hot_velocity(mock_s):
    mock_s.return_value = _settings()
    snap = _snap("TRENDING")
    assert (
        is_high_conviction_entry(
            side=Side.PUT,
            snap=snap,
            tier="ELITE",
            score=100.0,
            move_pct=30.0,
            chart_confidence=90.0,
            velocity_3s=0.8,
        )
        is False
    )
    assert (
        is_high_conviction_entry(
            side=Side.PUT,
            snap=snap,
            tier="ELITE",
            score=100.0,
            move_pct=30.0,
            chart_confidence=90.0,
            velocity_3s=2.5,
        )
        is True
    )
