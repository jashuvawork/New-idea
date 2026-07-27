"""Best-scalps-only gate — mid-quality CE probes during rips are blocked."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.trade_selector import (
    EntryCandidate,
    _scalp_best_quality_ok,
    _tradeable_explosion_on_side,
)
from app.models.schemas import (
    Breadth,
    MarketPhase,
    Regime,
    Side,
    SpotChart,
    StrategyType,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.scalp_best_only_enabled = True
    s.scalp_best_min_rank_score = 88.0
    s.scalp_best_min_chart_confidence = 72.0
    s.scalp_best_require_breadth_aligned = True
    s.scalp_best_require_chart_aligned = True
    s.scalp_best_atm_itm_only = True
    s.scalp_best_min_velocity_pct = 1.2
    s.scalp_best_defer_to_explosion = True
    s.moneyness_atm_tolerance_points = 50.0
    s.nifty_strike_step = 50.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _snap(**kw) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=kw.get("spot", 23950.0),
        atmStrike=kw.get("atm", 23950.0),
        regime=Regime.RANGE_BOUND,
        tradeQualityScore=60.0,
        breadth=Breadth(bias="BULLISH", score=70, aligned=True),
        spotChart=SpotChart(
            direction="BULLISH",
            momentum5Pct=0.12,
            trendStrength=70,
            emaBias="BULLISH",
            candleBias="BULLISH",
            macdBias="BULLISH",
        ),
        explosionAlerts=kw.get("alerts", []),
    )


def _cand(score=90.0, strike=23900.0, vel=2.0, confidence=90.0) -> EntryCandidate:
    sug = SimpleNamespace(
        runnerSignal=SimpleNamespace(premiumVelocityPct=vel),
        confidence=confidence,
        tqs=60.0,
    )
    return EntryCandidate(
        symbol="NIFTY",
        snap=_snap(),
        mode="scalp",
        score=score,
        side=Side.CALL,
        strike=strike,
        premium=112.0,
        strategy_type=StrategyType.SCALP,
        confidence=confidence,
        tqs=60.0,
        suggestion=sug,
    )


def test_tradeable_explosion_detected():
    snap = _snap(alerts=[{
        "side": "CALL", "strike": 24000, "tier": "ELITE",
        "tradeable": True, "explosionScore": 100,
    }])
    assert _tradeable_explosion_on_side(snap, Side.CALL) is True
    assert _tradeable_explosion_on_side(snap, Side.PUT) is False


@patch("app.engines.chart_exit_levels.chart_trade_confidence", return_value=(85.0, []))
@patch("app.engines.trade_selector.get_settings")
def test_best_scalp_passes_aligned_itm(mock_settings, _conf):
    mock_settings.return_value = _settings()
    # Disable defer so this unit test isolates alignment/moneyness/score.
    s = _settings(scalp_best_defer_to_explosion=False)
    mock_settings.return_value = s
    ok, reason = _scalp_best_quality_ok(_cand(score=90, strike=23900, vel=2.0), _snap(), s)
    assert ok, reason


@patch("app.engines.chart_exit_levels.chart_trade_confidence", return_value=(85.0, []))
def test_mid_rank_scalp_blocked(_conf):
    s = _settings(scalp_best_defer_to_explosion=False)
    ok, reason = _scalp_best_quality_ok(_cand(score=83.0), _snap(), s)
    assert ok is False
    assert "rank_below" in reason


@patch("app.engines.chart_exit_levels.chart_trade_confidence", return_value=(85.0, []))
def test_otm_scalp_blocked(_conf):
    s = _settings(scalp_best_defer_to_explosion=False)
    ok, reason = _scalp_best_quality_ok(_cand(score=92, strike=24100), _snap(), s)
    assert ok is False
    assert "atm_itm" in reason


@patch("app.engines.chart_exit_levels.chart_trade_confidence", return_value=(85.0, []))
def test_defers_when_explosion_tradeable(_conf):
    s = _settings()
    snap = _snap(alerts=[{
        "side": "CALL", "strike": 24000, "tier": "EXPLODING",
        "tradeable": True, "explosionScore": 96,
    }])
    ok, reason = _scalp_best_quality_ok(_cand(score=92), snap, s)
    assert ok is False
    assert reason == "scalp_best_defer_to_explosion"
