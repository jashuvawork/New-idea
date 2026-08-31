"""EOD local-base replay — production gates on stored premium tape."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.eod_local_base_replay import (
    _ReplayDateTime,
    _chart_analysis_from_spot_history,
    _enrich_alert_from_contract,
    _install_replay_clock,
    _replay_selection_rank,
    _restore_replay_clock,
    evaluate_local_base_entry,
    evaluate_replay_live_gates,
    generate_eod_local_base_replay,
    replay_local_base_day,
    _spot_chart_from_history,
)
from app.models.schemas import Breadth, MarketPhase, Side, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _bullish_chart(spot: float = 77000.0) -> SpotChart:
    return SpotChart(
        direction="BULLISH",
        spot=spot,
        momentum5Pct=0.08,
        momentum10Pct=0.05,
        momentum15Pct=0.02,
    )


def _bearish_chart(spot: float = 77000.0) -> SpotChart:
    return SpotChart(
        direction="BEARISH",
        spot=spot,
        momentum5Pct=-0.08,
        momentum10Pct=-0.05,
        momentum15Pct=-0.02,
    )


def _snap(side: str = "CALL", chart: SpotChart | None = None) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=77000.0,
        atmStrike=77000.0,
        spotChart=chart or _bullish_chart(),
        tradeQualityScore=60.0,
    )


def test_enrich_alert_merges_tape_volume():
    alert = {"ictArmedBaseLaunch": True, "volume": 0}
    contract = {"volume": 71_736_060.0, "volumeSurge": 2.5, "velocity3s": 1.2}
    merged = _enrich_alert_from_contract(alert, contract)
    assert merged["volume"] == 71_736_060.0
    assert merged["volumeAwaken"] is True


def test_spot_chart_from_history_builds_momentum():
    t0 = datetime(2026, 8, 19, 10, 0, 0, tzinfo=IST)
    hist = [(t0 + timedelta(seconds=30 * i), 77000.0 + i * 8.0) for i in range(20)]
    chart = _spot_chart_from_history(hist, 77160.0)
    assert chart.momentum5Pct > 0


def test_spot_chart_from_history_builds_momentum():
    t0 = datetime(2026, 8, 19, 10, 0, 0, tzinfo=IST)
    hist = [(t0 + timedelta(seconds=30 * i), 77000.0 + i * 8.0) for i in range(20)]
    chart = _spot_chart_from_history(hist, 77160.0)
    assert chart.momentum5Pct > 0


def test_chart_analysis_from_spot_history_includes_gainzalgo_fields():
    t0 = datetime(2026, 8, 19, 10, 0, 0, tzinfo=IST)
    hist = [(t0 + timedelta(seconds=20 * i), 77000.0 + i * 5.0) for i in range(40)]
    analysis = _chart_analysis_from_spot_history(hist, 77200.0, symbol="NIFTY")
    assert analysis is not None
    assert isinstance(analysis.decisiveCandle, dict)
    assert "decisive" in analysis.decisiveCandle
    assert isinstance(analysis.squeeze, dict)
    assert "on" in analysis.squeeze
    assert isinstance(analysis.vwap, dict)


def test_chart_analysis_from_spot_history_returns_none_when_too_short():
    t0 = datetime(2026, 8, 19, 10, 0, 0, tzinfo=IST)
    hist = [(t0, 77000.0), (t0 + timedelta(seconds=30), 77010.0)]
    assert _chart_analysis_from_spot_history(hist, 77010.0) is None


@patch("app.engines.eod_local_base_replay.get_settings")
def test_replay_selection_rank_includes_coil_prediction_bonus(mock_settings):
    mock_settings.return_value = MagicMock(
        pad_lane_selector_rank_bonus=18.0,
        ftv_direct_trade_selector_rank_bonus=55.0,
        expansion_strike_rank_bonus_enabled=True,
        expansion_strike_rank_bonus=15.0,
        eod_replay_early_pad_rank_penalty=12.0,
        eod_replay_live_session_gates_enabled=False,
    )
    snap = _snap()
    alert = {
        "side": "CALL",
        "coilCoiling": True,
        "coilReadinessScore": 72.0,
        "coilPredictedSide": "CALL",
    }
    base = _replay_selection_rank({"rankScore": 80.0}, alert, snap, {"SENSEX": snap})
    assert base == 90.0


def test_evaluate_local_base_entry_blocks_non_top_moment():
    snap = _snap()
    alert = {
        "tier": "BUILDING",
        "explosionScore": 50,
        "premium": 95.0,
        "side": "CALL",
        "strike": 77000.0,
    }
    allowed, reason, _, _ = evaluate_local_base_entry(alert, snap)
    assert not allowed
    assert reason == "not_top_moment_radar"


@patch("app.engines.eod_local_base_replay.get_settings")
@patch("app.engines.ict_breakout_monitor.first_lift_entry_readiness")
def test_evaluate_local_base_entry_passes_v_rip(mock_lift, mock_settings):
    mock_settings.return_value = MagicMock(
        top_moments_only_enabled=True,
        top_moments_min_grade="A",
        explosion_min_premium_inr=15.0,
    )
    mock_lift.return_value = (True, "v_rip_session_low_ready")
    snap = _snap(chart=_bullish_chart())
    alert = {
        "tier": "EXPLODING",
        "explosionScore": 72,
        "premium": 95.0,
        "side": "CALL",
        "strike": 77000.0,
        "ictVRipReady": True,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "ictBaseRelativeMovePct": 8.0,
        "velocity3s": 2.5,
        "velocity9s": 1.5,
        "volumeSurge": 2.5,
        "ictFirstLift": True,
    }
    allowed, reason, moment, ranking = evaluate_local_base_entry(alert, snap)
    assert allowed
    assert moment == "V"
    assert ranking.get("grade") in ("A", "S", "B")


@patch("app.engines.eod_local_base_replay.get_settings")
@patch("app.engines.ict_breakout_monitor.first_lift_entry_readiness")
def test_evaluate_local_base_entry_rejects_failed_lift(mock_lift, mock_settings):
    mock_settings.return_value = MagicMock(
        top_moments_only_enabled=True,
        top_moments_min_grade="A",
        explosion_min_premium_inr=15.0,
    )
    mock_lift.return_value = (False, "first_lift_index_turn_not_confirmed")
    snap = _snap(chart=_bearish_chart())
    alert = {
        "tier": "ELITE",
        "explosionScore": 80,
        "premium": 120.0,
        "side": "CALL",
        "strike": 77000.0,
        "ictEliteBaseReady": True,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "ictBaseRelativeMovePct": 4.0,
        "velocity3s": 3.0,
        "velocity9s": 2.0,
        "volumeSurge": 3.0,
    }
    allowed, reason, _, _ = evaluate_local_base_entry(alert, snap)
    assert not allowed
    assert reason == "first_lift_index_turn_not_confirmed"


def test_replay_local_base_day_no_tape():
    with patch(
        "app.engines.eod_local_base_replay._load_batches",
        return_value=[],
    ):
        rep = replay_local_base_day("2026-08-22")
    assert rep["status"] == "no_tape"


def test_generate_eod_local_base_replay_includes_comparison():
    date = "2026-08-19"
    with (
        patch(
            "app.engines.eod_local_base_replay.replay_local_base_day",
            return_value={
                "date": date,
                "status": "ok",
                "netPnlInr": 1000,
                "tradeCount": 1,
                "trades": [],
            },
        ),
        patch(
            "app.engines.eod_trade_report.generate_eod_trade_report",
            return_value={
                "date": date,
                "status": "ok",
                "netPnlInr": 500,
                "tradeCount": 2,
                "note": "legacy",
            },
        ),
    ):
        rep = generate_eod_local_base_replay(date)
    assert rep["comparison"]["deltaPnlInr"] == 500
    assert rep["comparison"]["legacyEodReport"]["tradeCount"] == 2


@patch("app.engines.eod_local_base_replay.get_settings")
@patch("app.engines.directional_lock.get_settings")
@patch("app.engines.best_side_selection.get_settings")
def test_replay_live_gates_block_call_flip_without_dominance(
    mock_best_settings,
    mock_dir_settings,
    mock_replay_settings,
):
    from app.config import Settings
    from app.engines.directional_lock import record_trade_side, reset_directional_lock

    settings = Settings(
        eod_replay_live_session_gates_enabled=True,
        best_side_selection_enabled=True,
        directional_side_lock_enabled=True,
    )
    mock_replay_settings.return_value = settings
    mock_dir_settings.return_value = settings
    mock_best_settings.return_value = settings

    reset_directional_lock()
    bearish = _bearish_chart()
    put_snap = _snap(side="PUT", chart=bearish)
    put_snap.breadth = Breadth(bias="NEUTRAL", aligned=False)
    record_trade_side("SENSEX", Side.PUT, put_snap)

    call_snap = _snap(side="CALL", chart=bearish)
    call_snap.breadth = Breadth(bias="NEUTRAL", aligned=False)
    call_snap.explosionAlerts = [
        {
            "side": "CALL",
            "strike": 77000.0,
            "tier": "BUILDING",
            "explosionScore": 40.0,
            "velocity3s": 0.8,
            "premium": 100.0,
        }
    ]
    alert = call_snap.explosionAlerts[0]
    allowed, reason = evaluate_replay_live_gates(
        alert,
        call_snap,
        {"SENSEX": call_snap},
        settings=settings,
        skip_session_gate=True,
    )
    assert allowed is False
    assert "directional" in reason or "switch" in reason


@patch("app.engines.eod_local_base_replay.get_settings")
@patch("app.engines.directional_lock.get_settings")
@patch("app.engines.best_side_selection.get_settings")
def test_replay_live_gates_allow_dominant_call_flip(
    mock_best_settings,
    mock_dir_settings,
    mock_replay_settings,
):
    from app.config import Settings
    from app.engines.directional_lock import record_trade_side, reset_directional_lock

    settings = Settings(
        eod_replay_live_session_gates_enabled=True,
        best_side_selection_enabled=True,
        directional_side_lock_enabled=True,
        best_side_power_hour_min_velocity_3s=1.8,
        best_side_power_hour_min_velocity_ratio=1.3,
    )
    mock_replay_settings.return_value = settings
    mock_dir_settings.return_value = settings
    mock_best_settings.return_value = settings

    reset_directional_lock()
    bearish = _bearish_chart()
    put_snap = _snap(side="PUT", chart=bearish)
    put_snap.breadth = Breadth(bias="NEUTRAL", aligned=False)
    record_trade_side("SENSEX", Side.PUT, put_snap)

    call_snap = _snap(side="CALL", chart=bearish)
    call_snap.breadth = Breadth(bias="NEUTRAL", aligned=False)
    call_snap.explosiveRunnerWatchlist = [
        {"side": "CALL", "premiumVelocityPct": 2.5, "score": 52.0},
        {"side": "PUT", "premiumVelocityPct": 0.2, "score": 30.0},
    ]
    call_snap.explosionAlerts = [
        {
            "side": "CALL",
            "strike": 77000.0,
            "tier": "BUILDING",
            "explosionScore": 52.0,
            "velocity3s": 2.5,
            "premium": 115.0,
        }
    ]
    alert = call_snap.explosionAlerts[0]
    allowed, reason = evaluate_replay_live_gates(
        alert,
        call_snap,
        {"SENSEX": call_snap},
        settings=settings,
        skip_session_gate=True,
    )
    assert allowed is True, reason


def test_replay_clock_drives_power_hour_window():
    import app.engines.power_hour_guards as power_hour

    original = power_hour._minutes_now
    original_phase = power_hour.get_market_phase
    try:
        power_hour.get_market_phase = lambda: "LIVE_MARKET"
        _ReplayDateTime.current = datetime(2026, 8, 28, 15, 10, 0, tzinfo=IST)
        saved = _install_replay_clock(_ReplayDateTime)
        assert power_hour.in_power_hour_window() is True
        _ReplayDateTime.current = datetime(2026, 8, 28, 14, 30, 0, tzinfo=IST)
        assert power_hour.in_power_hour_window() is False
        _restore_replay_clock(saved)
    finally:
        power_hour._minutes_now = original
        power_hour.get_market_phase = original_phase
