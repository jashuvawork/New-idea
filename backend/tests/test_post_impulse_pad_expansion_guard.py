"""Post-impulse consolidation + pad expansion confirm — Sep2 gap-day guard."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.engines.early_radar_pad_capture import (
    EARLY_RADAR_PAD_UNCONFIRMED,
    POST_IMPULSE_CONSOLIDATION_BLOCKED,
    early_radar_pad_entry_readiness,
    early_radar_pad_expansion_confirmed,
    post_impulse_consolidation_active,
    stamp_early_radar_pad_capture,
)
from app.engines.explosion_entry_guards import post_impulse_consolidation_entry_blocked
from app.engines.explosion_detector import ExplosionEvent
from app.models.schemas import MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = Settings()
    for key, value in overrides.items():
        setattr(s, key, value)
    return s


def _sep2_nifty_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime(2026, 9, 2, 9, 30, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=62.0,
        spot=23845.0,
        atmStrike=23850.0,
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=0.01,
            momentum10Pct=0.02,
            momentum15Pct=-0.28,
        ),
    )


def _sep2_nifty_alert():
    return {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 23900.0,
        "premium": 118.0,
        "tier": "EXPLODING",
        "explosionScore": 97.8,
        "dailyMovePct": 7.2,
        "peakMovePct": 7.2,
        "localBaseMovePct": 7.2,
        "ictBaseRelativeMovePct": 7.2,
        "offLowMovePct": 7.2,
        "ictBaseArmed": True,
        "ictArmedBaseSamples": 8,
        "ictArmedBaseLaunch": False,
        "ictFirstLift": False,
        "velocity3s": 0.08,
        "velocity9s": 0.04,
        "volumeAwaken": True,
    }


@patch("app.engines.early_radar_pad_capture.get_settings")
@patch("app.engines.session_timing.in_open_caution_window", return_value=True)
def test_sep2_armed_exploding_blocked_without_expansion(mock_caution, mock_settings):
    mock_settings.return_value = _settings()
    snap = _sep2_nifty_snap()
    alert = _sep2_nifty_alert()
    assert post_impulse_consolidation_active(snap, "PUT") is True
    assert early_radar_pad_expansion_confirmed(alert) is False
    ok, reason = early_radar_pad_entry_readiness(snap=snap, alert=alert)
    assert ok is False
    assert reason in (EARLY_RADAR_PAD_UNCONFIRMED, POST_IMPULSE_CONSOLIDATION_BLOCKED)
    assert alert.get("earlyRadarPadCapture") is True
    assert not alert.get("earlyRadarPadReady")


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_expansion_confirmed_with_armed_base_launch_stamp(mock_settings):
    mock_settings.return_value = _settings()
    alert = _sep2_nifty_alert()
    alert["ictArmedBaseLaunch"] = True
    assert early_radar_pad_expansion_confirmed(alert) is True


@patch("app.engines.early_radar_pad_capture.get_settings")
@patch("app.engines.session_timing.in_open_caution_window", return_value=True)
def test_sep2_passes_with_hot_velocity(mock_caution, mock_settings):
    mock_settings.return_value = _settings()
    snap = _sep2_nifty_snap()
    alert = _sep2_nifty_alert()
    alert["velocity3s"] = 1.1
    alert["velocity9s"] = 0.6
    ok, reason = early_radar_pad_entry_readiness(snap=snap, alert=alert)
    assert ok is True, reason


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.session_timing.in_open_caution_window", return_value=True)
def test_post_impulse_blocks_elite_base_ready_selector_gate(mock_caution, mock_settings):
    mock_settings.return_value = _settings()
    snap = _sep2_nifty_snap()
    alert = _sep2_nifty_alert()
    event = ExplosionEvent(
        symbol="NIFTY",
        side=Side.PUT,
        strike=23900.0,
        premium=118.0,
        velocity_3s=0.08,
        velocity_9s=0.04,
        velocity_15s=0.0,
        volume_surge=1.2,
        explosion_score=97.8,
        tier="EXPLODING",
        reason="test",
        daily_move_pct=7.2,
        peak_move_pct=7.2,
    )
    blocked, reason = post_impulse_consolidation_entry_blocked(
        event,
        alert=alert,
        snap=snap,
    )
    assert blocked is True
    assert reason == POST_IMPULSE_CONSOLIDATION_BLOCKED


@patch("app.engines.early_radar_pad_capture.get_settings")
@patch("app.engines.session_timing.in_open_caution_window", return_value=False)
def test_aug27_prelaunch_still_passes_after_open_window(mock_caution, mock_settings):
    """Aug27 SENSEX PUT 77300 @ 10:01 — armed prelaunch with live velocity."""
    mock_settings.return_value = _settings()
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime(2026, 8, 27, 10, 1, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=49.0,
        spot=77441.0,
        atmStrike=77400.0,
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=-0.04,
            momentum10Pct=-0.02,
            momentum15Pct=0.01,
        ),
    )
    alert = {
        "symbol": "SENSEX",
        "side": "PUT",
        "strike": 77300.0,
        "premium": 67.65,
        "tier": "EXPLODING",
        "explosionScore": 31.6,
        "localBaseMovePct": 10.6,
        "ictBaseRelativeMovePct": 10.6,
        "ictBaseArmed": True,
        "ictArmedBaseSamples": 8,
        "ictArmedBaseLaunch": False,
        "ictFirstLift": False,
        "velocity3s": 1.2,
        "velocity9s": 0.8,
        "volumeAwaken": True,
    }
    ok, reason = early_radar_pad_entry_readiness(snap=snap, alert=alert)
    assert ok is True, reason
    stamped = dict(alert)
    assert stamp_early_radar_pad_capture(stamped, snap) is True
    assert stamped.get("earlyRadarPadReady") is True
