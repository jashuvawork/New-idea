"""Top FTV/V bypass on NIFTY/SENSEX expiry worst days."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.expiry_day_guards import check_expiry_entry_allowed
from app.engines.ict_breakout_monitor import first_lift_entry_readiness
from app.engines.top_ftv_v_expiry_bypass import (
    alert_is_top_ftv_or_v,
    alert_top_moment_type,
    snapshots_have_top_ftv_or_v,
    top_ftv_v_expiry_worst_waive,
)
from app.engines.worst_day_guard import session_entry_policy, worst_day_allows_candidate
from app.models.schemas import AutoTraderState, MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.top_ftv_v_expiry_bypass_enabled = True
    s.top_ftv_v_expiry_bypass_symbols_csv = "NIFTY,SENSEX"
    s.top_ftv_v_expiry_bypass_min_explosion_score = 12.0
    s.top_ftv_v_expiry_bypass_min_rank = 0.0
    s.top_ftv_v_expiry_bypass_min_base_move_pct = 5.0
    s.top_ftv_v_expiry_bypass_max_base_move_pct = 55.0
    s.top_ftv_v_expiry_chart_bypass_enabled = True
    s.expiry_worst_day_top_ftv_v_bypass_enabled = True
    s.expiry_worst_day_top_ftv_v_bypasses_trade_cap = True
    s.expiry_day_guards_enabled = True
    s.expiry_worst_day_halt_entries = True
    s.expiry_worst_day_elite_top_bypass_enabled = True
    s.expiry_worst_day_grade_a_ftv_bypass_enabled = False
    s.grade_a_ftv_first_lift_enabled = False
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
    s.worst_day_pause_enabled = True
    s.worst_day_breakout_only_enabled = True
    s.worst_day_intraday_trend_override_enabled = False
    s.worst_day_full_pause_loss_inr = -50000.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _snap(*, symbol: str = "SENSEX") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
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


def _aug27_v_rip_alert() -> dict:
    return {
        "symbol": "SENSEX",
        "side": "PUT",
        "strike": 77400.0,
        "premium": 116.6,
        "tier": "EXPLODING",
        "tradeable": True,
        "explosionScore": 29.0,
        "ictFlatThenVertical": True,
        "ictFirstLift": True,
        "ictVRipReady": True,
        "ictBreakout": True,
        "ictBaseRelativeMovePct": 23.5,
        "localBaseMovePct": 23.5,
        "dailyMovePct": 23.52,
        "peakMovePct": 25.69,
        "volumeAwaken": True,
        "velocity3s": 0.0,
    }


@patch("app.engines.top_ftv_v_expiry_bypass.get_settings")
def test_alert_classifies_as_exploding_top_moment(mock_settings):
    mock_settings.return_value = _settings()
    assert alert_top_moment_type(_aug27_put_77300_alert()) == "EXPLODING"


@patch("app.engines.top_ftv_v_expiry_bypass.get_settings")
def test_alert_is_top_ftv_or_v_aug27_put(mock_settings):
    mock_settings.return_value = _settings()
    assert alert_is_top_ftv_or_v(_aug27_put_77300_alert(), _snap()) is True


@patch("app.engines.top_ftv_v_expiry_bypass.get_settings")
def test_v_rip_classifies_as_v_moment(mock_settings):
    mock_settings.return_value = _settings()
    assert alert_top_moment_type(_aug27_v_rip_alert()) == "V"
    assert alert_is_top_ftv_or_v(_aug27_v_rip_alert(), _snap()) is True


@patch("app.engines.top_ftv_v_expiry_bypass.get_settings")
def test_top_ftv_v_waives_expiry_worst_defensive_rip(mock_settings):
    mock_settings.return_value = _settings()
    evidence = {
        "symbol": "SENSEX",
        "tier": "EXPLODING",
        "flatThenVertical": True,
        "firstLift": True,
        "activeBreakout": True,
        "explosionScore": 33.1,
        "velocity3s": 0.0,
    }
    assert top_ftv_v_expiry_worst_waive(evidence) is True


@patch("app.engines.expiry_day_guards.expiry_trades_cap_reached", return_value=(False, ""))
@patch("app.engines.expiry_day_guards.in_expiry_morning_window", return_value=True)
@patch("app.engines.expiry_day_guards.in_expiry_evening_block", return_value=False)
@patch("app.engines.expiry_day_guards.get_settings")
@patch("app.engines.expiry_day_guards.is_expiry_session", return_value=True)
@patch("app.engines.expiry_day_guards.predict_worst_expiry_day")
@patch("app.engines.expiry_day_guards._session_declining", return_value=True)
def test_expiry_declining_halt_lifts_for_top_ftv_v(
    mock_declining, mock_worst, mock_expiry, mock_settings, _evening, _morning, _cap,
):
    mock_settings.return_value = _settings()
    mock_worst.return_value = (True, 70.0, ["chop_regime"])
    snap = _snap()
    snap.explosionAlerts = [_aug27_put_77300_alert()]
    ok, reason, meta = check_expiry_entry_allowed(AutoTraderState(), {"SENSEX": snap})
    assert ok is True, reason
    assert meta.get("expiryWorstDayTopFtvVBypass") is True


@patch("app.engines.top_ftv_v_expiry_bypass.get_settings")
@patch("app.engines.grade_a_ftv_capture.get_settings")
@patch("app.engines.ict_breakout_monitor.get_settings")
@patch("app.engines.ict_breakout_monitor._expiry_worst_session", return_value=True)
def test_first_lift_readiness_passes_top_ftv_v_at_pad(
    mock_worst, mock_settings, mock_grade_a_settings, mock_top_settings,
):
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_grade_a_settings.return_value = cfg
    mock_top_settings.return_value = cfg
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


@patch("app.engines.expiry_day_guards.is_expiry_session", return_value=True)
@patch("app.engines.top_ftv_v_expiry_bypass.get_settings")
@patch("app.engines.worst_day_guard.get_settings")
@patch("app.engines.worst_day_guard.identify_worst_day")
def test_session_policy_lifts_to_normal_when_top_ftv_v_on_radar(
    mock_worst, mock_settings, mock_top_settings, _expiry,
):
    cfg = _settings()
    mock_settings.return_value = cfg
    mock_top_settings.return_value = cfg
    mock_worst.return_value = MagicMock(is_worst=True, to_dict=lambda: {"reasons": ["chop"]})
    snap = _snap()
    snap.explosionAlerts = [_aug27_put_77300_alert()]
    policy, meta = session_entry_policy(AutoTraderState(), {"SENSEX": snap})
    assert policy == "NORMAL"
    assert meta.get("worstDayLiftedByTopFtvV") is True


@patch("app.engines.worst_day_guard.get_settings")
@patch("app.engines.worst_day_guard.session_entry_policy")
def test_worst_day_allows_top_ftv_v_candidate_at_score_33(mock_policy, mock_settings):
    mock_settings.return_value = _settings()
    mock_settings.return_value.worst_day_breakout_min_rank = 65.0
    mock_policy.return_value = ("BREAKOUT_ONLY", {})
    snap = _snap()
    alert = _aug27_put_77300_alert()
    cand = SimpleNamespace(
        symbol="SENSEX",
        snap=snap,
        mode="explosion",
        tier="EXPLODING",
        score=33.1,
        side=Side.PUT,
        strike=77300.0,
        premium=80.25,
        alert=alert,
        explosion_event=None,
    )
    ok, reason, meta = worst_day_allows_candidate(
        cand,
        AutoTraderState(),
        {snap.symbol: snap},
        policy="BREAKOUT_ONLY",
    )
    assert ok is True, reason
    assert meta.get("worstDayBypass") == "top_ftv_v_expiry"


@patch("app.engines.top_ftv_v_expiry_bypass.get_settings")
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
    assert alert_is_top_ftv_or_v(alert, snap) is True
    assert snapshots_have_top_ftv_or_v({"NIFTY": snap}) is False
    snap.explosionAlerts = [alert]
    assert snapshots_have_top_ftv_or_v({"NIFTY": snap}) is True


@patch("app.engines.top_ftv_v_expiry_bypass.get_settings")
def test_rejects_score_below_floor(mock_settings):
    mock_settings.return_value = _settings()
    alert = _aug27_put_77300_alert()
    alert["explosionScore"] = 8.0
    assert alert_is_top_ftv_or_v(alert, _snap()) is False
