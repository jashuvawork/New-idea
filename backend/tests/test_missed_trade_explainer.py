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
    s.peak_move_explosion_min_pct = 35.0
    s.vertical_rip_bypass_enabled = True
    s.min_option_premium_inr = 20.0
    s.max_option_premium_inr = 400.0
    s.explosion_max_premium_inr = 400.0

    mock_state.return_value = AutoTraderState(running=True, skipped=[])

    report = build_missed_trade_report({"SENSEX": _snap()})
    assert report["missedCount"] >= 1 or report["passCount"] >= 1
    assert "summary" in report
    if report["missed"]:
        row = report["missed"][0]
        assert row["symbol"] == "SENSEX"
        assert row["gates"]
        assert row["primaryBlocker"] or row["wouldPass"]


@patch("app.engines.missed_trade_explainer.get_settings")
@patch("app.engines.missed_trade_explainer.get_state")
def test_missed_trade_flags_put_on_bullish(mock_state, mock_settings):
    s = mock_settings.return_value
    s.aggressive_min_explosion_score = 45.0
    s.all_day_explosion_min_score = 25.0
    s.all_day_explosion_session_move_min_pct = 40.0
    s.all_day_explosion_extreme_move_min_pct = 80.0
    s.premium_led_elite_counter_min_score = 90.0
    s.premium_led_explosion_bypass_enabled = True
    s.premium_led_counter_breadth_enabled = True
    s.chart_alignment_enabled = True
    s.chart_min_trend_strength = 25.0
    s.explosion_breadth_alignment_enabled = True
    s.worst_day_pause_enabled = False
    s.bad_day_routing_enabled = False
    s.best_trades_only_enabled = False
    s.controlled_trading_enabled = False
    s.all_day_min_chart_confidence = 62.0
    s.all_day_min_rank_score = 68.0
    s.chart_exit_levels_enabled = False
    s.worst_day_breakout_only_enabled = False
    s.whipsaw_guards_enabled = False
    s.premium_led_min_velocity_3s = 2.8
    s.premium_led_min_velocity_9s = 3.5
    s.peak_move_explosion_min_pct = 35.0
    s.vertical_rip_bypass_enabled = True
    s.vertical_rip_bypass_min_peak_pct = 30.0
    s.vertical_rip_bypass_min_score = 38.0
    s.vertical_rip_hard_breadth_bypass_enabled = True
    s.min_option_premium_inr = 20.0
    s.max_option_premium_inr = 400.0
    s.explosion_max_premium_inr = 400.0

    mock_state.return_value = AutoTraderState(running=True, skipped=[])
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24500.0,
        tradeQualityScore=50.0,
        breadth=Breadth(bias="BULLISH", score=62, aligned=True),
        spotChart=SpotChart(direction="BULLISH", spot=24500.0, trendStrength=35.0),
        explosionAlerts=[
            {
                "symbol": "NIFTY",
                "side": "PUT",
                "strike": 24050.0,
                "premium": 45.0,
                "explosionScore": 72.0,
                "tier": "EXPLODING",
                "dailyMovePct": 18.0,
                "peakMovePct": 18.0,
                "tradeable": True,
                "velocity3s": 4.5,
            },
        ],
    )
    with patch("app.engines.missed_trade_explainer.in_all_day_explosion_window", return_value=True):
        report = build_missed_trade_report({"NIFTY": snap})
    row = report["missed"][0]
    gate_names = {g["gate"] for g in row["gates"]}
    assert "breadth_hard_block" in gate_names
    assert "market_direction" in gate_names
    assert not row["wouldPass"]
