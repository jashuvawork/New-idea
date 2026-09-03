"""Sep03 NIFTY PUT 23900 — session-trough pad vs stale armed-base coil chase."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.early_radar_pad_capture import (
    SESSION_TROUGH_PAD_READY,
    armed_base_stale_vs_session_trough,
    building_coil_pad_lift_signal,
    session_trough_pad_entry_readiness,
    session_trough_pad_lift_signal,
)
from app.engines.ict_breakout_monitor import first_lift_entry_readiness
from app.models.schemas import MarketPhase, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _nifty_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime(2026, 9, 3, 12, 1, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=55.0,
        spot=23900.0,
        atmStrike=23900.0,
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=-0.04,
            momentum10Pct=-0.02,
            momentum15Pct=0.01,
        ),
    )


def _sep03_stale_armed_chase_alert(*, premium: float = 79.65, off_low: float = 59.3):
    """Live shape at 12:01 — armed base ₹70.4, trough ~₹50, 11% off stale base."""
    return {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 23900.0,
        "premium": premium,
        "tier": "BUILDING",
        "explosionScore": 45.0,
        "localBaseMovePct": 11.0,
        "ictBaseRelativeMovePct": 11.0,
        "localBaseBasePremium": 70.4,
        "ictBasePremium": 70.4,
        "sessionLow": 50.0,
        "offLowMovePct": off_low,
        "ictBaseArmed": True,
        "ictArmedBaseSamples": 8,
        "ictArmedBaseLaunch": True,
        "armedBaseCapture": True,
        "volumeAwaken": True,
        "velocity3s": 0.6,
        "velocity9s": 0.3,
    }


def _sep03_trough_pad_alert(*, premium: float = 55.0, off_low: float = 10.0):
    """Near session trough while armed base still stale above V-low."""
    return {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 23900.0,
        "premium": premium,
        "tier": "BUILDING",
        "explosionScore": 28.0,
        "localBaseMovePct": 6.5,
        "ictBaseRelativeMovePct": 6.5,
        "localBaseBasePremium": 70.4,
        "ictBasePremium": 70.4,
        "sessionLow": 50.0,
        "offLowMovePct": off_low,
        "ictBaseArmed": True,
        "ictArmedBaseSamples": 8,
        "ictArmedBaseLaunch": False,
        "volumeAwaken": True,
        "velocity3s": 0.0,
        "velocity9s": 0.0,
    }


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_armed_base_stale_vs_session_trough_sep03(mock_settings):
    mock_settings.return_value = Settings()
    alert = _sep03_stale_armed_chase_alert()
    assert armed_base_stale_vs_session_trough(alert) is True


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_building_coil_pad_blocks_stale_armed_chase(mock_settings):
    mock_settings.return_value = Settings()
    alert = _sep03_stale_armed_chase_alert()
    assert building_coil_pad_lift_signal(alert) is False


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_session_trough_pad_active_near_v_low(mock_settings):
    mock_settings.return_value = Settings()
    alert = _sep03_trough_pad_alert()
    assert session_trough_pad_lift_signal(alert) is True


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_session_trough_pad_readiness_at_local_base(mock_settings):
    mock_settings.return_value = Settings()
    snap = _nifty_snap()
    alert = _sep03_trough_pad_alert()
    ok, reason = session_trough_pad_entry_readiness(snap=snap, alert=alert)
    assert ok is True, reason
    assert alert.get("sessionTroughPad") is True
    assert reason == SESSION_TROUGH_PAD_READY


@patch("app.engines.early_radar_pad_capture.get_settings")
@patch("app.engines.ict_breakout_monitor.get_settings")
def test_first_lift_prefers_trough_over_stale_coil_chase(
    mock_ict_settings,
    mock_pad_settings,
):
    mock_pad_settings.return_value = Settings()
    mock_ict_settings.return_value = Settings()
    snap = _nifty_snap()

    chase = _sep03_stale_armed_chase_alert()
    ready, reason = first_lift_entry_readiness(snap=snap, alert=chase)
    assert ready is False or "building_coil_pad" not in str(reason)

    trough = _sep03_trough_pad_alert()
    ready, reason = first_lift_entry_readiness(snap=snap, alert=trough)
    assert ready is True, reason
    assert reason == SESSION_TROUGH_PAD_READY


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_session_trough_pad_blocks_extended_off_low(mock_settings):
    mock_settings.return_value = Settings()
    alert = _sep03_trough_pad_alert(premium=79.65, off_low=59.3)
    assert session_trough_pad_lift_signal(alert) is False
