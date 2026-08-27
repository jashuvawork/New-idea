"""Aug27 SENSEX PUT 77300 — bullish local-base prediction at score 33, v3=0."""

from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.bullish_local_base import (
    alert_bullish_local_base_active,
    alert_bullish_local_base_prediction,
    local_base_reversal_prediction,
)
from app.engines.ict_breakout_monitor import _fast_bullish_local_base_readiness
from app.models.schemas import Breadth, MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.bullish_local_base_prediction_enabled = True
    s.local_base_reversal_prediction_enabled = True
    s.bullish_local_base_prediction_min_score = 62.0
    s.bullish_local_base_pad_min_explosion_score = 12.0
    s.bullish_local_base_pad_max_move_pct = 45.0
    s.bullish_local_base_pad_min_confidence = 55.0
    s.bullish_local_base_prediction_min_vol_surge = 2.0
    s.bullish_local_base_prediction_min_velocity_3s = 1.5
    s.bullish_local_base_prediction_min_velocity_9s = 0.2
    s.bullish_local_base_prediction_min_move_pct = 8.0
    s.bullish_local_base_prediction_max_move_pct = 40.0
    s.bullish_local_base_prediction_min_confidence = 70.0
    s.fast_bullish_local_base_soft_min_score = 45.0
    s.fast_bullish_local_base_soft_min_confidence = 60.0
    s.local_base_pad_capture_min_premium_inr = 18.0
    s.fast_bullish_local_base_max_premium_inr = 220.0
    s.fast_bullish_local_base_capture_enabled = True
    s.fast_bullish_local_base_min_move_pct = 1.0
    s.fast_bullish_local_base_max_move_pct = 45.0
    s.fast_bullish_local_base_min_velocity_3s = 0.8
    s.local_base_turn_bypass_enabled = True
    s.local_base_turn_min_score = 62.0
    s.local_base_turn_pad_min_score = 28.0
    s.local_base_turn_min_vol_surge = 2.0
    s.local_base_turn_min_mom_shift_pct = 0.05
    s.local_base_reversal_require_ict_confirm = False
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp="2026-08-27T09:58:00+05:30",
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=77350.0,
        atmStrike=77300.0,
        tradeQualityScore=55,
        breadth=Breadth(bias="BEARISH", score=40, aligned=True),
        spotChart=SpotChart(
            direction="BEARISH",
            momentum5Pct=-0.15,
            momentum10Pct=-0.10,
            momentum15Pct=-0.05,
            trendStrength=60.0,
            emaBias="BEARISH",
            candleBias="BEARISH",
            recommendedSide="PUT",
        ),
    )


def _aug27_alert() -> dict:
    return {
        "symbol": "SENSEX",
        "side": "PUT",
        "strike": 77300.0,
        "premium": 80.25,
        "tier": "EXPLODING",
        "tradeable": True,
        "explosionScore": 33.1,
        "flatVerticalGrade": "A",
        "flatVerticalQuality": 72.1,
        "ictFlatThenVertical": True,
        "ictFirstLift": True,
        "ictBaseArmed": True,
        "ictBaseRelativeMovePct": 33.9,
        "localBaseMovePct": 33.9,
        "dailyMovePct": 33.86,
        "peakMovePct": 38.2,
        "volumeAwaken": True,
        "ictVolumeAwakening": True,
        "volumeSurge": 2.0,
        "velocity3s": 0.0,
        "velocity9s": 0.0,
        "indexMomAlign": True,
        "indexHelpersConfirm": True,
        "ictBreakout": True,
    }


def _event():
    from types import SimpleNamespace

    return SimpleNamespace(
        side=Side.PUT,
        tier="EXPLODING",
        explosion_score=33.1,
        premium=80.25,
        velocity_3s=0.0,
        velocity_9s=0.0,
        volume_surge=2.0,
        daily_move_pct=33.86,
        peak_move_pct=38.2,
    )


def _ict():
    from types import SimpleNamespace

    return SimpleNamespace(
        base_relative_move_pct=33.9,
        flat_then_vertical=True,
        local_swing_base=False,
        volume_awakening=True,
        premium_fvg=False,
        displacement=False,
        active=True,
    )


@patch("app.engines.bullish_local_base.get_settings")
def test_bullish_prediction_active_aug27_put_at_pad(mock_settings):
    mock_settings.return_value = _settings()
    pred = local_base_reversal_prediction(_snap(), _event(), _ict(), alert=_aug27_alert())
    assert pred["active"] is True, pred
    assert pred["side"] == "PUT"
    assert pred["direction"] == "BEARISH"


@patch("app.engines.bullish_local_base.get_settings")
def test_alert_wrapper_active_aug27_put(mock_settings):
    mock_settings.return_value = _settings()
    assert alert_bullish_local_base_active(_aug27_alert(), _snap()) is True


@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.engines.bullish_local_base.get_settings")
def test_fast_bullish_readiness_aug27_put_at_34pct_pad(mock_bull, mock_ict):
    cfg = _settings()
    mock_bull.return_value = cfg
    mock_ict.return_value = cfg
    ok, reason = _fast_bullish_local_base_readiness(
        snap=_snap(),
        event=_event(),
        ict=_ict(),
        alert=_aug27_alert(),
        settings=cfg,
    )
    assert ok is True, reason
    assert reason == "fast_bullish_local_base_ready"
