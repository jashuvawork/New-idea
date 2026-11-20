"""Index near session extreme detection for scoped TP anchor (no entry block)."""

from unittest.mock import patch

from app.engines.index_lift_turn_guards import (
    index_lift_turn_blocks_side,
    index_near_extreme_chase_active,
)
from app.models.schemas import Side, SpotChart, SymbolSnapshot


def _snap(*, spot: float = 25727.0, mom5: float = 1.0) -> SymbolSnapshot:
    chart = SpotChart(
        direction="BULLISH",
        spot=spot,
        momentum5Pct=mom5,
        momentum15Pct=0.8,
        momentum10Pct=0.9,
        rsi=72.0,
        macdBias="NEUTRAL",
    )
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp="2026-11-20T12:50:00+05:30",
        marketPhase="LIVE_MARKET",
        dataAvailable=True,
        tradeQualityScore=76.0,
        spot=spot,
        spotChart=chart,
    )


@patch("app.engines.index_lift_turn_guards.index_rally_metrics")
def test_nov20_near_hod_call_chase_detected(mock_metrics):
    mock_metrics.return_value = {
        "sessionHigh": 25739.2,
        "sessionLow": 25345.2,
        "spot": 25727.0,
        "rallyPoints": 381.8,
        "slidePoints": 12.2,
    }
    active, meta = index_near_extreme_chase_active("NIFTY", Side.CALL, _snap())
    assert active is True
    assert meta.get("mode") == "index_near_session_high_call_chase"


@patch("app.engines.index_lift_turn_guards.index_rally_metrics")
def test_near_hod_does_not_block_pretrade_path(mock_metrics):
    mock_metrics.return_value = {
        "rallyPoints": 381.8,
        "slidePoints": 12.2,
    }
    blocked, reason, _ = index_lift_turn_blocks_side("NIFTY", Side.CALL, _snap())
    assert blocked is False
    assert reason == "ok"


@patch("app.engines.index_lift_turn_guards.index_rally_metrics")
def test_put_mirror_near_session_low_detected(mock_metrics):
    mock_metrics.return_value = {
        "rallyPoints": 15.0,
        "slidePoints": 380.0,
        "sessionHigh": 25739.0,
        "sessionLow": 25345.0,
        "spot": 25360.0,
    }
    active, meta = index_near_extreme_chase_active("NIFTY", Side.PUT, _snap(spot=25360.0))
    assert active is True
    assert meta.get("mode") == "index_near_session_low_put_chase"