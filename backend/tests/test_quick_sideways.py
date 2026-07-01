"""Quick sideways scalp strategy."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.quick_sideways import (
    check_quick_sideways_entry,
    evaluate_quick_sideways_exit,
    is_sideways_snapshot,
    quick_sideways_enabled,
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
    s.enhanced_velocity_threshold = 1.2
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
    s.quick_sideways_micro_target_points = 2.0
    s.quick_sideways_micro_giveback_points = 1.5
    s.quick_sideways_max_hold_seconds = 120
    s.quick_sideways_no_progress_seconds = 75
    s.scalp_stop_min_hold_seconds = 30
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
def test_entry_rejects_low_velocity(mock_settings):
    s = mock_settings.return_value
    s.quick_sideways_enabled = True
    s.quick_sideways_min_tqs = 35
    s.quick_sideways_min_velocity_pct = 0.5
    s.enhanced_velocity_threshold = 1.2
    snap = _snap(orderflow=Orderflow(tickMomentum=5, deltaVelocity=5), spotChart=SpotChart(direction="NEUTRAL"))
    ok, reason = check_quick_sideways_entry(snap, Side.CALL, 77000, 55.0, velocity_pct=0.1)
    assert not ok
    assert "velocity" in reason
