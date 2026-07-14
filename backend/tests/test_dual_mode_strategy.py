"""Dual-mode weekly playbook — defensive vs aggressive."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.dual_mode_strategy import (
    defensive_day_session_active,
    good_day_session_active,
    resolve_trading_session_mode,
    skip_best_trades_only_filter,
    skip_bad_day_rank_floor,
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


def _snap(symbol: str = "NIFTY", bias: str = "BULLISH", tqs: float = 72.0) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        optionExpiry="2026-07-17",
        spot=24500.0,
        atmStrike=24500.0,
        regime=Regime.TREND_EXPANSION,
        tradeQualityScore=tqs,
        breadth=Breadth(bias=bias, score=70, aligned=True),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.25, trendStrength=65),
    )


@patch("app.engines.whipsaw_guards.is_bearish_sideways_session", return_value=False)
@patch("app.engines.chop_day_guards.in_momentum_rally_window", return_value=True)
def test_good_day_detected_on_rally(_rally, _bear):
    snaps = {"NIFTY": _snap("NIFTY", "BULLISH"), "SENSEX": _snap("SENSEX", "BULLISH")}
    active, reasons = good_day_session_active(
        AutoTraderState(), snaps, day_mode="MOMENTUM RALLY", confidence_tier="HIGH",
    )
    assert active is True
    assert "momentum_rally" in reasons


@patch("app.engines.bad_day_routing.bad_day_session_active", return_value=(True, ["bearish_sideways"]))
@patch("app.engines.worst_day_guard.session_entry_policy", return_value=("BREAKOUT_ONLY", {}))
@patch("app.engines.day_adaptive_engine.classify_day_type", return_value="WORST")
def test_defensive_on_worst_day(_cls, _pol, _bad):
    snaps = {"NIFTY": _snap("NIFTY", "BEARISH", 40)}
    active, reasons = defensive_day_session_active(
        AutoTraderState(), snaps, day_mode="EXPIRY DAY", confidence_tier="LOW",
    )
    assert active is True


@patch("app.engines.whipsaw_guards.is_bearish_sideways_session", return_value=False)
@patch("app.engines.chop_day_guards.in_momentum_rally_window", return_value=True)
@patch("app.engines.day_adaptive_engine.classify_day_type", return_value="ELITE")
def test_aggressive_mode_on_elite_rally(_cls, _rally, _bear):
    snaps = {"NIFTY": _snap(), "SENSEX": _snap("SENSEX")}
    mode, meta = resolve_trading_session_mode(
        AutoTraderState(), snaps, day_mode="BULLISH DAY", confidence_tier="ELITE",
    )
    assert mode == "AGGRESSIVE"
    assert skip_best_trades_only_filter(mode) is True
    assert skip_bad_day_rank_floor(mode) is True
    assert meta["goodDayActive"] is True


@patch("app.engines.bad_day_routing.bad_day_session_active", return_value=(True, ["session_loss"]))
@patch("app.engines.worst_day_guard.session_entry_policy", return_value=("BREAKOUT_ONLY", {}))
@patch("app.engines.day_adaptive_engine.classify_day_type", return_value="WORST")
def test_defensive_mode_on_bad_day(_cls, _pol, _bad):
    snaps = {"NIFTY": _snap("NIFTY", "BEARISH", 38)}
    mode, meta = resolve_trading_session_mode(
        AutoTraderState(), snaps, day_mode="EXPIRY DAY", confidence_tier="LOW",
    )
    assert mode == "DEFENSIVE"
    assert meta["defensiveDayActive"] is True
