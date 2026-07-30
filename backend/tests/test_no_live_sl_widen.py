"""Jul30 77700 CE — live chart must not widen entry SL into a −48pt blowup."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.engines.explosion_profit import _effective_stop_points
from app.engines.chart_exit_levels import update_live_chart_trail, refresh_open_trade_chart_plan
from app.models.schemas import PaperTrade, Side, StrategyType, SymbolSnapshot, MarketPhase, Breadth


def _trade(**plan_extra) -> PaperTrade:
    plan = {
        "stopPoints": 40.0,
        "entryStopPoints": 13.66,
        "naturalStopPoints": 16.1,
        "localSupportStopPoints": 16.1,
        "targetPoints": 39.0,
        "trailArmPoints": 11.0,
        "trailKeepRatio": 0.65,
        "chartConfidence": 89.0,
        **plan_extra,
    }
    return PaperTrade(
        id="46e3207a",
        symbol="SENSEX",
        side=Side.CALL,
        strike=77700.0,
        lots=90,
        entryPremium=105.42,
        currentPremium=90.0,
        openedAt=datetime.now(timezone.utc),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=9.69,
        entryContext={
            "exitPlan": plan,
            "entryChartConfidence": 88.6,
            "chartConfidence": 89.0,
            "explosionScore": 100.0,
            "explosionTier": "ELITE",
            "localBaseBasePremium": 96.52,
            "highConviction": True,
            "velocity3s": 3.34,
        },
    )


def test_effective_stop_does_not_mult_calculated_local_support():
    """Live plan stop 40 + conf×1.4 must not become ~56 — freeze at entry 13.66."""
    trade = _trade()
    eff = _effective_stop_points(trade, stop_points=8.0)
    assert eff <= 13.66 + 0.01, eff
    assert eff == 13.66


def test_effective_stop_caps_live_widened_plan_at_entry():
    trade = _trade(stopPoints=40.0, naturalStopPoints=40.0, localSupportStopPoints=40.0)
    eff = _effective_stop_points(trade, stop_points=8.0)
    assert eff == 13.66


@patch("app.engines.chart_exit_levels.compute_live_chart_trail_tuning")
@patch("app.engines.chart_exit_levels.chart_trade_confidence")
@patch("app.engines.chart_exit_levels.get_settings")
def test_live_trail_cannot_widen_above_entry_stop(mock_settings, mock_conf, mock_tuning):
    s = MagicMock()
    s.chart_exit_levels_enabled = True
    s.chart_confidence_trail_enabled = True
    s.chart_trail_tune_seconds = 0
    s.chart_confidence_half_tp_lock_pct = 0.5
    s.explosion_trail_arm_points = 4.0
    s.explosion_trail_keep_ratio = 0.65
    s.explosion_micro_target_points = 3.0
    mock_settings.return_value = s
    mock_conf.return_value = (89.0, ["mtf"])

    tuning = MagicMock()
    tuning.stopPoints = 40.0  # live wants to widen
    tuning.targetPoints = 50.0
    tuning.targetPoints2 = 60.0
    tuning.trailArmPoints = 12.0
    tuning.trailKeepRatio = 0.5
    tuning.confidenceDelta = 0.0
    tuning.tighten = False
    tuning.letRun = True
    tuning.sources = ["high_conf_let_run"]
    mock_tuning.return_value = tuning

    trade = _trade()
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(timezone.utc),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=77700.0,
        breadth=Breadth(bias="BULLISH", score=70, aligned=True),
    )
    plan = update_live_chart_trail(trade, snap)
    assert plan["stopPoints"] <= 13.66 + 0.01, plan["stopPoints"]
    assert plan["entryStopPoints"] == 13.66


@patch("app.engines.chart_exit_levels.update_live_chart_trail")
@patch("app.engines.chart_exit_levels.merge_chart_into_exit_plan")
@patch("app.engines.chart_exit_levels.get_settings")
def test_refresh_cannot_widen_above_entry_stop(mock_settings, mock_merge, mock_live):
    s = MagicMock()
    s.chart_exit_levels_enabled = True
    s.chart_exit_refresh_seconds = 0
    mock_settings.return_value = s
    mock_merge.return_value = {
        "stopPoints": 40.0,
        "entryStopPoints": 13.66,
        "naturalStopPoints": 16.1,
        "targetPoints": 50.0,
        "chartConfidence": 91.0,
        "chartExitLevels": {"stopPoints": 40.0},
        "reasoning": ["SL local support+chart 40.0pt"],
    }
    mock_live.side_effect = lambda trade, snap: (trade.entryContext or {}).get("exitPlan")

    trade = _trade()
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime.now(timezone.utc),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=77700.0,
        breadth=Breadth(bias="BULLISH", score=70, aligned=True),
    )
    plan = refresh_open_trade_chart_plan(trade, snap)
    assert plan["stopPoints"] == 13.66
    assert any("Freeze entry SL" in r for r in plan.get("reasoning") or [])
