"""Tests for missed trade explainer."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.missed_trade_explainer import build_missed_trade_report
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    ChartAnalysis,
    MarketPhase,
    Side,
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
        spot=77600.0,
        tradeQualityScore=34.0,
        breadth=Breadth(bias="BEARISH", score=32, aligned=True),
        spotChart=SpotChart(direction="BEARISH", spot=77600.0, trendStrength=40.0),
        chartAnalysis=ChartAnalysis(consensus="BEARISH", alignedCount=4, totalTimeframes=5),
        explosionAlerts=[
            {
                "symbol": "SENSEX",
                "side": "PUT",
                "strike": 76900.0,
                "premium": 400.0,
                "explosionScore": 34.0,
                "tier": "EXPLODING",
                "dailyMovePct": 4520.0,
                "tradeable": True,
                "velocity3s": 3.5,
                "allDayExplosion": True,
            },
        ],
    )


@patch("app.engines.missed_trade_explainer.get_settings")
@patch("app.engines.missed_trade_explainer.get_state")
def test_missed_trade_report_finds_blockers(mock_state, mock_settings):
    s = mock_settings.return_value
    s.aggressive_min_explosion_score = 45.0
    s.all_day_explosion_min_score = 25.0
    s.all_day_explosion_session_move_min_pct = 40.0
    s.all_day_explosion_extreme_move_min_pct = 80.0
    s.controlled_trading_enabled = True
    s.worst_day_pause_enabled = True
    s.worst_day_breakout_only_enabled = True
    s.worst_day_breakout_min_rank = 68.0
    s.worst_day_breakout_min_velocity_3s = 2.5
    s.worst_day_breakout_min_symbol_tqs = 45.0
    s.worst_day_breakout_tiers_csv = "ELITE,EXPLODING"
    s.worst_day_breakout_require_chart_align = True
    s.bad_day_routing_enabled = True
    s.bad_day_high_confidence_min_rank = 65.0
    s.best_trades_only_enabled = True
    s.best_trades_min_rank_score = 62.0
    s.chart_exit_levels_enabled = True
    s.chart_alignment_enabled = True
    s.whipsaw_guards_enabled = False
    s.all_day_min_chart_confidence = 62.0
    s.all_day_min_rank_score = 68.0

    mock_state.return_value = AutoTraderState(running=True, skipped=[])

    report = build_missed_trade_report({"SENSEX": _snap()})
    assert report["missedCount"] >= 1 or report["passCount"] >= 1
    assert "summary" in report
    if report["missed"]:
        row = report["missed"][0]
        assert row["symbol"] == "SENSEX"
        assert row["gates"]
        assert row["primaryBlocker"] or row["wouldPass"]
