"""Session Intent authority — MTF + structural leg blocks (CE/PE paired)."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.index_session_dominant_trend import reset_index_session_dominant_trend_for_tests
from app.engines.session_intent_authority import (
    session_intent_blocks_entry,
    session_intent_suppresses_premium_led_bypass,
)
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
    s.session_intent_authority_enabled = True
    s.index_session_dominant_trend_enabled = True
    s.sep917_legacy_profile_enabled = True
    s.symmetric_best_trade_capture_enabled = True
    return s


def _snap(
    *,
    breadth_bias: str = "BEARISH",
    breadth_aligned: bool = True,
    mtf_put_aligned: bool = True,
) -> SymbolSnapshot:
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
        breadth=Breadth(bias=breadth_bias, score=40, aligned=breadth_aligned),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.05),
        chartAnalysis=ChartAnalysis(consensus="BEARISH", timeframes=tf),
    )


def _cand(side: str, local: float = 15.0) -> SimpleNamespace:
    return SimpleNamespace(
        symbol="NIFTY",
        side=Side.CALL if side == "CALL" else Side.PUT,
        alert={"localBaseMovePct": local, "tier": "EXPLODING"},
        pretrade_meta={},
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
def test_slide_day_blocks_counter_ce_mid_pad_when_htf_bearish(_m0, _m1, _m2, _m3):
    reset_index_session_dominant_trend_for_tests()
    settings = _settings()
    settings.index_trend_tie_break_breadth_over_mom5_enabled = True
    snap = _snap()
    state = AutoTraderState()
    cand = _cand("CALL", local=15.0)
    blocked, reason, meta = session_intent_blocks_entry(
        cand, state, {"NIFTY": snap}, settings=settings,
    )
    assert blocked
    assert reason in ("session_intent_counter_side_mtf", "session_intent_counter_mid_pad")
    assert meta["sessionIntent"]["sessionLeg"] in ("SLIDE", "NEUTRAL")


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
def test_rally_day_blocks_counter_put_mid_pad(_m0, _m1, _m2, _m3):
    reset_index_session_dominant_trend_for_tests()
    settings = _settings()
    tf = {
        "15m": TimeframeChartRead(label="15m", direction="BULLISH", trendStrength=25).model_dump(),
        "1h": TimeframeChartRead(label="1h", direction="BULLISH", trendStrength=22).model_dump(),
        "5m": TimeframeChartRead(label="5m", direction="BEARISH", trendStrength=10).model_dump(),
    }
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=25700.0,
        regime=Regime.CHOP,
        tradeQualityScore=50.0,
        breadth=Breadth(bias="BULLISH", score=60, aligned=True),
        spotChart=SpotChart(direction="BEARISH", momentum5Pct=-0.05),
        chartAnalysis=ChartAnalysis(consensus="BULLISH", timeframes=tf),
    )
    cand = _cand("PUT", local=14.0)
    blocked, reason, _ = session_intent_blocks_entry(
        cand, AutoTraderState(), {"NIFTY": snap}, settings=settings,
    )
    assert blocked
    assert "session_intent_counter" in reason


def test_premium_led_suppressed_on_counter_slide_ce():
    settings = _settings()
    snap = _snap()
    assert session_intent_suppresses_premium_led_bypass(
        "CALL", snap, local_pad=18.0, settings=settings,
    )
    assert not session_intent_suppresses_premium_led_bypass(
        "CALL", snap, local_pad=5.0, settings=settings,
    )