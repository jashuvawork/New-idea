"""Index continuation rally — explosion_near_miss waiver for ATM/ITM CE/PE."""

from types import SimpleNamespace
from unittest.mock import patch

from app.config import Settings
from app.engines.index_continuation_rally_near_miss import (
    index_continuation_rally_near_miss_waive,
    index_continuation_rally_premium_bypass_active,
    index_continuation_rally_premium_ok,
)
from app.models.schemas import Side


def _snap(spot: float = 82_000.0, atm: float = 82_000.0):
    chart = SimpleNamespace(
        momentum5Pct=0.15,
        macdHistogram=0.02,
        direction="BULLISH",
        candleBias="BULLISH",
    )
    return SimpleNamespace(
        symbol="SENSEX",
        spot=spot,
        atmStrike=atm,
        spotChart=chart,
        dataAvailable=True,
    )


def test_premium_ok_band_18_to_600():
    s = Settings()
    assert index_continuation_rally_premium_ok(55.0, settings=s)
    assert index_continuation_rally_premium_ok(205.0, settings=s)
    assert index_continuation_rally_premium_ok(600.0, settings=s)
    assert not index_continuation_rally_premium_ok(17.0, settings=s)
    assert not index_continuation_rally_premium_ok(601.0, settings=s)


@patch("app.engines.ce_rally_lift_timing.ce_rally_lift_ready", return_value=(True, "ok", {}))
def test_sensex_ce_waives_atm_itm_in_continuation_band(mock_lift):
    s = Settings(index_continuation_rally_near_miss_enabled=True)
    snap = _snap()
    alert = {
        "symbol": "SENSEX",
        "side": "CALL",
        "tier": "ELITE",
        "strike": 81_900.0,
        "premium": 150.0,
        "explosionScore": 90.0,
    }
    assert index_continuation_rally_near_miss_waive(
        alert, snap=snap, settings=s,
    )
    assert alert.get("indexContinuationRallyNearMissWaive") is True
    mock_lift.assert_called_once()


@patch("app.engines.ce_rally_lift_timing.ce_rally_lift_ready", return_value=(True, "ok", {}))
def test_atm_allowed_itm_or_atm_only(mock_lift):
    s = Settings(index_continuation_rally_allow_otm=False)
    snap = _snap(spot=82_000.0, atm=82_000.0)
    alert = {
        "symbol": "SENSEX",
        "side": "CALL",
        "tier": "ELITE",
        "strike": 82_000.0,
        "premium": 200.0,
        "explosionScore": 90.0,
    }
    assert index_continuation_rally_near_miss_waive(
        alert, snap=snap, settings=s,
    )


@patch("app.engines.ce_rally_lift_timing.ce_rally_lift_ready", return_value=(True, "ok", {}))
def test_otm_rejected_when_allow_otm_false(mock_lift):
    s = Settings(index_continuation_rally_allow_otm=False)
    snap = _snap()
    alert = {
        "symbol": "SENSEX",
        "side": "CALL",
        "tier": "ELITE",
        "strike": 82_500.0,
        "premium": 80.0,
        "explosionScore": 90.0,
    }
    assert not index_continuation_rally_near_miss_waive(
        alert, snap=snap, settings=s,
    )


@patch("app.engines.pe_slide_breakdown_timing.pe_slide_breakdown_ready", return_value=(True, "ok", {}))
def test_pe_mirror_put_waive(mock_slide):
    s = Settings()
    snap = _snap(spot=25_100.0, atm=25_100.0)
    snap.symbol = "NIFTY"
    alert = {
        "symbol": "NIFTY",
        "side": "PUT",
        "tier": "BUILDING",
        "strike": 25_200.0,
        "premium": 120.0,
        "explosionScore": 40.0,
    }
    assert index_continuation_rally_near_miss_waive(
        alert, snap=snap, settings=s,
    )


@patch(
    "app.engines.index_continuation_rally_near_miss.index_continuation_rally_near_miss_waive"
)
def test_explosion_near_miss_waive_calls_index_continuation(mock_cont):
    from app.engines.rally_capture import explosion_near_miss_waive

    mock_cont.return_value = True
    snap = _snap()
    alert = {"tier": "ELITE", "side": "CALL", "symbol": "SENSEX"}
    with patch("app.engines.rally_capture.near_strike_armed_near_miss_waive", return_value=False), patch(
        "app.engines.rally_capture.armed_base_pad_near_miss_waive", return_value=False
    ):
        assert explosion_near_miss_waive(alert, snap=snap) is True
    mock_cont.assert_called_once()


@patch("app.engines.ce_rally_lift_timing.ce_rally_lift_ready", return_value=(True, "ok", {}))
def test_premium_bypass_active_stamps_and_reuses_flag(mock_lift):
    s = Settings()
    snap = _snap()
    alert = {
        "symbol": "SENSEX",
        "side": "CALL",
        "tier": "ELITE",
        "strike": 81_900.0,
        "premium": 180.0,
        "explosionScore": 90.0,
    }
    assert index_continuation_rally_premium_bypass_active(
        alert, snap, settings=s,
    )
    assert alert.get("indexContinuationRallyNearMissWaive")
    assert index_continuation_rally_premium_bypass_active(
        alert, snap, settings=s,
    )


@patch("app.engines.ce_rally_lift_timing.ce_rally_lift_ready", return_value=(True, "ok", {}))
def test_explosion_near_miss_waive_mid_rip_not_hard_blocked(mock_lift):
    """Afternoon mid-rip coil must not block index continuation near-miss waiver."""
    from app.engines.rally_capture import explosion_near_miss_waive

    s = Settings()
    snap = _snap()
    alert = {
        "symbol": "SENSEX",
        "side": "CALL",
        "tier": "ELITE",
        "strike": 82_000.0,
        "premium": 220.0,
        "explosionScore": 88.0,
    }
    assert explosion_near_miss_waive(
        alert,
        snap=snap,
        readiness_reason="mid_rip_armed_coil_rejected",
        settings=s,
    )
    assert alert.get("indexContinuationRallyNearMissWaive") is True