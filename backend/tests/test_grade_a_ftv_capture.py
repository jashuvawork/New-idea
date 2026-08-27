"""Grade-A FTV first-lift bypass on NIFTY/SENSEX expiry worst days."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.expiry_day_guards import check_expiry_entry_allowed
from app.engines.grade_a_ftv_capture import (
    alert_is_grade_a_ftv_first_lift,
    grade_a_ftv_expiry_worst_waive,
    snapshots_have_grade_a_ftv_first_lift,
)
from app.engines.ict_breakout_monitor import first_lift_entry_readiness
from app.models.schemas import AutoTraderState, MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.grade_a_ftv_first_lift_enabled = True
    s.grade_a_ftv_first_lift_symbols_csv = "NIFTY,SENSEX"
    s.grade_a_ftv_first_lift_min_explosion_score = 28.0
    s.grade_a_ftv_first_lift_min_quality = 65.0
    s.grade_a_ftv_first_lift_min_rank = 40.0
    s.grade_a_ftv_first_lift_min_base_move_pct = 8.0
    s.grade_a_ftv_first_lift_max_base_move_pct = 45.0
    s.expiry_worst_day_grade_a_ftv_bypass_enabled = True
    s.grade_a_ftv_chart_bypass_enabled = True
    s.expiry_day_guards_enabled = True
    s.expiry_worst_day_halt_entries = True
    s.expiry_worst_day_elite_top_bypass_enabled = True
    s.expiry_worst_day_elite_top_bypasses_trade_cap = True
    s.expiry_morning_only = False
    s.expiry_evening_all_in_explosion_bypass = False
    s.expiry_evening_block_hour = 15
    s.expiry_evening_block_minute = 0
    s.first_lift_trade_enabled = True
    s.first_lift_trade_min_score = 62.0
    s.first_lift_trade_min_quality = 65.0
    s.first_lift_trade_min_velocity_3s = 1.5
    s.first_lift_trade_min_velocity_9s = 1.0
    s.first_lift_trade_min_volume_surge = 2.0
    s.first_lift_trade_max_move_pct = 25.0
    s.ict_structured_early_min_move_pct = 15.0
    s.ict_defensive_base_rip_block_expiry_worst = True
    s.ict_defensive_base_rip_expiry_worst_min_tier = "ELITE"
    s.ict_defensive_base_rip_expiry_worst_min_quality = 85.0
    s.ict_defensive_base_rip_expiry_worst_min_score = 90.0
    s.ict_defensive_base_rip_expiry_worst_min_velocity_3s = 3.0
    s.first_lift_option_led_enabled = False
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=77350.0,
        atmStrike=77300.0,
        tradeQualityScore=55,
        spotChart=SpotChart(
            direction="BEARISH",
            timeframe="5m",
            barCount=40,
            momentum5Pct=-0.15,
            momentum15Pct=-0.10,
            trendStrength=60.0,
            emaBias="BEARISH",
            candleBias="BEARISH",
            recommendedSide="PUT",
        ),
    )


def _aug27_put_77300_alert() -> dict:
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
        "indexMomAlign": True,
        "indexHelpersConfirm": True,
        "ictBreakout": True,
    }


@patch("app.engines.grade_a_ftv_capture.get_settings")
def test_alert_is_grade_a_ftv_first_lift_aug27_put(mock_settings):
    mock_settings.return_value = _settings()
    assert alert_is_grade_a_ftv_first_lift(_aug27_put_77300_alert(), _snap()) is True


@patch("app.engines.grade_a_ftv_capture.get_settings")
def test_grade_a_ftv_waives_expiry_worst_defensive_rip(mock_settings):
    mock_settings.return_value = _settings()
    evidence = {
        "symbol": "SENSEX",
        "tier": "EXPLODING",
        "flatThenVertical": True,
        "firstLift": True,
        "flatVerticalGrade": "A",
        "flatVerticalQuality": 72.1,
        "explosionScore": 33.1,
        "velocity3s": 0.0,
    }
    assert grade_a_ftv_expiry_worst_waive(evidence) is True


@patch("app.engines.expiry_day_guards.expiry_trades_cap_reached", return_value=(False, ""))
@patch("app.engines.expiry_day_guards.in_expiry_morning_window", return_value=True)
@patch("app.engines.expiry_day_guards.in_expiry_evening_block", return_value=False)
@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.expiry_day_guards.is_expiry_session", return_value=True)
@patch("app.engines.expiry_day_guards.predict_worst_expiry_day")
@patch("app.engines.expiry_day_guards._session_declining", return_value=True)
def test_expiry_declining_halt_lifts_for_grade_a_ftv(
    mock_declining, mock_worst, mock_expiry, mock_settings, _evening, _morning, _cap,
):
    mock_settings.return_value = _settings()
    mock_worst.return_value = (True, 70.0, ["chop_regime"])
    snap = _snap()
    snap.explosionAlerts = [_aug27_put_77300_alert()]
    ok, reason, meta = check_expiry_entry_allowed(AutoTraderState(), {"SENSEX": snap})
    assert ok is True, reason
    assert meta.get("expiryWorstDayGradeAFtvBypass") is True


@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.engines.ict_breakout_monitor._expiry_worst_session", return_value=True)
def test_first_lift_readiness_passes_grade_a_ftv_at_pad(mock_worst, mock_settings):
    mock_settings.return_value = _settings()
    snap = _snap()
    alert = _aug27_put_77300_alert()
    ict = MagicMock()
    ict.active = True
    ict.flat_then_vertical = True
    ict.first_lift = True
    ict.base_relative_move_pct = 33.9
    ict.flat_vertical_quality = 72.1
    ict.volume_awakening = True
    ict.volume_surge = 2.0
    ict.armed_base_launch = False
    ict.elite_base_ready = False
    ict.v_rip_ready = False
    ok, reason = first_lift_entry_readiness(
        snap=snap, alert=alert, ict=ict, state=AutoTraderState(),
    )
    assert ok is True, reason


@patch("app.engines.grade_a_ftv_capture.get_settings")
def test_nifty_also_qualifies(mock_settings):
    mock_settings.return_value = _settings()
    alert = _aug27_put_77300_alert()
    alert["symbol"] = "NIFTY"
    alert["strike"] = 24150.0
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24150.0,
        atmStrike=24150.0,
        tradeQualityScore=50,
        spotChart=_snap().spotChart,
    )
    assert alert_is_grade_a_ftv_first_lift(alert, snap) is True
    assert snapshots_have_grade_a_ftv_first_lift({"NIFTY": snap}) is False
    snap.explosionAlerts = [alert]
    assert snapshots_have_grade_a_ftv_first_lift({"NIFTY": snap}) is True


def test_rank_entry_candidate_preserves_grade_a_ftv_sleeve():
    """Regression: flatVerticalGrade must reach ftv_authorization_policy via rank_entry_candidate."""
    from types import SimpleNamespace

    from app.engines.missed_trade_explainer import _candidate_from_alert
    from app.engines.trade_ranking import (
        ftv_authorization_policy,
        ftv_policy_settings,
        rank_entry_candidate,
    )
    from app.models.schemas import Breadth, MarketPhase, Side, SpotChart, SymbolSnapshot

    alert = _aug27_put_77300_alert()
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp=_snap().timestamp,
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=77350.0,
        atmStrike=77300.0,
        tradeQualityScore=55.0,
        breadth=Breadth(bias="BEARISH", score=40, aligned=True),
        spotChart=SpotChart(direction="BEARISH", spot=77350.0, recommendedSide="PUT"),
        explosionAlerts=[alert],
    )
    candidate = _candidate_from_alert("SENSEX", snap, alert)
    candidate.explosion_event = SimpleNamespace(
        symbol="SENSEX",
        side=Side.PUT,
        strike=77300.0,
        tier="ELITE",
        explosion_score=100.0,
        velocity_3s=4.2,
        velocity_9s=2.0,
        volume_surge=2.5,
        daily_move_pct=21.0,
        peak_move_pct=21.0,
    )

    from app.config import Settings

    ranking = rank_entry_candidate(candidate)
    evidence = ranking.get("evidence") or {}
    assert evidence.get("flatVerticalGrade") in ("A", "A+")
    decision = ftv_authorization_policy(
        evidence,
        ranking,
        snapshot_available=True,
        atm_itm_allowed=True,
        **ftv_policy_settings(Settings()),
    )
    assert decision.allowed is True
    assert decision.mode == "GRADE_A_FTV_FIRST_LIFT"
