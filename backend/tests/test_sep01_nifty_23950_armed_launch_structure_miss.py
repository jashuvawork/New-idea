"""Sep01 NIFTY PUT 23950 — armed_base_launch at local base before flat→vertical confirms."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.ict_breakout_monitor import ICTBreakoutSignal, first_lift_entry_readiness
from app.engines.pad_lane_capture import (
    _armed_base_launch_pad_chart_signal,
    resolve_strict_pad_lane_for_entry,
)
from app.engines.spot_direction import premium_blocks_entry
from app.engines.winner_entry_guards import premium_fading_blocks_entry
from app.models.schemas import MarketPhase, PremiumChart, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _sep01_put_23950_alert(**overrides) -> dict:
    alert = {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 23950.0,
        "premium": 22.0,
        "tier": "ELITE",
        "momentType": "armed_base_launch",
        "explosionScore": 100.0,
        "ictArmedBaseLaunch": True,
        "ictFirstLift": True,
        "localBaseMovePct": 9.5,
        "ictBaseRelativeMovePct": 9.5,
        "offLowMovePct": 9.5,
        "peakMovePct": 12.0,
        "velocity3s": 2.5,
        "velocity9s": 1.8,
        "volumeAwaken": True,
        "volumeSurge": 2.0,
        "flatVerticalQuality": 70.0,
    }
    alert.update(overrides)
    return alert


def _explosion_event(**overrides):
    base = SimpleNamespace(
        symbol="NIFTY",
        side=Side.PUT,
        strike=23950.0,
        tier="ELITE",
        daily_move_pct=9.5,
        peak_move_pct=12.0,
        explosion_score=100.0,
        velocity_3s=2.5,
        velocity_9s=1.8,
        volume_surge=2.0,
        volume=50000.0,
        premium=22.0,
        armed_base_launch=True,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _bearish_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime(2026, 9, 1, 14, 37, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=55.0,
        spot=23975.0,
        atmStrike=24000.0,
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=-0.12,
            trendStrength=40.0,
            spot=23975.0,
        ),
    )


@patch("app.engines.ict_breakout_monitor.get_settings", return_value=Settings())
def test_armed_launch_readiness_without_flat_then_vertical(_mock_settings):
    """ELITE armed_base_launch at ~9.5% lb must not die on structure_not_confirmed."""
    snap = _bearish_snap()
    alert = _sep01_put_23950_alert(
        ictFlatThenVertical=False,
        ictBreakout=False,
    )
    event = _explosion_event()
    ict = ICTBreakoutSignal(
        active=False,
        pattern="armed_base_launch",
        score=100.0,
        reasons=[],
        armed_base_launch=True,
        first_lift=True,
        flat_then_vertical=False,
        base_relative_move_pct=9.5,
        volume_awakening=True,
        volume_surge=2.0,
        flat_vertical_quality=70.0,
        armed_base_samples=10,
        armed_base_span_seconds=30.0,
    )
    ok, reason = first_lift_entry_readiness(
        snap=snap,
        event=event,
        ict=ict,
        alert=alert,
    )
    assert ok is True
    assert reason != "first_lift_structure_not_confirmed"


@patch("app.engines.pad_lane_capture.get_settings", return_value=Settings())
def test_armed_launch_pad_signal_without_flat_then_vertical(_mock_settings):
    alert = _sep01_put_23950_alert(
        ictFlatThenVertical=False,
        ictBreakout=False,
    )
    assert _armed_base_launch_pad_chart_signal(alert, _explosion_event()) is True


@patch("app.engines.pad_lane_capture.get_settings", return_value=Settings())
@patch("app.engines.ict_breakout_monitor.get_settings", return_value=Settings())
def test_strict_pad_resolves_for_exec_premium_retest(_mock_ict, _mock_pad):
    alert = _sep01_put_23950_alert(
        ictFlatThenVertical=False,
        ictBreakout=False,
    )
    event = _explosion_event()
    snap = _bearish_snap()

    _, strict = resolve_strict_pad_lane_for_entry(
        Side.PUT,
        snap,
        mode="explosion",
        explosion_event=event,
        alert=alert,
    )
    assert strict is True

    blocked, reason = premium_fading_blocks_entry(
        premium_momentum_3s=-0.8,
        premium_momentum_5s=-0.6,
        explosion_event=event,
        confirmed_ftv_bypass=True,
        pad_lane_bypass=strict,
    )
    assert blocked is False
    assert reason == "pad_lane_shallow_fade_ok"


@patch("app.engines.spot_direction.get_settings", return_value=Settings())
@patch("app.engines.winner_entry_guards.get_settings", return_value=Settings())
@patch("app.engines.pad_lane_capture.get_settings", return_value=Settings())
@patch("app.engines.ict_breakout_monitor.get_settings", return_value=Settings())
def test_premium_blocks_entry_allows_pad_retest(_mock_ict, _mock_pad, _mock_guard, _mock_spot):
    alert = _sep01_put_23950_alert(
        ictFlatThenVertical=False,
        ictBreakout=False,
    )
    event = _explosion_event()
    _, strict = resolve_strict_pad_lane_for_entry(
        Side.PUT,
        _bearish_snap(),
        mode="explosion",
        explosion_event=event,
        alert=alert,
    )
    premium = PremiumChart(
        direction="BEARISH",
        momentum3Pct=-0.8,
        momentum5Pct=-0.6,
        lastPremium=22.0,
    )
    blocked, reason = premium_blocks_entry(
        Side.PUT,
        premium,
        explosion_event=event,
        confirmed_ftv_bypass=True,
        pad_lane_bypass=strict,
    )
    assert blocked is False
    assert reason == "pad_lane_shallow_fade_ok"
