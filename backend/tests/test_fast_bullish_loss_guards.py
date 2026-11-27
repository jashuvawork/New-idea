"""Fast bullish local base — block Nov26-style extended-pad chase at session extreme."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.config import Settings
from app.engines.ict_breakout_monitor import _fast_bullish_local_base_readiness
from app.models.schemas import Breadth, ChartAnalysis, MarketPhase, Side, SpotChart, SymbolSnapshot


def _settings() -> Settings:
    return Settings()


def _snap_call_at_high() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp="2026-11-26T11:17:00+05:30",
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=83100.0,
        atmStrike=83000.0,
        tradeQualityScore=55.0,
        breadth=Breadth(bias="BULLISH", score=50, aligned=True),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.05),
        chartAnalysis=ChartAnalysis(consensus="BULLISH"),
    )


@patch("app.engines.index_tick_helpers.resolve_index_session")
@patch("app.engines.bullish_local_base.bullish_local_base_prediction")
def test_blocks_nov26_ce_chase_at_session_high(mock_pred, mock_ext):
    mock_ext.return_value = {
        "hi": 83200.0,
        "lo": 82500.0,
        "last": 83100.0,
        "open": 82600.0,
    }
    mock_pred.return_value = {"active": False}
    settings = _settings()
    ict = MagicMock(flat_then_vertical=True, active=True, base_relative_move_pct=12.0)
    alert = {
        "symbol": "SENSEX",
        "side": "CALL",
        "strike": 82900.0,
        "premium": 503.0,
        "tier": "ELITE",
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "localBaseMovePct": 12.0,
        "ictBaseRelativeMovePct": 12.0,
        "volumeAwaken": True,
        "velocity3s": 3.2,
        "drawdownFromHighPct": 0.0,
    }
    event = SimpleNamespace(
        side=Side.CALL,
        strike=82900.0,
        premium=503.0,
        velocity_3s=3.2,
    )
    with patch("app.engines.local_base_chart_bypass.local_base_momentum_turn", return_value=True):
        ok, reason = _fast_bullish_local_base_readiness(
            snap=_snap_call_at_high(),
            event=event,
            ict=ict,
            alert=alert,
            settings=settings,
        )
    assert ok is False
    assert reason in (
        "fast_bullish_elevated_pad_requires_predictor",
        "fast_bullish_elevated_pad_no_pullback",
        "exec_preflight_call_mid_pad_at_session_high",
    )


@patch("app.engines.bullish_local_base.bullish_local_base_prediction")
def test_allows_elevated_pad_when_predictor_active_with_pullback(mock_pred):
    mock_pred.return_value = {"active": True, "confidence": 72.0}
    settings = _settings()
    snap = SymbolSnapshot(
        symbol="SENSEX",
        timestamp="2026-11-25T11:16:00+05:30",
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=82800.0,
        atmStrike=82800.0,
        tradeQualityScore=55.0,
        breadth=Breadth(bias="BULLISH", score=50, aligned=True),
        spotChart=SpotChart(direction="BULLISH", momentum5Pct=0.08),
        chartAnalysis=ChartAnalysis(consensus="BULLISH"),
    )
    ict = MagicMock(flat_then_vertical=True, active=True, base_relative_move_pct=6.0)
    alert = {
        "side": "CALL",
        "strike": 82700.0,
        "premium": 480.0,
        "tier": "EXPLODING",
        "ictFlatThenVertical": True,
        "ictBreakout": True,
        "localBaseMovePct": 6.0,
        "velocity3s": 3.28,
        "drawdownFromHighPct": -4.0,
    }
    event = SimpleNamespace(side=Side.CALL, strike=82700.0, premium=480.0, velocity_3s=3.28)
    ok, reason = _fast_bullish_local_base_readiness(
        snap=snap, event=event, ict=ict, alert=alert, settings=settings,
    )
    assert ok is True, reason