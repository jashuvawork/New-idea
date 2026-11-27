"""Order-wire final entry pass — session intent + live leg with fresh snapshots."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.order_time_entry_pass import order_time_entry_blocked
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    ChartAnalysis,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    SymbolSnapshot,
    TimeframeChartRead,
)
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _settings():
    s = settings_mock()
    s.order_time_entry_pass_enabled = True
    s.order_time_entry_pass_session_intent = True
    s.order_time_entry_pass_live_index_leg = True
    s.order_time_entry_pass_wire_hydration = True
    s.order_time_entry_pass_participation_veto = True
    s.session_intent_authority_enabled = True
    s.live_index_leg_hard_align_enabled = True
    s.enable_live_trading = True
    s.auto_trading_enabled = True
    s.index_session_dominant_trend_enabled = True
    s.sep917_legacy_profile_enabled = True
    s.symmetric_best_trade_capture_enabled = True
    return s


def _snap(*, mtf_put_aligned: bool = True) -> SymbolSnapshot:
    tf: dict = {}
    if mtf_put_aligned:
        tf["15m"] = TimeframeChartRead(
            label="15m", direction="BEARISH", trendStrength=25, momentumPct=-0.1,
        ).model_dump()
        tf["1h"] = TimeframeChartRead(
            label="1h", direction="BEARISH", trendStrength=22, momentumPct=-0.08,
        ).model_dump()
        tf["5m"] = TimeframeChartRead(
            label="5m", direction="BULLISH", trendStrength=10, momentumPct=0.05,
        ).model_dump()
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=25700.0,
        regime=Regime.CHOP,
        tradeQualityScore=50.0,
        breadth=Breadth(bias="BEARISH", score=40, aligned=True),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.05),
        chartAnalysis=ChartAnalysis(consensus="BEARISH", timeframes=tf),
    )


def _cand(side: str, local: float = 15.0) -> SimpleNamespace:
    return SimpleNamespace(
        symbol="NIFTY",
        side=Side.CALL if side == "CALL" else Side.PUT,
        alert={"localBaseMovePct": local, "tier": "EXPLODING"},
        pretrade_meta={},
        snap=None,
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
    return_value={"rallyPoints": 50.0, "slidePoints": 55.0},
)
def test_order_time_blocks_counter_ce_slide_intent(_m0, _m1, _m2, _m3):
    from app.engines.index_session_dominant_trend import reset_index_session_dominant_trend_for_tests

    reset_index_session_dominant_trend_for_tests()
    settings = _settings()
    settings.order_time_entry_pass_participation_veto = False
    state = AutoTraderState()
    snap = _snap()
    cand = _cand("CALL", local=15.0)
    blocked, reason, meta = order_time_entry_blocked(
        cand, state, {"NIFTY": snap}, is_live=True, settings=settings,
    )
    assert blocked is True
    assert "session_intent" in reason
    assert meta["checks"]["sessionIntent"]["blocked"] is True


@patch(
    "app.engines.index_tick_helpers.index_trend_breakout",
    return_value={},
)
@patch(
    "app.engines.put_slide_ce_mirror.put_slide_unlock_armed",
    return_value=(False, "", {}),
)
@patch(
    "app.engines.pe_win_ce_mirror.call_rally_unlock_armed",
    return_value=(True, "ok", {}),
)
@patch(
    "app.engines.index_rally_side_flip.index_rally_metrics",
    return_value={"rallyPoints": 80.0, "slidePoints": 10.0},
)
def test_order_time_blocks_counter_put_rally_intent(_m0, _m1, _m2, _m3):
    from app.engines.index_session_dominant_trend import reset_index_session_dominant_trend_for_tests

    reset_index_session_dominant_trend_for_tests()
    settings = _settings()
    settings.order_time_entry_pass_participation_veto = False
    state = AutoTraderState()
    tf = {
        "15m": TimeframeChartRead(
            label="15m", direction="BULLISH", trendStrength=25, momentumPct=0.1,
        ).model_dump(),
        "1h": TimeframeChartRead(
            label="1h", direction="BULLISH", trendStrength=22, momentumPct=0.08,
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
        spotChart=SpotChart(direction="BEARISH", momentum5Pct=-0.05),
        chartAnalysis=ChartAnalysis(consensus="BULLISH", timeframes=tf),
    )
    cand = _cand("PUT", local=15.0)
    blocked, reason, _ = order_time_entry_blocked(
        cand, state, {"NIFTY": snap}, is_live=True, settings=settings,
    )
    assert blocked is True
    assert "session_intent" in reason


def test_order_time_syncs_fresh_snap_onto_candidate():
    settings = _settings()
    settings.order_time_entry_pass_session_intent = False
    settings.order_time_entry_pass_live_index_leg = False
    settings.order_time_entry_pass_participation_veto = False
    cand = _cand("CALL")
    stale = _snap()
    fresh = _snap()
    fresh.spot = 25850.0
    cand.snap = stale
    blocked, _, _ = order_time_entry_blocked(
        cand, AutoTraderState(), {"NIFTY": fresh}, settings=settings,
    )
    assert blocked is False
    assert cand.snap is fresh
    assert cand.snap.spot == 25850.0


def test_order_time_disabled_is_noop():
    settings = _settings()
    settings.order_time_entry_pass_enabled = False
    blocked, reason, meta = order_time_entry_blocked(
        _cand("CALL"), AutoTraderState(), {"NIFTY": _snap()}, settings=settings,
    )
    assert blocked is False
    assert reason == "ok"
    assert meta.get("orderTimeEntryPass") is True


@patch(
    "app.engines.index_tick_helpers.resolve_index_session",
    return_value={"hi": 26200.0, "lo": 25400.0, "last": 25800.0},
)
@patch(
    "app.engines.index_tick_helpers.index_trend_breakout",
    return_value={},
)
@patch(
    "app.engines.index_rally_side_flip.index_rally_metrics",
    return_value={"rallyPoints": 20.0, "slidePoints": 70.0},
)
def test_participation_veto_blocks_ce_mid_pad_on_slide(_m0, _m1, _m2):
    from app.engines.index_session_dominant_trend import reset_index_session_dominant_trend_for_tests

    reset_index_session_dominant_trend_for_tests()
    settings = _settings()
    snap = _snap()
    snap.spot = 25800.0
    snap.spotChart = SpotChart(direction="BEARISH", momentum5Pct=-0.05)
    snap.breadth = Breadth(bias="BEARISH", score=35, aligned=True)
    cand = _cand("CALL", local=15.0)
    blocked, reason, meta = order_time_entry_blocked(
        cand,
        AutoTraderState(),
        {"NIFTY": snap},
        is_live=True,
        settings=settings,
    )
    assert blocked is True
    assert "participation_veto_counter_ce_on_slide" in reason
    assert meta["checks"]["participationVeto"]["blocked"] is True


@patch(
    "app.engines.index_tick_helpers.resolve_index_session",
    return_value={"hi": 26200.0, "lo": 25400.0, "last": 25800.0},
)
@patch(
    "app.engines.index_tick_helpers.index_trend_breakout",
    return_value={},
)
@patch(
    "app.engines.index_rally_side_flip.index_rally_metrics",
    return_value={"rallyPoints": 80.0, "slidePoints": 15.0},
)
def test_participation_veto_blocks_pe_mid_pad_on_rally(_m0, _m1, _m2):
    from app.engines.index_session_dominant_trend import reset_index_session_dominant_trend_for_tests

    reset_index_session_dominant_trend_for_tests()
    settings = _settings()
    tf = {
        "15m": TimeframeChartRead(
            label="15m", direction="BULLISH", trendStrength=25, momentumPct=0.1,
        ).model_dump(),
    }
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=25800.0,
        regime=Regime.CHOP,
        tradeQualityScore=50.0,
        breadth=Breadth(bias="BULLISH", score=60, aligned=True),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.05),
        chartAnalysis=ChartAnalysis(consensus="BULLISH", timeframes=tf),
    )
    cand = _cand("PUT", local=14.0)
    blocked, reason, _ = order_time_entry_blocked(
        cand, AutoTraderState(), {"NIFTY": snap}, is_live=True, settings=settings,
    )
    assert blocked is True
    assert "participation_veto_counter_pe_on_rally" in reason


def test_wire_hydration_merges_execution_chart_meta():
    from app.engines.order_time_entry_pass import hydrate_wire_snapshot_from_chart

    settings = _settings()
    base = _snap()
    chart_meta = {
        "source": "upstox_live",
        "spot": 25820.5,
        "indexChartFull": {
            "direction": "BEARISH",
            "momentum5Pct": -0.12,
            "momentum15Pct": -0.08,
            "rsi": 42.0,
            "macdBias": "BEARISH",
        },
        "indexMtf": {
            "consensus": "BEARISH",
            "timeframes": {
                "15m": {"direction": "BEARISH", "momentumPct": -0.1, "trendStrength": 24},
                "1h": {"direction": "BEARISH", "momentumPct": -0.07, "trendStrength": 20},
            },
        },
    }
    hydrated = hydrate_wire_snapshot_from_chart(base, chart_meta, settings=settings)
    assert hydrated.spot == 25820.5
    assert hydrated.spotChart.direction == "BEARISH"
    assert hydrated.chartAnalysis.consensus == "BEARISH"
    assert "15m" in (hydrated.chartAnalysis.timeframes or {})