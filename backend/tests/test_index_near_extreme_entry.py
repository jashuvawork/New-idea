"""Near session high/low entry blocks (Nov20 25700 CE CE @ HOD)."""

from unittest.mock import MagicMock, patch

from app.engines.index_lift_turn_guards import (
    index_lift_turn_blocks_side,
    index_near_extreme_chase_active,
    index_near_extreme_entry_waiver,
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
def test_near_hod_blocks_call_without_waiver(mock_metrics):
    mock_metrics.return_value = {
        "sessionHigh": 25739.2,
        "sessionLow": 25345.2,
        "spot": 25727.0,
        "rallyPoints": 381.8,
        "slidePoints": 12.2,
    }
    event = MagicMock()
    event.tier = "ELITE"
    event.velocity_3s = 1.34
    blocked, reason, _ = index_lift_turn_blocks_side(
        "NIFTY",
        Side.CALL,
        _snap(),
        explosion_event=event,
        alert={"momentType": "building_local_base_lift", "tier": "ELITE"},
    )
    assert blocked is True
    assert reason == "index_near_session_high_blocks_call"


@patch("app.engines.index_lift_turn_guards.index_rally_metrics")
def test_first_lift_waives_near_hod_block(mock_metrics):
    mock_metrics.return_value = {
        "rallyPoints": 381.8,
        "slidePoints": 12.2,
    }
    ok, reason, _ = index_near_extreme_entry_waiver(
        Side.CALL,
        _snap(),
        meta=mock_metrics.return_value,
        alert={"evidence": {"firstLift": True}},
    )
    assert ok is True
    assert "first_lift" in reason


@patch("app.engines.index_lift_turn_guards.index_rally_metrics")
def test_breakout_waives_near_hod_when_printing_new_high(mock_metrics):
    mock_metrics.return_value = {
        "rallyPoints": 400.0,
        "slidePoints": 2.0,
    }
    ok, reason, _ = index_near_extreme_entry_waiver(
        Side.CALL,
        _snap(mom5=0.06),
        meta=mock_metrics.return_value,
        alert={},
    )
    assert ok is True
    assert reason == "index_near_extreme_session_high_breakout"


@patch("app.engines.index_lift_turn_guards.index_rally_metrics")
def test_put_mirror_near_session_low(mock_metrics):
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
    blocked, reason, _ = index_lift_turn_blocks_side("NIFTY", Side.PUT, _snap(spot=25360.0))
    assert blocked is True
    assert reason == "index_near_session_low_blocks_put"