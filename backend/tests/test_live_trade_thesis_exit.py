"""Live open-trade thesis exits — counter-leg scratch/snatch (CE/PE)."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.live_trade_thesis_monitor import (
    assess_live_trade_thesis,
    live_wrong_side_thesis_exit_reason,
)
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    ChartAnalysis,
    MarketPhase,
    PaperTrade,
    Regime,
    Side,
    SpotChart,
    StrategyType,
    SymbolSnapshot,
    TimeframeChartRead,
)
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = settings_mock()
    s.live_trade_thesis_exit_enabled = True
    s.live_trade_thesis_min_hold_seconds = 60.0
    s.live_trade_thesis_broken_min_seconds = 0.0
    s.live_trade_thesis_min_htf_oppose = 1
    s.live_trade_thesis_profit_booking_min_best_points = 10.0
    s.live_trade_thesis_profit_booking_min_remain_points = 4.0
    s.live_trade_thesis_max_action_pnl_pts = 12.0
    s.session_intent_authority_enabled = True
    s.index_session_dominant_trend_enabled = True
    return s


def _snap_slide() -> SymbolSnapshot:
    tf = {
        "15m": TimeframeChartRead(
            label="15m", direction="BEARISH", trendStrength=25, momentumPct=-0.12,
        ).model_dump(),
        "1h": TimeframeChartRead(
            label="1h", direction="BEARISH", trendStrength=22, momentumPct=-0.08,
        ).model_dump(),
        "5m": TimeframeChartRead(
            label="5m", direction="BEARISH", trendStrength=18, momentumPct=-0.06,
        ).model_dump(),
        "3m": TimeframeChartRead(
            label="3m", direction="BEARISH", trendStrength=15, momentumPct=-0.05,
        ).model_dump(),
    }
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=25700.0,
        regime=Regime.CHOP,
        tradeQualityScore=50.0,
        breadth=Breadth(bias="BEARISH", score=40, aligned=True),
        spotChart=SpotChart(direction="BEARISH", momentum5Pct=-0.06),
        chartAnalysis=ChartAnalysis(consensus="BEARISH", timeframes=tf),
    )


def _trade_call(*, worst: float = -12.0) -> PaperTrade:
    opened = datetime.now(IST) - timedelta(minutes=5)
    return PaperTrade(
        id="thesis-1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=25750.0,
        entryPremium=232.0,
        currentPremium=234.0,
        lots=1,
        openedAt=opened,
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=12.0,
        worstPnlPoints=worst,
        entryContext={
            "worstPnlPoints": worst,
            "executionChart": {"premiumChart": {"momentum3Pct": -0.5}},
        },
    )


@patch(
    "app.engines.index_tick_helpers.index_trend_breakout",
    return_value={},
)
@patch(
    "app.engines.put_slide_ce_mirror.put_slide_unlock_armed",
    return_value=(True, "ok", {}),
)
@patch(
    "app.engines.pe_win_ce_mirror.call_rally_unlock_armed",
    return_value=(True, "ok", {}),
)
@patch(
    "app.engines.index_rally_side_flip.index_rally_metrics",
    return_value={"rallyPoints": 20.0, "slidePoints": 55.0},
)
def test_assess_marks_counter_call_broken_on_slide(_m0, _m1, _m2, _m3):
    from app.engines.index_session_dominant_trend import reset_index_session_dominant_trend_for_tests

    reset_index_session_dominant_trend_for_tests()
    snap = _snap_slide()
    state = AutoTraderState()
    trade = _trade_call()
    with patch("app.engines.live_trade_thesis_monitor.get_settings", return_value=_settings()):
        assessment = assess_live_trade_thesis(trade, snap, state)
    assert assessment.get("thesisBroken") is True
    assert assessment.get("counterParticipation") is True


@patch(
    "app.engines.live_trade_thesis_monitor._premium_rolling_over",
    return_value=True,
)
@patch(
    "app.engines.index_tick_helpers.index_trend_breakout",
    return_value={},
)
@patch(
    "app.engines.put_slide_ce_mirror.put_slide_unlock_armed",
    return_value=(True, "ok", {}),
)
@patch(
    "app.engines.pe_win_ce_mirror.call_rally_unlock_armed",
    return_value=(True, "ok", {}),
)
@patch(
    "app.engines.index_rally_side_flip.index_rally_metrics",
    return_value={"rallyPoints": 20.0, "slidePoints": 55.0},
)
def test_snatch_on_counter_call_fade(_roll, _m0, _m1, _m2, _m3):
    from app.engines.index_session_dominant_trend import reset_index_session_dominant_trend_for_tests

    reset_index_session_dominant_trend_for_tests()
    snap = _snap_slide()
    state = AutoTraderState()
    trade = _trade_call(worst=-14.0)
    trade.entryContext["liveThesisBrokenSince"] = (
        datetime.now(IST) - timedelta(minutes=10)
    ).isoformat()
    with patch("app.engines.live_trade_thesis_monitor.get_settings", return_value=_settings()):
        reason = live_wrong_side_thesis_exit_reason(
            trade,
            snap,
            state,
            pnl_pts=3.5,
            best=6.0,
            hold_seconds=200.0,
            live_velocity_3s=0.0,
        )
    assert reason == "live_wrong_side_thesis_snatch"


@patch(
    "app.engines.live_trade_thesis_monitor._premium_rolling_over",
    return_value=True,
)
@patch(
    "app.engines.index_tick_helpers.index_trend_breakout",
    return_value={},
)
@patch(
    "app.engines.put_slide_ce_mirror.put_slide_unlock_armed",
    return_value=(True, "ok", {}),
)
@patch(
    "app.engines.pe_win_ce_mirror.call_rally_unlock_armed",
    return_value=(True, "ok", {}),
)
@patch(
    "app.engines.index_rally_side_flip.index_rally_metrics",
    return_value={"rallyPoints": 20.0, "slidePoints": 55.0},
)
def test_defers_when_normal_profit_booking_zone(_roll, _m0, _m1, _m2, _m3):
    from app.engines.index_session_dominant_trend import reset_index_session_dominant_trend_for_tests

    reset_index_session_dominant_trend_for_tests()
    snap = _snap_slide()
    state = AutoTraderState()
    trade = _trade_call(worst=-14.0)
    trade.entryContext["liveThesisBrokenSince"] = (
        datetime.now(IST) - timedelta(minutes=10)
    ).isoformat()
    with patch("app.engines.live_trade_thesis_monitor.get_settings", return_value=_settings()):
        reason = live_wrong_side_thesis_exit_reason(
            trade,
            snap,
            state,
            pnl_pts=8.0,
            best=14.0,
            hold_seconds=400.0,
            live_velocity_3s=0.0,
        )
    assert reason is None


@patch(
    "app.engines.index_tick_helpers.index_trend_breakout",
    return_value={},
)
@patch(
    "app.engines.put_slide_ce_mirror.put_slide_unlock_armed",
    return_value=(True, "ok", {}),
)
@patch(
    "app.engines.pe_win_ce_mirror.call_rally_unlock_armed",
    return_value=(True, "ok", {}),
)
@patch(
    "app.engines.index_rally_side_flip.index_rally_metrics",
    return_value={"rallyPoints": 20.0, "slidePoints": 55.0},
)
def test_pe_symmetric_put_on_rally_slide_counter(_m0, _m1, _m2, _m3):
    from app.engines.index_session_dominant_trend import reset_index_session_dominant_trend_for_tests

    reset_index_session_dominant_trend_for_tests()
    tf = {
        "15m": TimeframeChartRead(
            label="15m", direction="BULLISH", trendStrength=25, momentumPct=0.12,
        ).model_dump(),
        "1h": TimeframeChartRead(
            label="1h", direction="BULLISH", trendStrength=22, momentumPct=0.08,
        ).model_dump(),
        "5m": TimeframeChartRead(
            label="5m", direction="BULLISH", trendStrength=18, momentumPct=0.06,
        ).model_dump(),
    }
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=25700.0,
        regime=Regime.CHOP,
        tradeQualityScore=50.0,
        breadth=Breadth(bias="BULLISH", score=40, aligned=True),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.06),
        chartAnalysis=ChartAnalysis(consensus="BULLISH", timeframes=tf),
    )
    with patch(
        "app.engines.index_rally_side_flip.index_rally_metrics",
        return_value={"rallyPoints": 55.0, "slidePoints": 20.0},
    ):
        trade = _trade_call()
        trade.side = Side.PUT
        trade.strike = 25600.0
        state = AutoTraderState()
        with patch("app.engines.live_trade_thesis_monitor.get_settings", return_value=_settings()):
            assessment = assess_live_trade_thesis(trade, snap, state)
    assert assessment.get("thesisBroken") is True