"""Near-base ICT tier promotion — faster CE/PE detection all day."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.explosion_detector import (
    ExplosionEvent,
    _strike_key,
    apply_ict_near_base_tier_promotion,
    event_to_dict,
    reset_detector_state_for_tests,
)
from app.engines.ict_breakout_monitor import analyze_ict_breakout
from app.models.schemas import Side
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _ict_settings(**overrides):
    s = settings_mock(
        ict_breakout_monitor_enabled=True,
        ict_flat_base_max_range_pct=8.0,
        ict_flat_base_use_lowest=True,
        ict_structured_early_min_move_pct=15.0,
        ict_first_lift_appear_min_move_pct=8.0,
        ict_first_lift_appear_enabled=True,
        ict_first_lift_min_velocity_3s=1.2,
        elite_local_base_max_move_pct=40.0,
        near_base_tier_promotion_min_quality=65.0,
        explosion_immature_min_session_move_pct=28.0,
        ict_structured_early_max_move_pct=65.0,
        ict_early_vertical_min_session_move_pct=28.0,
        ict_displacement_min_velocity_3s=2.2,
        ict_vertical_min_session_move_pct=80.0,
        ict_volume_surge_awaken_min=2.0,
        explosion_volume_awaken_min=25000,
        ict_local_base_lookback_polls=16,
        ict_local_base_min_dump_pct=25.0,
        **overrides,
    )
    return s


def _seed_flat_base(*, symbol: str, strike: float, side: Side, base: float, lift: float) -> None:
    from app.engines.explosion_detector import _history

    key = _strike_key(strike, side)
    now = datetime.now(IST)
    hist = deque(maxlen=40)
    for i, prem in enumerate([base + 1, base, base + 0.5, base + 1, base + 2, base, base + 0.5, base]):
        hist.append((now - timedelta(seconds=90 - i * 5), prem, 12000))
    hist.append((now, lift, 160000))
    _history.setdefault(symbol, {})[key] = hist


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
@patch("app.engines.ict_breakout_monitor.get_settings")
def test_first_lift_appears_at_8pct_off_base(mock_get_settings, side):
    """CE + PE: first_lift stamps at ~8% appear floor, not 15%."""
    mock_get_settings.return_value = _ict_settings()
    base = 100.0
    lift = 108.5  # ~8.5% off base
    symbol, strike = "NIFTY", 23300.0
    _seed_flat_base(symbol=symbol, strike=strike, side=side, base=base, lift=lift)

    ict = analyze_ict_breakout(
        symbol=symbol,
        side=side,
        strike=strike,
        premium=lift,
        session_move_pct=8.5,
        peak_move_pct=8.5,
        velocity_3s=1.4,
        velocity_9s=1.0,
        volume_surge=2.5,
        volume=160000,
        tier="WATCH",
        reason="probe",
    )
    assert ict.first_lift is True
    assert 8.0 <= ict.base_relative_move_pct <= 10.0


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
@patch("app.engines.ict_breakout_monitor.get_settings")
def test_watch_low_score_promoted_via_event_to_dict(mock_get_settings, side):
    """WATCH + low score + ICT first_lift → BUILDING/EXPLODING in alert output."""
    reset_detector_state_for_tests()
    mock_get_settings.return_value = _ict_settings()
    base = 89.0
    lift = 96.5  # ~8.4% off base
    symbol, strike = "NIFTY", 23300.0
    _seed_flat_base(symbol=symbol, strike=strike, side=side, base=base, lift=lift)

    event = ExplosionEvent(
        symbol=symbol,
        side=side,
        strike=strike,
        premium=lift,
        velocity_3s=1.5,
        velocity_9s=1.1,
        velocity_15s=0.8,
        volume_surge=2.8,
        volume=160000,
        explosion_score=18.0,
        tier="WATCH",
        reason="lowScoreProbe",
        daily_move_pct=8.4,
        peak_move_pct=8.4,
    )
    settings = _ict_settings()
    with (
        patch("app.config.get_settings", return_value=settings),
        patch("app.engines.ict_breakout_monitor.get_settings", return_value=settings),
    ):
        alert = event_to_dict(event, snap=None)

    assert alert["ictFirstLift"] is True
    assert alert["tier"] in ("BUILDING", "EXPLODING")
    assert alert["tradeable"] is True
    assert alert["explosionScore"] >= 38.0


def test_apply_ict_near_base_tier_promotion_disabled():
    settings = _ict_settings(near_base_ict_tier_promotion_enabled=False)
    ict = MagicMock(
        first_lift=True,
        flat_then_vertical=True,
        active=True,
        base_relative_move_pct=12.0,
        flat_vertical_quality=75.0,
        volume_awakening=True,
        score=40.0,
    )
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.CALL,
        strike=23300.0,
        premium=112.0,
        velocity_3s=1.5,
        velocity_9s=1.0,
        velocity_15s=0.5,
        volume_surge=2.0,
        volume=50000,
        explosion_score=20.0,
        tier="WATCH",
        reason="test",
        daily_move_pct=12.0,
        peak_move_pct=12.0,
    )
    apply_ict_near_base_tier_promotion(event, ict, settings)
    assert event.tier == "WATCH"


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_apply_ict_near_base_tier_promotion_exploding(side):
    settings = _ict_settings()
    ict = MagicMock(
        first_lift=True,
        flat_then_vertical=True,
        active=True,
        armed_base_launch=False,
        elite_base_ready=False,
        v_rip_ready=False,
        building_rip_ready=False,
        armed_base_sustained_lift=False,
        base_relative_move_pct=12.0,
        flat_vertical_quality=72.0,
        volume_awakening=True,
        score=40.0,
    )
    event = ExplosionEvent(
        symbol="NIFTY",
        side=side,
        strike=23300.0,
        premium=112.0,
        velocity_3s=1.5,
        velocity_9s=1.0,
        velocity_15s=0.5,
        volume_surge=2.0,
        volume=50000,
        explosion_score=20.0,
        tier="WATCH",
        reason="test",
        daily_move_pct=12.0,
        peak_move_pct=12.0,
    )
    apply_ict_near_base_tier_promotion(event, ict, settings)
    assert event.tier == "EXPLODING"
    assert "ictNearBaseTierPromotion" in event.reason
