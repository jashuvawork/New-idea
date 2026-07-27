"""Best-scalps-only + local-base softening for structured CE/PE scalps."""

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
    s.scalp_best_min_rank_score = 84.0
    s.scalp_best_min_chart_confidence = 68.0
    s.scalp_best_require_breadth_aligned = True
    s.scalp_best_require_chart_aligned = True
    s.scalp_best_atm_itm_only = True
    s.scalp_best_min_velocity_pct = 1.0
    s.scalp_best_defer_to_explosion = True
    s.scalp_local_base_enabled = True
    s.scalp_local_base_min_rank_score = 80.0
    s.scalp_local_base_min_chart_confidence = 62.0
    s.scalp_local_base_min_velocity_pct = 0.8
    s.scalp_local_base_max_otm_steps = 3
    s.moneyness_atm_tolerance_points = 50.0
    s.nifty_strike_step = 50.0
    s.local_base_overrides_session_chart_enabled = True
    s.local_base_ichimoku_chart_bypass_enabled = True
    s.local_base_chart_bypass_require_ichimoku = False
    s.local_base_overrides_bearish_breadth = True
    s.local_base_require_aligned_live_momentum = True
    s.local_base_aligned_momentum_max_adverse_pct = 0.05
    s.local_base_ichimoku_max_adverse_mom5_pct = 0.12
    s.local_base_chart_bypass_min_score = 38.0
    s.local_base_chart_bypass_radar_min_move_pct = 28.0
    s.explosion_local_base_entry_min_move_pct = 15.0
    s.explosion_local_base_chase_max_move_pct = 40.0
    s.explosion_local_base_trust_min_move_pct = 8.0
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _local_alert(strike=23900.0):
    return {
        "side": "CALL",
        "strike": strike,
        "tier": "EXPLODING",
        "explosionScore": 88.0,
        "dailyMovePct": 32.0,
        "peakMovePct": 32.0,
        "velocity3s": 1.5,
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "ictBaseRelativeMovePct": 28.0,
        "ictPattern": "flat_then_vertical",
        "tradeable": True,
    }


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
        breadth=Breadth(
            bias=kw.get("breadth", "BULLISH"),
            score=70,
            aligned=kw.get("breadth", "BULLISH") == "BULLISH",
        ),
        spotChart=SpotChart(
            direction=kw.get("chart", "BULLISH"),
            momentum5Pct=kw.get("mom5", 0.12),
            trendStrength=70,
            emaBias=kw.get("chart", "BULLISH"),
            candleBias=kw.get("chart", "BULLISH"),
            macdBias=kw.get("chart", "BULLISH"),
        ),
        explosionAlerts=kw.get("alerts", []),
    )


def _cand(score=90.0, strike=23900.0, vel=2.0, confidence=90.0, alert=None) -> EntryCandidate:
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
        alert=alert,
    )


def test_tradeable_explosion_detected():
    snap = _snap(alerts=[{
        "side": "CALL", "strike": 24000, "tier": "ELITE",
        "tradeable": True, "explosionScore": 100,
    }])
    assert _tradeable_explosion_on_side(snap, Side.CALL) is True
    assert _tradeable_explosion_on_side(snap, Side.PUT) is False


@patch("app.engines.chart_exit_levels.chart_trade_confidence", return_value=(85.0, []))
def test_best_scalp_passes_aligned_itm(_conf):
    s = _settings(scalp_best_defer_to_explosion=False)
    ok, reason = _scalp_best_quality_ok(_cand(score=90, strike=23900, vel=2.0), _snap(), s)
    assert ok, reason


@patch("app.engines.chart_exit_levels.chart_trade_confidence", return_value=(85.0, []))
def test_lowered_floor_allows_84(_conf):
    s = _settings(scalp_best_defer_to_explosion=False)
    ok, reason = _scalp_best_quality_ok(_cand(score=84.0), _snap(), s)
    assert ok, reason


@patch("app.engines.chart_exit_levels.chart_trade_confidence", return_value=(85.0, []))
def test_mid_rank_scalp_still_blocked(_conf):
    s = _settings(scalp_best_defer_to_explosion=False)
    ok, reason = _scalp_best_quality_ok(_cand(score=79.0), _snap(), s)
    assert ok is False
    assert "rank_below" in reason


@patch("app.engines.chart_exit_levels.chart_trade_confidence", return_value=(85.0, []))
def test_otm_scalp_blocked_without_local_base(_conf):
    s = _settings(scalp_best_defer_to_explosion=False)
    ok, reason = _scalp_best_quality_ok(_cand(score=92, strike=24100), _snap(), s)
    assert ok is False
    assert "atm_itm" in reason


@patch("app.engines.chart_exit_levels.chart_trade_confidence", return_value=(85.0, []))
def test_defers_when_explosion_tradeable_without_local_base(_conf):
    s = _settings()
    snap = _snap(alerts=[{
        "side": "CALL", "strike": 24000, "tier": "EXPLODING",
        "tradeable": True, "explosionScore": 96,
    }])
    ok, reason = _scalp_best_quality_ok(_cand(score=92), snap, s)
    assert ok is False
    assert reason == "scalp_best_defer_to_explosion"


@patch("app.engines.local_base_chart_bypass.get_settings")
@patch("app.engines.chart_exit_levels.chart_trade_confidence", return_value=(70.0, []))
def test_local_base_softens_and_skips_defer(_conf, mock_lb):
    """Structured local-base scalp: soft floors + no defer-to-explosion."""
    s = _settings()
    mock_lb.return_value = s
    alert = _local_alert(23900.0)
    # Hostile session chart — local-base should lift alignment.
    snap = _snap(
        chart="BEARISH",
        breadth="BEARISH",
        mom5=0.02,
        alerts=[alert, {
            "side": "CALL", "strike": 24100, "tier": "ELITE",
            "tradeable": True, "explosionScore": 100,
        }],
    )
    cand = _cand(score=81.0, strike=23900.0, vel=0.9, alert=alert)
    ok, reason = _scalp_best_quality_ok(cand, snap, s)
    assert ok, reason


@patch("app.engines.local_base_chart_bypass.get_settings")
@patch("app.engines.chart_exit_levels.chart_trade_confidence", return_value=(70.0, []))
def test_local_base_allows_shallow_otm(_conf, mock_lb):
    s = _settings(scalp_best_defer_to_explosion=False)
    mock_lb.return_value = s
    alert = _local_alert(24050.0)  # 2 steps OTM from 23950 ATM
    snap = _snap(spot=23950.0, atm=23950.0, alerts=[alert])
    cand = _cand(score=82.0, strike=24050.0, vel=1.0, alert=alert)
    ok, reason = _scalp_best_quality_ok(cand, snap, s)
    assert ok, reason
