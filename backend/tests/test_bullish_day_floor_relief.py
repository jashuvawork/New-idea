"""Lower entry floors on confirmed bullish / momentum-rally sessions."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.bullish_day_floor_relief import (
    bullish_day_context_active,
    bullish_day_first_lift_floors,
    bullish_day_structure_bypass_allowed,
)
from app.engines.day_adaptive_engine import build_day_adaptive_profile
from app.engines.explosion_detector import ExplosionEvent
from app.engines.explosion_entry_guards import immature_explosion_blocked
from app.engines.ict_breakout_monitor import ICTBreakoutSignal, first_lift_entry_readiness
from app.models.schemas import AutoTraderState, MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.bullish_day_floor_relief_enabled = True
    s.bullish_day_extra_rank_relief = 6.0
    s.bullish_day_structured_min_move_pct = 8.0
    s.bullish_day_first_lift_min_score = 45.0
    s.bullish_day_first_lift_min_quality = 50.0
    s.bullish_day_immature_local_base_min_move_pct = 8.0
    s.bullish_day_structure_bypass_min_score = 55.0
    s.bullish_day_structure_bypass_min_base_move_pct = 2.0
    s.bullish_day_structure_bypass_tiers_csv = "ELITE,EXPLODING"
    s.first_lift_trade_enabled = True
    s.first_lift_trade_min_score = 62.0
    s.first_lift_trade_min_quality = 65.0
    s.first_lift_trade_min_velocity_3s = 1.2
    s.first_lift_trade_min_velocity_9s = 0.8
    s.first_lift_trade_min_volume_surge = 2.0
    s.first_lift_trade_max_move_pct = 25.0
    s.first_lift_trade_min_momentum_shift_pct = 0.03
    s.ict_structured_early_min_move_pct = 15.0
    s.explosion_immature_block_enabled = True
    s.explosion_immature_min_session_move_pct = 28.0
    s.explosion_local_base_entry_min_move_pct = 15.0
    s.explosion_chase_use_local_base = True
    s.ict_v_rip_pad_min_move_pct = 2.0
    s.early_radar_pad_max_local_move_pct = 20.0
    s.early_radar_pad_exploding_prelaunch_min_score = 25.0
    s.ict_structured_early_min_move_pct = 15.0
    s.day_adaptive_good_day_rank_relief = 3.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24050.0,
        atmStrike=24050.0,
        spotChart=SpotChart(
            direction="BULLISH",
            momentum5Pct=0.12,
            momentum10Pct=0.08,
            momentum15Pct=0.05,
        ),
    )


def test_bullish_day_context_requires_rally_and_high_tier():
    assert bullish_day_context_active(
        day_mode="MOMENTUM RALLY",
        confidence_tier="ELITE",
    )
    assert not bullish_day_context_active(
        day_mode="CHOP DAY",
        confidence_tier="ELITE",
    )
    assert not bullish_day_context_active(
        day_mode="MOMENTUM RALLY",
        confidence_tier="MEDIUM",
    )


def test_structure_bypass_requires_tier_score_and_base_move():
    assert bullish_day_structure_bypass_allowed(
        tier="EXPLODING",
        score=60.0,
        base_move_pct=3.0,
        volume_awakening=False,
        day_mode="BULLISH DAY",
        confidence_tier="ELITE",
    )
    assert not bullish_day_structure_bypass_allowed(
        tier="BUILDING",
        score=60.0,
        base_move_pct=3.0,
        volume_awakening=False,
        day_mode="BULLISH DAY",
        confidence_tier="ELITE",
    )
    assert bullish_day_structure_bypass_allowed(
        tier="ELITE",
        score=55.0,
        base_move_pct=1.0,
        volume_awakening=True,
        day_mode="MOMENTUM RALLY",
        confidence_tier="HIGH",
    )


def _ict(**kwargs) -> ICTBreakoutSignal:
    base = dict(
        active=True,
        pattern="flat_vertical",
        score=60.0,
        reasons=["test"],
    )
    base.update(kwargs)
    return ICTBreakoutSignal(**base)


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_first_lift_structure_bypass_on_bullish_day(mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap()
    ict = _ict(
        first_lift=True,
        flat_then_vertical=False,
        base_relative_move_pct=10.0,
        flat_vertical_quality=55.0,
        volume_awakening=True,
    )
    event = SimpleNamespace(
        tier="EXPLODING",
        explosion_score=58.0,
        velocity_3s=1.5,
        velocity_9s=1.0,
        volume_surge=2.5,
    )
    alert = {
        "side": "CALL",
        "tier": "EXPLODING",
        "ictFirstLift": True,
        "ictBreakout": True,
        "ictFlatThenVertical": False,
        "ictBaseRelativeMovePct": 10.0,
        "flatVerticalQuality": 55.0,
        "explosionScore": 58.0,
        "velocity3s": 1.5,
        "velocity9s": 1.0,
        "volumeSurge": 2.5,
        "ictVolumeAwakening": True,
    }
    state = AutoTraderState(
        dailyStrategy={"dayMode": "MOMENTUM RALLY", "confidenceTier": "ELITE"},
    )

    ready, reason = first_lift_entry_readiness(
        snap=snap,
        event=event,
        ict=ict,
        alert=alert,
        day_mode="MOMENTUM RALLY",
        state=state,
    )

    assert ready is True
    assert "structure_not_confirmed" not in reason


@patch("app.engines.ict_breakout_monitor.get_settings")
def test_first_lift_still_blocks_structure_on_chop_day(mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap()
    ict = _ict(
        first_lift=True,
        flat_then_vertical=False,
        base_relative_move_pct=10.0,
        flat_vertical_quality=55.0,
        volume_awakening=True,
    )
    alert = {
        "tier": "EXPLODING",
        "ictFirstLift": True,
        "ictBreakout": True,
        "ictFlatThenVertical": False,
        "ictBaseRelativeMovePct": 10.0,
        "flatVerticalQuality": 55.0,
        "explosionScore": 58.0,
    }

    ready, reason = first_lift_entry_readiness(
        snap=snap,
        ict=ict,
        alert=alert,
        day_mode="CHOP DAY",
    )

    assert ready is False
    assert reason == "first_lift_structure_not_confirmed"


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.bullish_day_floor_relief.get_settings")
def test_immature_local_base_relief_on_bullish_day(
    mock_bd_settings,
    mock_guard_settings,
):
    settings = _settings()
    mock_bd_settings.return_value = settings
    mock_guard_settings.return_value = settings
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=24050.0,
        premium=120.0,
        velocity_3s=2.0,
        velocity_9s=1.5,
        velocity_15s=1.0,
        volume_surge=2.0,
        explosion_score=60.0,
        tier="EXPLODING",
        reason="first_lift",
        daily_move_pct=5.0,
        peak_move_pct=5.0,
    )
    ict = _ict(
        flat_then_vertical=True,
        local_swing_base=True,
        base_relative_move_pct=10.0,
        session_move_pct=5.0,
    )

    with patch(
        "app.engines.bullish_day_floor_relief.bullish_day_context_active",
        return_value=True,
    ):
        blocked, reason = immature_explosion_blocked(event, ict=ict)

    assert blocked is False
    assert reason == ""


@patch("app.engines.day_adaptive_engine.get_settings")
@patch("app.engines.bullish_day_floor_relief.bullish_day_context_active", return_value=True)
@patch("app.engines.whipsaw_guards.is_bearish_sideways_session", return_value=False)
@patch("app.engines.chop_day_guards.is_chop_session", return_value=False)
@patch("app.engines.chop_day_guards.in_momentum_rally_window", return_value=True)
def test_day_adaptive_extra_rank_relief_on_bullish_day(
    _rally,
    _chop,
    _bear,
    _bullish,
    mock_settings,
):
    mock_settings.return_value = _settings()
    profile = build_day_adaptive_profile(
        "MOMENTUM RALLY",
        "ELITE",
        {"NIFTY": _snap()},
    )
    assert profile.min_rank_relief >= 9.0  # ELITE base 9 + bullish extra 6
    assert any("Bullish day" in line for line in profile.playbook)


def test_bullish_day_first_lift_floors_defaults():
    floors = bullish_day_first_lift_floors(_settings())
    assert floors["minMove"] == 8.0
    assert floors["minScore"] == 45.0
    assert floors["immatureLocalBaseMinMove"] == 8.0
