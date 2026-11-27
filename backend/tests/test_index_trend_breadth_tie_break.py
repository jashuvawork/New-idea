"""Breadth tie-break over 5m mom when rally/slide points are close."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.index_session_dominant_trend import index_session_dominant_trend
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    Regime,
    SpotChart,
    SymbolSnapshot,
)
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _snap(mom5: float = 0.05) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=25700.0,
        regime=Regime.CHOP,
        tradeQualityScore=50.0,
        breadth=Breadth(bias="BEARISH", score=40, aligned=True),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=mom5),
    )


def test_bearish_breadth_prefers_slide_over_mom5_bounce():
    settings = settings_mock()
    settings.index_trend_tie_break_breadth_over_mom5_enabled = True
    settings.index_trend_opposite_side_flip_margin_pts = 20.0
    with patch(
        "app.engines.pe_win_ce_mirror.call_rally_unlock_armed",
        return_value=(True, "ok", {}),
    ), patch(
        "app.engines.put_slide_ce_mirror.put_slide_unlock_armed",
        return_value=(True, "ok", {}),
    ), patch(
        "app.engines.index_rally_side_flip.index_rally_metrics",
        return_value={"rallyPoints": 50.0, "slidePoints": 52.0},
    ):
        trend, meta = index_session_dominant_trend(
            "NIFTY", _snap(mom5=0.05), AutoTraderState(), settings=settings,
        )
    assert trend == "SLIDE"
    assert meta.get("indexTrendFlip") == "breadth_slide"