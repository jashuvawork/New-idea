"""Sep22 NIFTY PUT 23350 — EXPIRY WORST morning flat→vertical structure miss fix."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.ict_breakout_monitor import ICTBreakoutSignal, first_lift_entry_readiness
from app.engines.top_ftv_v_expiry_bypass import expiry_worst_pe_structure_bypass_allowed
from app.models.schemas import MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _sep22_put_23350_alert(**overrides) -> dict:
    alert = {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 23350.0,
        "premium": 28.0,
        "tier": "ELITE",
        "explosionScore": 100.0,
        "ictFlatThenVertical": True,
        "ictBreakout": False,
        "ictFirstLift": False,
        "ictArmedBaseLaunch": False,
        "ictBaseArmed": True,
        "localBaseMovePct": 12.0,
        "ictBaseRelativeMovePct": 12.0,
        "offLowMovePct": 11.5,
        "flatVerticalQuality": 71.4,
        "flatVerticalGrade": "A",
        "volumeAwaken": True,
        "velocity3s": 2.0,
        "peakMovePct": 18.0,
    }
    alert.update(overrides)
    return alert


def _explosion_event(**overrides):
    base = SimpleNamespace(
        symbol="NIFTY",
        side=Side.PUT,
        strike=23350.0,
        tier="ELITE",
        daily_move_pct=12.0,
        peak_move_pct=18.0,
        explosion_score=100.0,
        velocity_3s=2.0,
        premium=28.0,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _bearish_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime(2026, 9, 22, 10, 41, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=55.0,
        spot=23364.0,
        atmStrike=23350.0,
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=-0.35,
            trendStrength=40.0,
            spot=23364.0,
        ),
    )


@patch("app.engines.top_ftv_v_expiry_bypass.get_settings", return_value=Settings())
def test_expiry_worst_pe_structure_bypass_flat_vertical_without_breakout(_mock):
    alert = _sep22_put_23350_alert()
    assert expiry_worst_pe_structure_bypass_allowed(
        tier="ELITE",
        score=100.0,
        base_move_pct=12.0,
        volume_awakening=True,
        side="PUT",
        day_mode="EXPIRY WORST",
        snap=_bearish_snap(),
        row=alert,
    ) is True


@patch("app.engines.top_ftv_v_expiry_bypass.get_settings", return_value=Settings())
def test_expiry_worst_pe_structure_bypass_rejects_extended_local(_mock):
    alert = _sep22_put_23350_alert(localBaseMovePct=28.0, ictBaseRelativeMovePct=28.0)
    assert expiry_worst_pe_structure_bypass_allowed(
        tier="ELITE",
        score=100.0,
        base_move_pct=28.0,
        volume_awakening=True,
        side="PUT",
        day_mode="EXPIRY WORST",
        snap=_bearish_snap(),
        row=alert,
    ) is False


@patch("app.engines.ict_breakout_monitor.get_settings", return_value=Settings())
@patch(
    "app.engines.session_timing.in_midday_chop_window",
    return_value=False,
)
def test_sep22_first_lift_readiness_accepts_elite_flat_vertical(_midday, _settings):
    """Sep22 10:41 ELITE flat→vertical at base must not die on structure_not_confirmed."""
    snap = _bearish_snap()
    alert = _sep22_put_23350_alert()
    event = _explosion_event()
    ict = ICTBreakoutSignal(
        active=False,
        pattern="flat_then_vertical",
        score=100.0,
        reasons=[],
        flat_then_vertical=True,
        first_lift=False,
        base_relative_move_pct=12.0,
        volume_awakening=True,
        flat_vertical_quality=71.4,
    )
    ok, reason = first_lift_entry_readiness(
        snap=snap,
        event=event,
        ict=ict,
        alert=alert,
        day_mode="EXPIRY WORST",
    )
    assert ok is True
    assert reason != "first_lift_structure_not_confirmed"

