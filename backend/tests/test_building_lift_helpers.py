"""Aug19 BUILDING sudden-lift helpers — monitor what actually helps the rip."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.building_lift_helpers import (
    evaluate_building_lift_helpers,
    stamp_building_lift_helpers,
)
from app.engines.building_ltp_monitor import (
    evaluate_all_building_ltp,
    peek_building_helper_flip,
    reset_building_ltp_monitor_for_tests,
)
from app.models.schemas import (
    Breadth,
    MarketPhase,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap_put() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        tradeQualityScore=55.0,
        spot=76900.0,
        atmStrike=76900.0,
        breadth=Breadth(bias="BEARISH", score=70.0, aligned=True),
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=-0.16,
            momentum10Pct=-0.12,
            momentum15Pct=-0.05,
        ),
        explosionAlerts=[],
    )


def _aug19_alert(**overrides):
    """Best-of-day shape from radar archive: vol awaken + velocity + FTV + ICT."""
    alert = {
        "tier": "BUILDING",
        "side": "PUT",
        "strike": 76900.0,
        "premium": 131.0,
        "velocity3s": 3.57,
        "velocity9s": 5.12,
        "volumeSurge": 2.5,
        "volume": 91_872_980.0,
        "explosionScore": 55.0,
        "reason": "+3.6%/3s peakV3=12.5% +5.1%/9s vol×2.5 open+93% volAwaken×91872k",
        "volumeAwaken": True,
        "ictVolumeAwakening": True,
        "ictDisplacement": True,
        "ictFlatThenVertical": True,
        "flatVerticalQuality": 89.3,
        "ictBaseRelativeMovePct": 6.0,
        "ictLocalSwingBase": True,
        "cvdBuying": True,
        "bullishLocalBasePrediction": {
            "active": True,
            "side": "PUT",
            "direction": "BEARISH",
            "confidence": 100.0,
            "ictConfirms": [
                "judas_sell_side_reclaim",
                "index_option_displacement",
                "pm_kill_zone",
            ],
            "reasons": [
                "local_base",
                "bearish_momentum_turn",
                "premium_accelerating",
                "volume_expanding",
                "judas_sell_side_reclaim",
                "index_option_displacement",
                "pm_kill_zone",
            ],
        },
    }
    alert.update(overrides)
    return alert


def test_aug19_helpers_detect_what_helped_the_move():
    snap = _snap_put()
    board = evaluate_building_lift_helpers(
        snap=snap,
        alert=_aug19_alert(),
        prev_ltp=125.0,
        live_ltp=131.0,
    )
    assert board.helping is True
    assert board.sudden_lift is True
    assert board.helper_count >= 3
    assert "vol_awaken" in board.helpers
    assert "velocity_spike" in board.helpers
    assert "displacement" in board.helpers
    assert "chart_align" in board.helpers or "breadth_align" in board.helpers
    assert "flat_vertical" in board.helpers
    assert "judas_reclaim" in board.helpers or "pm_kill_zone" in board.helpers
    assert board.score_bonus > 0


def test_cold_building_without_helpers_not_helping():
    snap = _snap_put()
    board = evaluate_building_lift_helpers(
        snap=snap,
        alert=_aug19_alert(
            velocity3s=-0.3,
            velocity9s=-0.2,
            volumeSurge=1.0,
            volume=1000,
            volumeAwaken=False,
            ictVolumeAwakening=False,
            ictDisplacement=False,
            ictFlatThenVertical=False,
            flatVerticalQuality=20.0,
            cvdBuying=False,
            reason="cold",
            bullishLocalBasePrediction={},
        ),
        prev_ltp=125.0,
        live_ltp=125.1,
    )
    assert board.helping is False
    assert "velocity_spike" not in board.helpers


def test_stamp_helpers_marks_alert_for_ftv():
    snap = _snap_put()
    alert = _aug19_alert()
    board = evaluate_building_lift_helpers(
        snap=snap, alert=alert, prev_ltp=125.0, live_ltp=131.0,
    )
    stamped = stamp_building_lift_helpers(alert, board)
    assert stamped["buildingLiftHelping"] is True
    assert stamped["buildingRipHelpersOk"] is True
    assert stamped["ictBuildingRipReady"] is True
    assert "vol_awaken" in stamped["buildingRipHelpers"]


@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.engines.building_ltp_monitor.get_settings")
@patch("app.engines.worst_day_itm_fade.worst_day_defensive_session_active", return_value=False)
@patch("app.engines.worst_day_guard.session_entry_policy", return_value=("NORMAL", {}))
@patch("app.engines.dual_mode_strategy.resolve_trading_session_mode", return_value=("NORMAL", {}))
def test_scoreboard_surfaces_helpers_and_boosts_helping(
    _mode, _policy, _worst, mock_ltp_settings, mock_ict_settings,
):
    reset_building_ltp_monitor_for_tests()
    settings = Settings()
    mock_ltp_settings.return_value = settings
    mock_ict_settings.return_value = settings
    snap = _snap_put()
    alert = _aug19_alert(premium=131.0)
    snap.explosionAlerts = [alert]
    scores = evaluate_all_building_ltp({"SENSEX": snap})
    assert scores
    top = scores[0]
    assert top.helping is True
    assert top.helper_count >= 3
    assert top.helpers
    assert top.score >= 50.0


@patch("app.engines.building_ltp_monitor.get_settings")
@patch("app.engines.building_lift_helpers.get_settings")
def test_helper_flip_triggers_cycle(mock_hlp, mock_ltp):
    reset_building_ltp_monitor_for_tests()
    settings = Settings()
    mock_ltp.return_value = settings
    mock_hlp.return_value = settings
    snap = _snap_put()
    snap.explosionAlerts = [_aug19_alert(premium=131.0)]
    # Seed empty helper fingerprint so flip is detected.
    flipped, keys = peek_building_helper_flip({"SENSEX": snap})
    assert flipped is True
    assert any("76900" in k for k in keys)
