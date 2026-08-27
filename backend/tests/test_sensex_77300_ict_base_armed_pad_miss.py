"""Aug27 SENSEX PUT 77300 — ict_base_armed EXPLODING at pad blocked before launch stamp."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.early_radar_pad_capture import (
    early_radar_pad_capture_active,
    early_radar_pad_entry_readiness,
    stamp_early_radar_pad_capture,
)
from app.engines.ict_breakout_monitor import first_lift_entry_readiness
from app.models.schemas import MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _sensex_snap() -> SymbolSnapshot:
    return SymbolSnapshot(
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


def _aug27_prelaunch_alert(*, score: float = 31.6, local_move: float = 10.6):
    return {
        "symbol": "SENSEX",
        "side": "PUT",
        "strike": 77300.0,
        "premium": 67.65,
        "tier": "EXPLODING",
        "explosionScore": score,
        "dailyMovePct": 8.91,
        "peakMovePct": 10.6,
        "localBaseMovePct": local_move,
        "ictBaseRelativeMovePct": local_move,
        "ictBaseArmed": True,
        "ictArmedBaseSamples": 8,
        "ictArmedBaseLaunch": False,
        "ictFirstLift": False,
        "ictVRipReady": False,
        "momentType": "ict_base_armed",
        "velocity3s": 1.2,
        "velocity9s": 0.8,
        "volumeAwaken": True,
    }


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_exploding_prelaunch_pad_active_at_local_base(mock_settings):
    mock_settings.return_value = Settings()
    snap = _sensex_snap()
    alert = _aug27_prelaunch_alert()
    assert early_radar_pad_capture_active(alert, snap) is True
    stamped = dict(alert)
    assert stamp_early_radar_pad_capture(stamped, snap) is True
    assert stamped["earlyRadarPadCapture"] is True


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_prelaunch_pad_readiness_waives_first_lift_score_near_miss(mock_settings):
    mock_settings.return_value = Settings()
    snap = _sensex_snap()
    alert = _aug27_prelaunch_alert()
    ok, reason = early_radar_pad_entry_readiness(snap=snap, alert=alert)
    assert ok is True, reason
    assert alert.get("earlyRadarPadCapture") is True

    ready, readiness_reason = first_lift_entry_readiness(snap=snap, alert=alert)
    assert ready is True, readiness_reason


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_prelaunch_pad_still_blocks_extended_chase(mock_settings):
    mock_settings.return_value = Settings()
    snap = _sensex_snap()
    alert = _aug27_prelaunch_alert(local_move=28.0, score=33.0)
    assert early_radar_pad_capture_active(alert, snap) is False


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_prelaunch_pad_still_blocks_low_score_building(mock_settings):
    mock_settings.return_value = Settings()
    snap = _sensex_snap()
    alert = _aug27_prelaunch_alert(score=18.0, local_move=6.0)
    alert["tier"] = "BUILDING"
    assert early_radar_pad_capture_active(alert, snap) is False


@patch("app.engines.early_radar_pad_capture.get_settings")
def test_shallow_otm_one_step_put_passes_pad_moneyness(mock_settings):
    mock_settings.return_value = Settings(explosion_shallow_otm_history_steps=1)
    from app.engines.early_radar_pad_capture import early_radar_pad_shallow_otm_ok

    snap = _sensex_snap()
    alert = _aug27_prelaunch_alert()
    assert early_radar_pad_shallow_otm_ok(alert, snap) is True
    assert early_radar_pad_capture_active(alert, snap) is True
