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


def _aug27_elite_first_lift_prelaunch_alert():
    """10:45 IST live shape — ELITE first_lift at 20% lb, blocked strict_rank_one_only."""
    return {
        "symbol": "SENSEX",
        "side": "PUT",
        "strike": 77300.0,
        "premium": 85.25,
        "tier": "ELITE",
        "explosionScore": 100.0,
        "dailyMovePct": 20.0,
        "peakMovePct": 26.0,
        "localBaseMovePct": 20.0,
        "ictBaseRelativeMovePct": 20.0,
        "tradeable": True,
        "ictBaseArmed": True,
        "ictArmedBaseSamples": 6,
        "ictArmedBaseSpanSeconds": 15.0,
        "ictArmedBaseRangePct": 0.0,
        "ictArmedBaseLaunch": False,
        "ictFirstLift": True,
        "ictFlatThenVertical": True,
        "ictVolumeAwakening": True,
        "volumeAwaken": True,
        "earlyRadarPadCapture": True,
        "velocity3s": 0.35,
        "velocity9s": 0.2,
    }


@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.premium_filter.get_settings")
@patch("app.engines.early_radar_pad_capture.get_settings")
def test_prelaunch_pad_passes_expiry_strict_rank_one_declining_halt(
    mock_pad_settings,
    mock_premium_settings,
    mock_expiry_settings,
):
    """Aug27 10:45 — expiry_worst_day_strict_rank_one_only after pad stamp."""
    from types import SimpleNamespace

    from app.engines.expiry_day_guards import (
        alert_is_early_pad_prelaunch_strict_launch,
        alert_is_strict_rank_one_launch,
        check_expiry_candidate,
    )
    from app.models.schemas import AutoTraderState

    cfg = Settings(explosion_shallow_otm_history_steps=1)
    mock_pad_settings.return_value = cfg
    mock_premium_settings.return_value = cfg
    mock_expiry_settings.return_value = cfg

    snap = _sensex_snap()
    snap.tradeQualityScore = 50.0
    snap.optionExpiry = "2026-08-27"
    alert = _aug27_elite_first_lift_prelaunch_alert()
    assert alert_is_early_pad_prelaunch_strict_launch(alert, snap) is True
    assert alert_is_strict_rank_one_launch(alert, snap) is True

    event = SimpleNamespace(
        daily_move_pct=20.0,
        peak_move_pct=26.0,
        explosion_score=100.0,
        tier="ELITE",
        side=Side.PUT,
    )
    candidate = SimpleNamespace(
        symbol="SENSEX",
        side=Side.PUT,
        strike=77300.0,
        score=120.0,
        mode="explosion",
        snap=snap,
        tier="ELITE",
        confidence=100.0,
        premium=85.25,
        explosion_event=event,
        alert=alert,
    )
    with patch(
        "app.engines.expiry_day_guards.predict_worst_expiry_day",
        return_value=(True, 65.0, ["chop_regime", "declining_session"]),
    ):
        with patch("app.engines.expiry_day_guards._session_declining", return_value=True):
            with patch(
                "app.engines.expiry_day_guards.check_expiry_explosion_open_block",
                return_value=(False, "ok"),
            ):
                with patch(
                    "app.engines.aligned_explosion_bypass.expiry_aligned_explosion_trade_allowed",
                    return_value=(True, "ok"),
                ):
                    ok, reason, meta = check_expiry_candidate(
                        candidate, AutoTraderState(), {"SENSEX": snap},
                    )
    assert ok is True, reason
    assert meta.get("expiryStrictRankOneLaunch") is True
