"""Index V-turn blocks PUT into CE lift (and mirror CALL into PE slide)."""

from unittest.mock import MagicMock, patch

from app.engines.index_lift_turn_guards import (
    index_lift_turn_blocks_side,
    index_session_rally_turn_active,
    index_session_slide_turn_active,
)
from app.models.schemas import MarketProfile, Side, SpotChart, SymbolSnapshot


def _snap(
    *,
    spot: float = 81000.0,
    session_lo: float = 80600.0,
    session_hi: float = 81200.0,
    mom5: float = 0.05,
) -> SymbolSnapshot:
    chart = SpotChart(
        direction="BULLISH",
        spot=spot,
        momentum5Pct=mom5,
        momentum15Pct=0.01,
        momentum10Pct=0.03,
        rsi=55.0,
        macdBias="NEUTRAL",
    )
    profile = MarketProfile(openingRangeLow=session_lo, openingRangeHigh=session_hi)
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp="2026-11-09T11:19:00+05:30",
        marketPhase="LIVE_MARKET",
        dataAvailable=True,
        tradeQualityScore=90,
        spot=spot,
        spotChart=chart,
        marketProfile=profile,
    )


@patch("app.engines.index_lift_turn_guards.index_rally_metrics")
def test_rally_turn_active_when_off_session_low(mock_metrics):
    mock_metrics.return_value = {
        "rallyPoints": 120.0,
        "slidePoints": 200.0,
        "sessionLow": 80600.0,
        "sessionHigh": 81200.0,
        "spot": 80720.0,
    }
    active, meta = index_session_rally_turn_active("SENSEX", _snap())
    assert active is True
    assert meta.get("mode") == "index_session_rally_turn"


@patch("app.engines.index_lift_turn_guards.index_rally_metrics")
def test_rally_turn_inactive_when_too_shallow(mock_metrics):
    mock_metrics.return_value = {
        "rallyPoints": 20.0,
        "sessionLow": 80600.0,
        "sessionHigh": 81200.0,
        "spot": 80620.0,
    }
    assert index_session_rally_turn_active("SENSEX", _snap(mom5=0.0))[0] is False


@patch("app.engines.index_lift_turn_guards.index_rally_metrics")
def test_lift_turn_blocks_put_not_call(mock_metrics):
    mock_metrics.return_value = {
        "rallyPoints": 100.0,
        "slidePoints": 50.0,
        "sessionLow": 80600.0,
        "sessionHigh": 81200.0,
        "spot": 80700.0,
    }
    snap = _snap()
    put_blocked, put_reason, _ = index_lift_turn_blocks_side("SENSEX", Side.PUT, snap)
    call_blocked, call_reason, _ = index_lift_turn_blocks_side("SENSEX", Side.CALL, snap)
    assert put_blocked is True
    assert put_reason == "index_lift_turn_blocks_put"
    assert call_blocked is False
    assert call_reason == "ok"


@patch("app.engines.index_lift_turn_guards.index_rally_metrics")
def test_slide_turn_blocks_call_mirror(mock_metrics):
    mock_metrics.return_value = {
        "rallyPoints": 30.0,
        "slidePoints": 90.0,
        "sessionLow": 80600.0,
        "sessionHigh": 81200.0,
        "spot": 81110.0,
    }
    chart = SpotChart(
        direction="BEARISH",
        spot=81110.0,
        momentum5Pct=-0.06,
        momentum15Pct=-0.02,
        momentum10Pct=-0.04,
        rsi=45.0,
        macdBias="NEUTRAL",
    )
    snap = _snap(spot=81110.0, mom5=-0.06)
    snap = snap.model_copy(update={"spotChart": chart})
    call_blocked, call_reason, _ = index_lift_turn_blocks_side("SENSEX", Side.CALL, snap)
    put_blocked, _, _ = index_lift_turn_blocks_side("SENSEX", Side.PUT, snap)
    assert call_blocked is True
    assert call_reason == "index_lift_turn_blocks_call"
    assert put_blocked is False
