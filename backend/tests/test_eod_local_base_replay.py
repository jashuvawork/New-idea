"""EOD local-base replay — production gates on stored premium tape."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engines.eod_local_base_replay import (
    _ReplayDateTime,
    _chart_analysis_from_spot_history,
    _enrich_alert_from_contract,
    _eod_replay_quality_blocks_entry,
    _install_replay_clock,
    _is_pad_lane_entry,
    _parse_window_bound,
    _record_replay_closed_trade,
    _replay_selection_rank,
    _restore_replay_clock,
    evaluate_local_base_entry,
    evaluate_replay_live_gates,
    evaluate_replay_structural_gates,
    generate_eod_local_base_replay,
    generate_window_replay,
    replay_local_base_day,
    _spot_chart_from_history,
)
from app.models.schemas import AutoTraderState, Breadth, MarketPhase, PaperTrade, Regime, Side, SpotChart, StrategyType, SymbolSnapshot
from tests.mock_defaults import settings_mock

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


def test_parse_window_bound_accepts_hhmmss():
    start = _parse_window_bound("2026-09-02", "12:07:00")
    end = _parse_window_bound("2026-09-02", "13:40:00", end_of_day=True)
    end_inclusive = _parse_window_bound("2026-09-02", "13:40", end_of_day=True)
    assert start.hour == 12 and start.minute == 7 and start.second == 0
    assert end.hour == 13 and end.minute == 40 and end.second == 0
    assert end_inclusive.second == 59


def test_generate_window_replay_delegates_to_day_replay():
    with patch(
        "app.engines.eod_local_base_replay.replay_local_base_day",
        return_value={"date": "2026-09-02", "status": "ok", "trades": [], "netPnlInr": 0},
    ) as mock_replay:
        rep = generate_window_replay(
            "2026-09-02",
            start="12:07:00",
            end="13:40:00",
            side="CALL",
        )
    mock_replay.assert_called_once_with(
        "2026-09-02",
        window_start="12:07:00",
        window_end="13:40:00",
        side_filter="CALL",
    )
    assert rep["status"] == "ok"
    assert "12:07:00" in rep["note"]


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


def test_replay_clock_drives_elite_budget_iso_week():
    import app.engines.elite_trade_budget as elite_budget

    original = elite_budget._iso_week
    try:
        _ReplayDateTime.current = datetime(2026, 8, 19, 10, 0, 0, tzinfo=IST)
        saved = _install_replay_clock(_ReplayDateTime)
        assert elite_budget._iso_week() == "2026-W34"
        _ReplayDateTime.current = datetime(2026, 9, 1, 10, 0, 0, tzinfo=IST)
        assert elite_budget._iso_week() == "2026-W36"
        _restore_replay_clock(saved)
    finally:
        elite_budget._iso_week = original


def test_is_pad_lane_entry_recognizes_coil_pad():
    assert _is_pad_lane_entry("building_coil_pad_ready")
    assert not _is_pad_lane_entry("v_rip_session_low_ready")


@patch("app.engines.eod_local_base_replay.get_settings")
def test_eod_replay_quality_blocks_building_tier_when_enabled(mock_settings):
    mock_settings.return_value = MagicMock(
        eod_replay_require_elite_or_exploding_tier=True,
        eod_replay_pad_max_off_base_pct=22.0,
        eod_replay_min_elite_score_for_pad=90.0,
        eod_replay_block_legacy_bypass_below_min_score=True,
    )
    ok, reason = _eod_replay_quality_blocks_entry(
        {"tier": "BUILDING", "ictBaseRelativeMovePct": 12.0},
        {"eliteScore": 92.0},
        entry_reason="building_coil_pad_ready",
        settings=mock_settings.return_value,
    )
    assert not ok
    assert reason == "eod_replay_building_tier_blocked"


@patch("app.engines.eod_local_base_replay.get_settings")
def test_eod_replay_quality_blocks_pad_chase(mock_settings):
    mock_settings.return_value = MagicMock(
        eod_replay_require_elite_or_exploding_tier=True,
        eod_replay_pad_max_off_base_pct=22.0,
        eod_replay_min_elite_score_for_pad=90.0,
        eod_replay_block_legacy_bypass_below_min_score=True,
    )
    ok, reason = _eod_replay_quality_blocks_entry(
        {"tier": "ELITE", "ictBaseRelativeMovePct": 23.0},
        {"eliteScore": 92.0},
        entry_reason="building_coil_pad_ready",
        settings=mock_settings.return_value,
    )
    assert not ok
    assert reason == "eod_replay_pad_chase_blocked"


@patch("app.engines.eod_local_base_replay.get_settings")
def test_eod_replay_quality_blocks_legacy_bypass_low_score(mock_settings):
    mock_settings.return_value = MagicMock(
        eod_replay_require_elite_or_exploding_tier=False,
        eod_replay_pad_max_off_base_pct=22.0,
        eod_replay_min_elite_score_for_pad=90.0,
        eod_replay_block_legacy_bypass_below_min_score=True,
        elite_trade_min_score=90.0,
    )
    ok, reason = _eod_replay_quality_blocks_entry(
        {"tier": "ELITE", "ictBaseRelativeMovePct": 10.0},
        {"eliteScore": 74.0, "legacyBypass": "building_ftv_gate"},
        entry_reason="building_coil_pad_ready",
        settings=mock_settings.return_value,
    )
    assert not ok
    assert reason == "eod_replay_legacy_bypass_low_score"


def test_structural_gates_disabled_skips():
    cfg = settings_mock(
        eod_replay_structural_gates_enabled=False,
        eod_replay_pretrade_enabled=False,
    )
    alert = {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 23650.0,
        "premium": 33.0,
        "tier": "EXPLODING",
        "score": 90.0,
        "velocity3s": 1.0,
        "explosionScore": 80.0,
    }
    snap = _snap(side="PUT", chart=_bearish_chart())
    ok, reason = evaluate_replay_structural_gates(
        alert, snap, AutoTraderState(), {"NIFTY": snap}, settings=cfg,
    )
    assert ok is True
    assert reason == "ok"


def test_structural_gates_block_same_strike_reentry():
    cfg = settings_mock(
        eod_replay_structural_gates_enabled=True,
        session_same_strike_loss_reentry_enabled=True,
        session_same_strike_loss_reentry_min_loss_inr=500.0,
    )
    state = AutoTraderState(
        closedPaperTrades=[
            PaperTrade(
                id="prior",
                symbol="NIFTY",
                side=Side.PUT,
                strike=23650.0,
                entryPremium=33.0,
                currentPremium=27.0,
                lots=6,
                pnlInr=-2704.0,
                openedAt=datetime.now(IST),
                closedAt=datetime.now(IST),
                status="CLOSED",
                exitReason="adaptive_stop_loss",
                strategyType=StrategyType.EXPLOSIVE,
                entryContext={"selectionMode": "explosion"},
            )
        ]
    )
    alert = {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 23650.0,
        "premium": 31.0,
        "tier": "EXPLODING",
        "score": 85.0,
        "velocity3s": 2.0,
        "explosionScore": 75.0,
    }
    snap = _snap(side="PUT", chart=_bearish_chart())
    ok, reason = evaluate_replay_structural_gates(
        alert, snap, state, {"NIFTY": snap}, settings=cfg,
    )
    assert ok is False
    assert reason in (
        "session_same_strike_loss_reentry_blocked",
        "session_same_side_loss_reentry_cooldown",
    )


def test_record_replay_closed_trade_populates_state():
    state = AutoTraderState()
    entry = datetime(2026, 9, 8, 9, 58, tzinfo=IST)
    exit_t = datetime(2026, 9, 8, 10, 8, tzinfo=IST)
    trade = {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 23650.0,
        "entryPremium": 33.55,
        "exitPremium": 27.8,
        "lots": 6,
        "pnlInr": -2704.0,
        "movePct": -17.0,
        "peakPct": 5.0,
        "exitReason": "adaptive_stop_loss",
        "_entryDt": entry,
        "_exitDt": exit_t,
    }
    _record_replay_closed_trade(
        state, trade, entry_ctx={"entryReason": "armed_base"}, session_date="2026-09-08",
    )
    assert len(state.closedPaperTrades) == 1
    assert state.closedPaperTrades[0].strike == 23650.0
    assert state.lastExit is not None

