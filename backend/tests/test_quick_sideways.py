"""Quick sideways scalp strategy."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.quick_sideways import (
    cap_quick_sideways_lots,
    check_quick_sideways_entry,
    evaluate_quick_sideways_exit,
    is_sideways_snapshot,
    quick_sideways_enabled,
    resolve_quick_sideways_stop_points,
    scan_quick_sideways_setups,
    score_quick_sideways,
)
from app.models.schemas import (
    Breadth,
    HeatmapStrike,
    MarketPhase,
    Orderflow,
    PaperTrade,
    Regime,
    Side,
    SpotChart,
    StrategyType,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap(**kwargs) -> SymbolSnapshot:
    base = dict(
        symbol="SENSEX",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        regime=Regime.RANGE_BOUND,
        spot=77000.0,
        atmStrike=77000.0,
        tradeQualityScore=42.0,
        breadth=Breadth(score=50, bias="NEUTRAL", aligned=False),
        orderflow=Orderflow(tickMomentum=42, deltaVelocity=38, signedMomentumPct=0.6),
        spotChart=SpotChart(
            direction="BULLISH",
            spot=77000.0,
            momentum5Pct=0.08,
            trendStrength=25,
        ),
        heatmap=[
            HeatmapStrike(strike=77000.0, callLtp=55.0, putLtp=48.0),
        ],
    )
    base.update(kwargs)
    return SymbolSnapshot(**base)


@patch("app.engines.quick_sideways.get_settings")
def test_quick_sideways_detects_range_bound(mock_settings):
    s = mock_settings.return_value
    s.quick_sideways_enabled = True
    s.rapid_scalp_mode_enabled = False
    assert quick_sideways_enabled()
    assert is_sideways_snapshot(_snap())


@patch("app.engines.quick_sideways.get_settings")
def test_scan_finds_atm_call_setup(mock_settings):
    s = mock_settings.return_value
    s.quick_sideways_enabled = True
    s.quick_sideways_min_tqs = 35
    s.quick_sideways_min_velocity_pct = 0.5
    s.quick_sideways_chop_min_velocity_pct = 0.22
    s.quick_sideways_chop_pick_momentum_pct = 0.02
    s.quick_sideways_scan_watchlist = True
    s.quick_sideways_strike_scan_radius = 250
    s.quick_sideways_allow_bearish_chop = True
    s.enhanced_velocity_threshold = 1.2
    s.quick_sideways_preferred_premium_min = 30.0
    s.quick_sideways_preferred_premium_max = 80.0
    s.quick_sideways_high_premium_penalty_start = 90.0
    setups = scan_quick_sideways_setups("SENSEX", _snap())
    assert len(setups) == 1
    assert setups[0]["side"] == Side.CALL
    assert setups[0]["strike"] == 77000.0
    assert setups[0]["score"] >= 58


@patch("app.engines.quick_sideways.get_settings")
def test_quick_sideways_exit_target(mock_settings):
    s = mock_settings.return_value
    s.quick_sideways_target_points = 3.0
    s.quick_sideways_stop_points = 2.0
    s.quick_sideways_stop_adaptive_enabled = True
    s.quick_sideways_stop_premium_lt_60 = 2.0
    s.quick_sideways_stop_premium_60_90 = 2.5
    s.quick_sideways_stop_premium_90_130 = 3.0
    s.quick_sideways_stop_premium_gt_130 = 3.5
    s.quick_sideways_micro_target_points = 2.0
    s.quick_sideways_micro_giveback_points = 1.5
    s.quick_sideways_chop_early_lock_points = 1.5
    s.quick_sideways_chop_early_giveback_points = 0.75
    s.quick_sideways_max_hold_seconds = 120
    s.quick_sideways_no_progress_seconds = 75
    s.quick_sideways_min_stop_hold_seconds = 30
    trade = PaperTrade(
        id="q1",
        symbol="SENSEX",
        side=Side.CALL,
        strike=77000,
        entryPremium=50.0,
        currentPremium=53.5,
        lots=10,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.SCALP,
    )
    reason, pnl = evaluate_quick_sideways_exit(trade, 53.5, 20)
    assert reason == "quick_sideways_target"
    assert pnl > 0


@patch("app.engines.quick_sideways.get_settings")
def test_adaptive_stop_by_premium(mock_settings):
    s = mock_settings.return_value
    s.quick_sideways_stop_adaptive_enabled = True
    s.quick_sideways_stop_points = 2.0
    s.quick_sideways_stop_premium_lt_60 = 2.0
    s.quick_sideways_stop_premium_60_90 = 2.5
    s.quick_sideways_stop_premium_90_130 = 3.0
    s.quick_sideways_stop_premium_gt_130 = 3.5
    assert resolve_quick_sideways_stop_points(45.0) == 2.0
    assert resolve_quick_sideways_stop_points(75.0) == 2.5
    assert resolve_quick_sideways_stop_points(110.0) == 3.0
    assert resolve_quick_sideways_stop_points(150.0) == 3.5


@patch("app.engines.quick_sideways.get_settings")
def test_stop_blocked_before_min_hold(mock_settings):
    s = mock_settings.return_value
    s.quick_sideways_stop_adaptive_enabled = True
    s.quick_sideways_stop_premium_lt_60 = 2.0
    s.quick_sideways_stop_premium_60_90 = 2.5
    s.quick_sideways_stop_premium_90_130 = 3.0
    s.quick_sideways_stop_premium_gt_130 = 3.5
    s.quick_sideways_target_points = 3.0
    s.quick_sideways_micro_target_points = 2.0
    s.quick_sideways_micro_giveback_points = 1.5
    s.quick_sideways_chop_early_lock_points = 1.5
    s.quick_sideways_chop_early_giveback_points = 0.75
    s.quick_sideways_max_hold_seconds = 120
    s.quick_sideways_no_progress_seconds = 75
    s.quick_sideways_min_stop_hold_seconds = 30
    from datetime import timedelta

    trade = PaperTrade(
        id="q2",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24400,
        entryPremium=119.0,
        currentPremium=116.0,
        lots=13,
        openedAt=datetime.now(IST) - timedelta(seconds=17),
        strategyType=StrategyType.SCALP,
    )
    reason, _ = evaluate_quick_sideways_exit(trade, 116.0, 65)
    assert reason is None

    trade.openedAt = datetime.now(IST) - timedelta(seconds=35)
    reason, pnl = evaluate_quick_sideways_exit(trade, 116.0, 65)
    assert reason == "quick_sideways_stop"
    assert pnl < 0


@patch("app.engines.quick_sideways.get_settings")
def test_chop_early_lock(mock_settings):
    s = mock_settings.return_value
    s.quick_sideways_stop_adaptive_enabled = True
    s.quick_sideways_stop_premium_lt_60 = 2.0
    s.quick_sideways_stop_premium_60_90 = 2.5
    s.quick_sideways_stop_premium_90_130 = 3.0
    s.quick_sideways_stop_premium_gt_130 = 3.5
    s.quick_sideways_target_points = 3.0
    s.quick_sideways_micro_target_points = 2.0
    s.quick_sideways_micro_giveback_points = 1.5
    s.quick_sideways_chop_early_lock_points = 1.5
    s.quick_sideways_chop_early_giveback_points = 0.75
    s.quick_sideways_max_hold_seconds = 120
    s.quick_sideways_no_progress_seconds = 75
    s.quick_sideways_min_stop_hold_seconds = 30
    trade = PaperTrade(
        id="q3",
        symbol="NIFTY",
        side=Side.PUT,
        strike=24100,
        entryPremium=34.0,
        currentPremium=35.0,
        lots=10,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.SCALP,
        bestPnlPoints=2.0,
        entryContext={"inChop": True},
    )
    reason, pnl = evaluate_quick_sideways_exit(trade, 35.0, 65)
    assert reason == "quick_sideways_chop_early_lock"
    assert pnl > 0


@patch("app.engines.quick_sideways.get_settings")
def test_score_prefers_cheaper_premium(mock_settings):
    s = mock_settings.return_value
    s.quick_sideways_preferred_premium_min = 30.0
    s.quick_sideways_preferred_premium_max = 80.0
    s.quick_sideways_high_premium_penalty_start = 90.0
    snap = _snap()
    cheap = score_quick_sideways(snap, Side.CALL, 77000, 55.0, 0.5)
    expensive = score_quick_sideways(snap, Side.CALL, 77000, 115.0, 0.5)
    assert cheap > expensive


@patch("app.engines.quick_sideways.get_settings")
def test_high_premium_lot_cap(mock_settings):
    s = mock_settings.return_value
    s.quick_sideways_high_premium_threshold_inr = 90.0
    s.quick_sideways_high_premium_lot_cap = 10
    assert cap_quick_sideways_lots(16, 101.0) == 10
    assert cap_quick_sideways_lots(16, 75.0) == 16


@patch("app.engines.quick_sideways.get_settings")
def test_entry_rejects_low_velocity(mock_settings):
    s = mock_settings.return_value
    s.quick_sideways_enabled = True
    s.quick_sideways_min_tqs = 35
    s.quick_sideways_min_velocity_pct = 0.5
    s.quick_sideways_chop_min_velocity_pct = 0.22
    s.quick_sideways_chop_pick_momentum_pct = 0.02
    s.quick_sideways_scan_watchlist = True
    s.quick_sideways_strike_scan_radius = 250
    s.quick_sideways_allow_bearish_chop = True
    s.enhanced_velocity_threshold = 1.2
    snap = _snap(orderflow=Orderflow(tickMomentum=5, deltaVelocity=5), spotChart=SpotChart(direction="NEUTRAL"))
    ok, reason = check_quick_sideways_entry(snap, Side.CALL, 77000, 55.0, velocity_pct=0.1)
    assert not ok
    assert "velocity" in reason


@patch("app.engines.quick_sideways.get_settings")
def test_chop_allows_lower_velocity(mock_settings):
    s = mock_settings.return_value
    s.quick_sideways_enabled = True
    s.quick_sideways_min_tqs = 35
    s.quick_sideways_min_velocity_pct = 0.5
    s.quick_sideways_chop_min_velocity_pct = 0.22
    s.quick_sideways_chop_pick_momentum_pct = 0.02
    s.quick_sideways_scan_watchlist = True
    s.quick_sideways_strike_scan_radius = 250
    s.quick_sideways_allow_bearish_chop = True
    s.enhanced_velocity_threshold = 1.2
    snap = _snap(
        regime=Regime.CHOP,
        breadth=Breadth(score=50, bias="BEARISH", aligned=False),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.03, trendStrength=20),
        explosiveRunnerWatchlist=[
            {"side": "CALL", "strike": 24400, "premium": 75.5, "premiumVelocityPct": 0.28},
        ],
        heatmap=[
            HeatmapStrike(strike=24400.0, callLtp=75.5, putLtp=48.0),
        ],
        spot=24380.0,
        atmStrike=24400.0,
    )
    ok, reason = check_quick_sideways_entry(snap, Side.CALL, 24400, 75.5, velocity_pct=0.28)
    assert ok, reason


@patch("app.engines.quick_sideways.get_settings")
def test_scan_watchlist_strike_in_chop(mock_settings):
    s = mock_settings.return_value
    s.quick_sideways_enabled = True
    s.quick_sideways_min_tqs = 35
    s.quick_sideways_min_velocity_pct = 0.5
    s.quick_sideways_chop_min_velocity_pct = 0.22
    s.quick_sideways_chop_pick_momentum_pct = 0.02
    s.quick_sideways_scan_watchlist = True
    s.quick_sideways_strike_scan_radius = 250
    s.quick_sideways_allow_bearish_chop = True
    s.enhanced_velocity_threshold = 1.2
    s.quick_sideways_preferred_premium_min = 30.0
    s.quick_sideways_preferred_premium_max = 80.0
    s.quick_sideways_high_premium_penalty_start = 90.0
    snap = _snap(
        symbol="NIFTY",
        regime=Regime.CHOP,
        spot=24380.0,
        atmStrike=24400.0,
        breadth=Breadth(score=50, bias="BEARISH", aligned=False),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.03, trendStrength=22),
        explosiveRunnerWatchlist=[
            {"side": "CALL", "strike": 24400, "premium": 75.5, "premiumVelocityPct": 0.3},
        ],
        heatmap=[HeatmapStrike(strike=24400.0, callLtp=75.5, putLtp=48.0)],
    )
    setups = scan_quick_sideways_setups("NIFTY", snap)
    assert len(setups) >= 1
    assert setups[0]["strike"] == 24400.0


@patch("app.engines.quick_sideways.get_settings")
def test_high_premium_quick_sideways_blocked_outside_pm_itm(mock_settings):
    s = mock_settings.return_value
    s.quick_sideways_enabled = True
    s.quick_sideways_min_tqs = 35
    s.quick_sideways_min_velocity_pct = 0.5
    s.quick_sideways_chop_min_velocity_pct = 0.22
    s.quick_sideways_high_premium_threshold_inr = 90.0
    s.min_option_premium_inr = 20.0
    s.max_option_premium_inr = 300.0
    s.enhanced_velocity_threshold = 1.2
    snap = _snap()
    ok, reason = check_quick_sideways_entry(snap, Side.CALL, 24250, 199.0, velocity_pct=0.6)
    assert not ok
    assert reason == "quick_sideways_premium_above_90"
