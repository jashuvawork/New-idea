"""Tests for realtime edge engine — entry scoring, PF feedback, exits."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.engines.edge_engine import (
    EdgeScore,
    check_edge_realtime_exit,
    compute_entry_edge,
    edge_rank_bonus,
    scale_lots_by_edge,
    session_pf_feedback,
    tune_plan_with_edge,
)
from app.engines.adaptive_exits import AdaptiveExitPlan
from app.engines.trade_selector import EntryCandidate
from app.models.schemas import (
    AutoTraderState,
    Breadth,
    MarketPhase,
    PaperTrade,
    Side,
    SpotChart,
    StrategyType,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap(**kwargs) -> SymbolSnapshot:
    defaults = dict(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=78000,
        tradeQualityScore=72,
        breadth=Breadth(bias="BULLISH", score=65, aligned=True),
        spotChart=SpotChart(
            direction="BULLISH",
            macdBias="BULLISH",
            rsi=58,
            momentum5Pct=0.15,
            trendStrength=70,
        ),
    )
    defaults.update(kwargs)
    return SymbolSnapshot(**defaults)


def _candidate(snap: SymbolSnapshot, score: float = 70.0) -> EntryCandidate:
    return EntryCandidate(
        symbol="SENSEX",
        snap=snap,
        mode="explosion",
        score=score,
        side=Side.CALL,
        strike=78000,
        premium=45.0,
        strategy_type=StrategyType.EXPLOSIVE,
        confidence=75,
        tqs=snap.tradeQualityScore,
        tier="BUILDING",
    )


@patch("app.engines.edge_engine.get_settings")
@patch("app.engines.morning_premium_capture.in_morning_premium_capture_window", return_value=True)
def test_compute_entry_edge_high_score_morning(_win, mock_settings):
    settings = get_settings()
    settings.edge_engine_enabled = True
    settings.edge_min_score_for_full_size = 72.0
    settings.edge_min_score_for_entry = 52.0
    settings.edge_lot_scale_min = 0.45
    settings.edge_lot_scale_max = 1.0
    settings.edge_session_pf_target = 2.5
    settings.edge_session_pf_tighten_below = 1.5
    mock_settings.return_value = settings

    snap = _snap()
    cand = _candidate(snap)
    state = AutoTraderState()
    edge = compute_entry_edge(cand, snap, state)

    assert edge.total >= 52
    assert edge.timing >= 10
    assert edge.chart >= 10
    assert edge.lot_scale > 0.45
    assert "morning_capture_window" in edge.reasons


@patch("app.engines.edge_engine.get_settings")
def test_scale_lots_by_edge(mock_settings):
    settings = get_settings()
    settings.edge_lot_scale_min = 0.45
    mock_settings.return_value = settings

    edge = EdgeScore(total=55, lot_scale=0.6)
    assert scale_lots_by_edge(100, edge) == 60
    assert scale_lots_by_edge(1, edge) == 1


def test_edge_rank_bonus():
    assert edge_rank_bonus(EdgeScore(total=88)) == 12.0
    assert edge_rank_bonus(EdgeScore(total=75)) == 8.0
    assert edge_rank_bonus(EdgeScore(total=48)) == -8.0


@patch("app.engines.edge_engine.get_settings")
def test_tune_plan_let_runners(mock_settings):
    settings = get_settings()
    settings.edge_engine_enabled = True
    settings.scalp_stop_min_points = 2.5
    mock_settings.return_value = settings

    plan = AdaptiveExitPlan(
        stopPoints=4.0,
        targetPoints=8.0,
        trailArmPoints=5.0,
        trailKeepRatio=0.55,
        microTargetPoints=2.5,
    )
    edge = EdgeScore(let_runners=True, tighten_exits=False)
    orig_target = plan.targetPoints
    tuned = tune_plan_with_edge(plan, edge)
    assert tuned.targetPoints > orig_target
    assert "edge_let_runners" in tuned.reasoning


@patch("app.engines.edge_engine.get_settings")
def test_check_momentum_exhaustion_exit(mock_settings):
    settings = get_settings()
    settings.edge_engine_enabled = True
    settings.edge_velocity_exhaustion_ratio = 0.35
    settings.edge_rsi_overbought_exit = 72.0
    settings.edge_macd_fade_exit_enabled = True
    mock_settings.return_value = settings

    trade = PaperTrade(
        id="t1",
        symbol="SENSEX",
        side=Side.CALL,
        strike=78000,
        lots=50,
        entryPremium=40.0,
        openedAt=datetime.now(IST),
        entryContext={"velocity3s": 4.0, "edgeScore": {"total": 75}},
        bestPnlPoints=5.0,
    )
    snap = _snap()
    reason, pnl = check_edge_realtime_exit(
        trade, current_premium=43.0, snap=snap, current_velocity_3s=0.5, lot_multiplier=20,
    )
    assert reason == "edge_momentum_exhaustion"
    assert pnl > 0


@patch("app.engines.edge_engine.collect_session_trades")
@patch("app.engines.edge_engine.analyze_last_n_trades")
@patch("app.engines.edge_engine.get_settings")
def test_session_pf_feedback_defensive(mock_settings, mock_analyze, mock_collect):
    settings = get_settings()
    settings.edge_session_pf_target = 2.5
    settings.edge_session_pf_tighten_below = 1.5
    mock_settings.return_value = settings
    mock_collect.return_value = [{"pnlInr": -100}] * 5
    mock_analyze.return_value = {"profitFactor": 0.8, "wins": 1, "count": 5}

    fb = session_pf_feedback(AutoTraderState())
    assert fb.lot_scale == 0.55
    assert fb.tighten_exits is True
    assert fb.pause_quick_scalps is True
