"""Slide-open lane + day-high CE block (CE/PE)."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.session_slide_open_lane import (
    session_call_near_day_high_blocked,
    slide_open_put_elite_timing_waiver,
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
    s.session_slide_open_lane_enabled = True
    s.session_call_near_day_high_block_enabled = True
    s.session_intent_authority_enabled = True
    return s


def _snap_slide() -> SymbolSnapshot:
    tf = {
        "15m": TimeframeChartRead(label="15m", direction="BEARISH", trendStrength=25).model_dump(),
        "1h": TimeframeChartRead(label="1h", direction="BEARISH", trendStrength=22).model_dump(),
        "5m": TimeframeChartRead(label="5m", direction="BULLISH", trendStrength=10).model_dump(),
    }
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=25850.0,
        regime=Regime.CHOP,
        tradeQualityScore=50.0,
        breadth=Breadth(bias="BEARISH", score=40, aligned=True),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.05),
        chartAnalysis=ChartAnalysis(consensus="BEARISH", timeframes=tf),
    )


@patch(
    "app.engines.session_slide_open_lane._in_slide_open_window",
    return_value=True,
)
@patch(
    "app.engines.session_slide_open_lane._index_below_open",
    return_value=(True, {"belowDayOpen": True}),
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
def test_slide_open_put_waives_elite_timing(_m1, _m2, _m3, _m4, _m5):
    settings = _settings()
    evidence = {
        "symbol": "NIFTY",
        "side": "PUT",
        "tier": "ELITE",
        "localBaseMovePct": 12.0,
        "explosionScore": 100,
    }
    ok, meta = slide_open_put_elite_timing_waiver(
        evidence, AutoTraderState(), _snap_slide(), settings=settings,
    )
    assert ok
    assert meta.get("slideOpenPutTimingWaiver") is True


@patch(
    "app.engines.index_tick_helpers.resolve_index_session",
    return_value={"hi": 25910.0, "lo": 25670.0, "last": 25905.0},
)
@patch(
    "app.engines.put_slide_ce_mirror.put_slide_unlock_armed",
    return_value=(True, "ok", {}),
)
@patch(
    "app.engines.pe_win_ce_mirror.call_rally_unlock_armed",
    return_value=(False, "", {}),
)
@patch(
    "app.engines.index_rally_side_flip.index_rally_metrics",
    return_value={"rallyPoints": 10.0, "slidePoints": 80.0},
)
def test_call_near_day_high_blocked_on_slide(_m1, _m2, _m3, _m4):
    settings = _settings()
    cand = SimpleNamespace(
        symbol="NIFTY",
        side=Side.CALL,
        alert={"dailyMovePct": 29.0, "localBaseMovePct": 14.8},
        pretrade_meta={},
    )
    blocked, reason, _ = session_call_near_day_high_blocked(
        cand, AutoTraderState(), {"NIFTY": _snap_slide()}, settings=settings,
    )
    assert blocked
    assert reason == "session_call_near_day_high_on_slide"