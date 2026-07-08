"""Tests for interval AI market analysis monitor."""

from datetime import datetime
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from app.engines.ai_market_analysis_monitor import (
    build_full_analysis_report,
    monitor_status,
    run_analysis_cycle,
)
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    Regime,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry="2026-07-09",
        spot=77600.0,
        regime=Regime.CHOP,
        tradeQualityScore=34.0,
        breadth=Breadth(bias="BULLISH", score=55, aligned=True),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.1),
        explosionAlerts=[
            {
                "symbol": "SENSEX",
                "side": "PUT",
                "strike": 76500.0,
                "premium": 392.65,
                "explosionScore": 88.0,
                "tier": "ELITE",
                "dailyMovePct": 4808.0,
                "tradeable": True,
                "allDayExplosion": True,
            },
        ],
    )


def test_build_full_analysis_report_includes_high_movers():
    state = AutoTraderState()
    report = build_full_analysis_report({"SENSEX": _snap()}, state, source="test")
    assert report["source"] == "test"
    assert report["lagScore"] is not None
    assert len(report.get("highMovers") or []) >= 1
    assert report["highMovers"][0]["strike"] == 76500.0


@patch("app.engines.ai_market_analysis_monitor.trade_store.record_analysis_report")
@patch("app.engines.ai_market_analysis_monitor.analyze_with_ai", new_callable=AsyncMock)
@patch("app.engines.ai_market_analysis_monitor.get_settings")
def test_run_analysis_cycle_persists(mock_settings, mock_ai, mock_record):
    mock_settings.return_value.ai_analysis_monitor_use_ai = False
    mock_settings.return_value.cursor_api_key = ""
    state = AutoTraderState()

    import asyncio

    report = asyncio.run(
        run_analysis_cycle({"SENSEX": _snap()}, state, source="test")
    )
    mock_record.assert_called_once()
    assert report["source"] == "test"
    mock_ai.assert_not_called()


def test_monitor_status_fields():
    status = monitor_status()
    assert "enabled" in status
    assert "intervalSeconds" in status
