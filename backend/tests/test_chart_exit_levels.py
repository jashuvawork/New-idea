"""Chart-driven SL/TP/trailing and all-day quality gates."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.chart_exit_levels import (
    ChartExitLevels,
    chart_trade_confidence,
    compute_chart_exit_levels,
    compute_live_chart_trail_tuning,
    high_quality_chart_entry,
    merge_chart_into_exit_plan,
    should_promote_quick_to_trailing,
    update_live_chart_trail,
)
from app.models.schemas import (
    Breadth,
    ChartAnalysis,
    MarketPhase,
    OptimizedProfile,
    PaperTrade,
    Side,
    SpotChart,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _chart_cap_settings(s) -> None:
    s.chart_exit_max_target_points = 80.0
    s.chart_exit_max_index_structure_pct = 0.04


def _snap_with_chart(consensus: str = "BEARISH", side_bias: str = "BEARISH") -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=77800.0,
        atmStrike=77800.0,
        tradeQualityScore=72.0,
        breadth=Breadth(bias="NEUTRAL", score=52, aligned=False),
        spotChart=SpotChart(direction=consensus, spot=77800.0, trendStrength=40.0),
        chartAnalysis=ChartAnalysis(
            consensus=consensus,
            alignedCount=4,
            totalTimeframes=5,
            pivots={"P": 77700.0, "S1": 77550.0, "S2": 77400.0, "R1": 77950.0},
            fibonacci={
                "zone": "PREMIUM",
                "nearestLevel": "618",
                "retracement": {"618": 77620.0},
                "extension": {"1.618": 77200.0},
            },
            institutional={
                "structure": side_bias,
                "displacement": True,
                "bos": "bearish_bos",
                "stopHunt": "sell_side_liquidity_sweep",
            },
            ichimoku={
                "tenkan": 77750.0,
                "kijun": 77680.0,
                "senkouA": 77850.0,
                "senkouB": 77650.0,
                "cloudTop": 77850.0,
                "cloudBottom": 77650.0,
                "cloudBias": "BEARISH",
                "tkCross": "BEARISH",
                "priceVsCloud": "INSIDE",
            },
            patterns=[{"name": "bearish_engulfing", "timeframe": "5m", "strength": 0.8}],
        ),
    )


@patch("app.engines.chart_exit_levels.get_settings")
def test_chart_confidence_high_for_aligned_put(mock_settings):
    s = mock_settings.return_value
    s.chart_exit_levels_enabled = True
    snap = _snap_with_chart("BEARISH", "BEARISH")
    conf, sources = chart_trade_confidence(snap, Side.PUT)
    assert conf >= 62
    assert any("smc" in x or "mtf" in x for x in sources)


@patch("app.engines.chart_exit_levels.get_settings")
def test_compute_chart_exit_levels_structure(mock_settings):
    s = mock_settings.return_value
    s.chart_exit_levels_enabled = True
    s.scalp_stop_min_points = 2.0
    s.scalp_trail_step_points = 2.0
    s.quick_trail_promote_min_confidence = 58.0
    s.all_day_min_chart_confidence = 62.0
    _chart_cap_settings(s)

    levels = compute_chart_exit_levels(
        _snap_with_chart(), Side.PUT, 216.0, base_stop=2.0, base_target=3.0,
    )
    assert isinstance(levels, ChartExitLevels)
    assert levels.stopPoints >= 2.0
    assert levels.targetPoints >= 3.0
    assert levels.targetPoints2 >= levels.targetPoints
    assert levels.promoteToTrailing is True


@patch("app.engines.chart_exit_levels.get_settings")
def test_ichimoku_sl_tp_in_chart_exit_levels(mock_settings):
    s = mock_settings.return_value
    s.chart_exit_levels_enabled = True
    s.scalp_stop_min_points = 2.0
    s.scalp_trail_step_points = 2.0
    s.quick_trail_promote_min_confidence = 58.0
    s.all_day_min_chart_confidence = 62.0
    _chart_cap_settings(s)

    snap = _snap_with_chart()
    levels = compute_chart_exit_levels(snap, Side.PUT, 82.0, base_stop=3.0, base_target=6.0)
    assert any("ichimoku" in src for src in levels.sources)
    assert levels.stopPoints >= 2.0
    assert levels.targetPoints >= 6.0
    assert levels.targetPoints2 >= levels.targetPoints


def test_ichimoku_helpers_put_direction():
    from app.engines.chart_exit_levels import _ichimoku_stop_pts, _ichimoku_target_pts

    ich = {
        "tenkan": 77750.0,
        "kijun": 77680.0,
        "cloudTop": 77850.0,
        "cloudBottom": 77650.0,
    }
    spot = 77800.0
    sl = _ichimoku_stop_pts("PUT", spot, ich, 80.0)
    tp1, tp2 = _ichimoku_target_pts("PUT", spot, ich, 80.0)
    assert sl is not None and sl > 0
    assert tp1 > 0
    assert tp2 >= tp1


@patch("app.engines.chart_exit_levels.get_settings")
def test_merge_chart_into_exit_plan(mock_settings):
    s = mock_settings.return_value
    s.chart_exit_levels_enabled = True
    s.scalp_stop_min_points = 2.0
    s.scalp_trail_step_points = 2.0
    s.quick_trail_promote_min_confidence = 58.0
    s.all_day_min_chart_confidence = 62.0
    _chart_cap_settings(s)

    base = {"stopPoints": 2.0, "targetPoints": 3.0, "trailArmPoints": 2.5, "trailKeepRatio": 0.55}
    merged = merge_chart_into_exit_plan(base, _snap_with_chart(), Side.PUT, 216.0)
    assert merged["chartConfidence"] >= 62
    assert merged.get("targetPoints2", 0) > 0
    assert merged.get("promoteToTrailing") is True


@patch("app.engines.chart_exit_levels.get_settings")
def test_high_quality_chart_entry(mock_settings):
    s = mock_settings.return_value
    s.all_day_high_quality_enabled = True
    s.all_day_min_chart_confidence = 62.0
    s.all_day_min_rank_score = 68.0
    s.chart_exit_levels_enabled = True

    ok, conf = high_quality_chart_entry(_snap_with_chart(), Side.PUT, 70.0)
    assert ok is True
    assert conf >= 62


def test_promote_quick_to_trailing_on_chart_confidence():
    trade = PaperTrade(
        id="t1",
        symbol="SENSEX",
        side=Side.PUT,
        strike=77600.0,
        entryPremium=216.0,
        lots=10,
        openedAt=datetime.now(IST),
        entryContext={
            "chartExitLevels": {"confidence": 65, "promoteToTrailing": True},
        },
    )
    with patch("app.engines.chart_exit_levels.get_settings") as mock_settings:
        s = mock_settings.return_value
        s.quick_trail_promote_min_confidence = 58.0
        s.quick_trail_promote_min_best_points = 2.0
        assert should_promote_quick_to_trailing(trade, best_pts=1.0) is True


@patch("app.engines.chart_exit_levels.get_settings")
def test_live_chart_trail_tuning_high_confidence(mock_settings):
    s = mock_settings.return_value
    s.scalp_stop_min_points = 2.0
    s.chart_confidence_trail_enabled = True
    _chart_cap_settings(s)
    plan = {
        "stopPoints": 3.0,
        "targetPoints": 6.0,
        "targetPoints2": 9.0,
        "trailArmPoints": 3.0,
        "trailKeepRatio": 0.60,
    }
    tuning = compute_live_chart_trail_tuning(
        plan, _snap_with_chart(), Side.PUT,
        entry_confidence=65.0, live_confidence=82.0, entry_premium=216.0,
    )
    assert tuning.letRun is True
    assert tuning.trailKeepRatio < 0.60
    assert tuning.targetPoints >= 6.0


@patch("app.engines.chart_exit_levels.get_settings")
def test_live_chart_trail_tuning_confidence_fade(mock_settings):
    s = mock_settings.return_value
    s.scalp_stop_min_points = 2.0
    _chart_cap_settings(s)
    plan = {
        "stopPoints": 3.0,
        "targetPoints": 6.0,
        "targetPoints2": 9.0,
        "trailArmPoints": 3.0,
        "trailKeepRatio": 0.60,
    }
    tuning = compute_live_chart_trail_tuning(
        plan, _snap_with_chart("BULLISH", "BULLISH"), Side.PUT,
        entry_confidence=72.0, live_confidence=48.0, entry_premium=216.0,
    )
    assert tuning.tighten is True
    assert tuning.trailKeepRatio > 0.60
    assert tuning.stopPoints < 3.0


@patch("app.engines.chart_exit_levels.get_settings")
def test_update_live_chart_trail_on_trade(mock_settings):
    s = mock_settings.return_value
    s.chart_exit_levels_enabled = True
    s.chart_confidence_trail_enabled = True
    s.chart_trail_tune_seconds = 0
    s.chart_exit_max_target_points = 80.0
    s.chart_exit_max_index_structure_pct = 0.04
    s.scalp_stop_min_points = 2.0
    s.scalp_stop_points = 3.0
    s.scalp_target_points = 6.0
    s.scalp_trail_arm_points = 3.0
    s.scalp_trail_keep_ratio = 0.60
    s.scalp_trail_step_points = 2.0
    s.enhanced_micro_target_points = 2.5

    trade = PaperTrade(
        id="t2",
        symbol="SENSEX",
        side=Side.PUT,
        strike=77600.0,
        entryPremium=216.0,
        lots=10,
        openedAt=datetime.now(IST),
        entryContext={
            "entryChartConfidence": 70.0,
            "exitPlan": {
                "stopPoints": 3.0,
                "targetPoints": 6.0,
                "trailArmPoints": 3.0,
                "trailKeepRatio": 0.60,
            },
        },
    )
    out = update_live_chart_trail(trade, _snap_with_chart())
    assert out.get("chartConfidenceLive") is not None
    assert trade.entryContext.get("chartExitLive") is not None


@patch("app.engines.chart_exit_levels.get_settings")
def test_live_trail_does_not_compound_targets(mock_settings):
    s = mock_settings.return_value
    s.chart_exit_levels_enabled = True
    s.chart_confidence_trail_enabled = True
    s.chart_trail_tune_seconds = 0
    s.chart_exit_max_target_points = 80.0
    s.chart_exit_max_index_structure_pct = 0.04
    s.scalp_stop_min_points = 2.0
    s.scalp_stop_points = 3.0
    s.scalp_target_points = 6.0
    s.scalp_trail_arm_points = 3.0
    s.scalp_trail_keep_ratio = 0.60
    s.scalp_trail_step_points = 2.0
    s.enhanced_micro_target_points = 2.5

    trade = PaperTrade(
        id="t3",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24200.0,
        entryPremium=120.0,
        lots=19,
        openedAt=datetime.now(IST),
        entryContext={
            "entryChartConfidence": 95.0,
            "exitPlan": {
                "stopPoints": 2.5,
                "targetPoints": 12.0,
                "targetPoints2": 18.0,
                "entryTargetPoints": 12.0,
                "entryTargetPoints2": 18.0,
                "entryStopPoints": 2.5,
                "trailArmPoints": 3.0,
                "trailKeepRatio": 0.48,
            },
        },
    )
    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24200.0,
        atmStrike=24200.0,
        tradeQualityScore=82.0,
        breadth=Breadth(bias="BULLISH", score=85, aligned=True),
        spotChart=SpotChart(direction="BULLISH", spot=24200.0, trendStrength=40.0),
        chartAnalysis=ChartAnalysis(
            consensus="BULLISH",
            alignedCount=2,
            totalTimeframes=5,
            pivots={"P": 24180.0, "R1": 24250.0, "R2": 24320.0},
            fibonacci={"extension": {"1.618": 24300.0}},
        ),
    )
    for _ in range(20):
        update_live_chart_trail(trade, snap)
    tp = float(trade.entryContext["exitPlan"]["targetPoints"])
    tp2 = float(trade.entryContext["exitPlan"]["targetPoints2"])
    assert tp <= 80.0
    assert tp2 <= 80.0
    assert tp < 1_000


@patch("app.engines.chart_exit_levels.get_settings")
def test_nifty_chart_targets_sane_with_premium_spot_pollution(mock_settings):
    s = mock_settings.return_value
    s.chart_exit_levels_enabled = True
    s.scalp_stop_min_points = 2.0
    s.scalp_trail_step_points = 2.0
    s.quick_trail_promote_min_confidence = 58.0
    s.all_day_min_chart_confidence = 62.0
    s.chart_exit_max_target_points = 80.0
    s.chart_exit_max_index_structure_pct = 0.04

    snap = SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=120.0,
        atmStrike=24200.0,
        tradeQualityScore=82.0,
        breadth=Breadth(bias="BULLISH", score=85, aligned=True),
        spotChart=SpotChart(direction="BULLISH", spot=24200.0, trendStrength=40.0),
        chartAnalysis=ChartAnalysis(
            consensus="BULLISH",
            alignedCount=2,
            totalTimeframes=5,
            pivots={"P": 24180.0, "R1": 24250.0, "R2": 24320.0},
            fibExtension={"1.618": 24300.0},
        ),
    )
    levels = compute_chart_exit_levels(snap, Side.CALL, 120.0, base_stop=2.5, base_target=8.0)
    assert levels.targetPoints <= 80.0
    assert levels.targetPoints2 <= 80.0
    assert levels.targetPoints >= 8.0
