"""Advisory FTV soft focus alert regressions."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.ftv_focus_alerts import (
    build_ftv_focus_alerts,
    clear_ftv_focus_alert_state,
    evaluate_ftv_focus_alert,
)
from app.models.schemas import Breadth, MarketPhase, SpotChart, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _snap(
    *,
    direction: str = "BULLISH",
    side: str = "CALL",
    tradeable: bool = True,
    tier: str = "ELITE",
) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime(2026, 8, 12, 10, 0, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=24_500,
        breadth=Breadth(bias=direction, score=65, aligned=True),
        spotChart=SpotChart(direction=direction),
        explosionAlerts=[{
            "side": side,
            "strike": 24_500,
            "explosionScore": 72,
            "tradeable": tradeable,
            "tier": tier,
            "ictFlatThenVertical": True,
            "localBaseMovePct": 12.0,
            "ictBaseRelativeMovePct": 12.0,
        }],
    )


def _live(
    *,
    confidence: str = "HIGH",
    dominant: str = "CALL",
    local_base_ready: bool = True,
    call_peak: float = 48.0,
    put_peak: float = 22.0,
) -> dict:
    return {
        "status": "READY",
        "liveReady": True,
        "localBaseReady": local_base_ready,
        "confidence": confidence,
        "dominantSide": dominant,
        "estimatedWindow": "5m",
        "baseRangePct": 0.12,
        "asOf": datetime(2026, 8, 12, 10, 15, tzinfo=IST).isoformat(),
        "sides": {
            "CALL": {"probabilities": {"1": 30.0, "5": call_peak}},
            "PUT": {"probabilities": {"1": 18.0, "5": put_peak}},
        },
    }


def test_focus_alert_fires_when_all_gates_align():
    clear_ftv_focus_alert_state()
    alert = evaluate_ftv_focus_alert("NIFTY", _snap(), _live())

    assert alert is not None
    assert alert["status"] == "ACTIVE"
    assert alert["side"] == "CALL"
    assert alert["chartAligned"] is True
    assert alert["radarTradeable"] is True
    assert "FTV focus" in alert["message"]


def test_focus_alert_blocks_without_local_base():
    clear_ftv_focus_alert_state()
    snap = _snap()
    snap.explosionAlerts = [{
        "side": "CALL",
        "strike": 24_500,
        "explosionScore": 72,
        "tradeable": True,
        "tier": "ELITE",
        "dailyMovePct": 8.0,
        "peakMovePct": 8.0,
    }]
    alert = evaluate_ftv_focus_alert(
        "NIFTY", snap, _live(local_base_ready=False),
    )
    assert alert is None


def test_focus_alert_blocks_counter_chart_side():
    clear_ftv_focus_alert_state()
    alert = evaluate_ftv_focus_alert(
        "NIFTY",
        _snap(direction="BEARISH", side="PUT"),
        _live(dominant="CALL"),
    )
    assert alert is None


def test_focus_alert_blocks_without_tradeable_radar():
    clear_ftv_focus_alert_state()
    snap = _snap(tradeable=False, tier="WATCH")
    snap.explosionAlerts = [{
        "side": "CALL",
        "strike": 24_500,
        "explosionScore": 12,
        "tradeable": False,
        "tier": "WATCH",
        "dailyMovePct": 8.0,
        "peakMovePct": 8.0,
    }]
    alert = evaluate_ftv_focus_alert(
        "NIFTY",
        snap,
        _live(),
    )
    assert alert is None


def test_focus_alert_blocks_radar_not_at_local_base():
    clear_ftv_focus_alert_state()
    snap = _snap()
    snap.explosionAlerts = [{
        "side": "CALL",
        "strike": 24_500,
        "explosionScore": 72,
        "tradeable": True,
        "tier": "ELITE",
        "dailyMovePct": 8.0,
        "peakMovePct": 8.0,
    }]
    alert = evaluate_ftv_focus_alert("NIFTY", snap, _live())
    assert alert is None


def test_focus_alert_respects_confidence_floor():
    clear_ftv_focus_alert_state()
    alert = evaluate_ftv_focus_alert(
        "NIFTY", _snap(), _live(confidence="LOW"),
    )
    assert alert is None


def test_focus_alert_cooldown_suppresses_repeat_fire():
    clear_ftv_focus_alert_state()
    first = evaluate_ftv_focus_alert("NIFTY", _snap(), _live(), now_mono=100.0)
    second = evaluate_ftv_focus_alert("NIFTY", _snap(), _live(), now_mono=120.0)

    assert first is not None and first["status"] == "ACTIVE"
    assert second is not None and second["status"] == "COOLDOWN"
    assert second["cooldownSecRemaining"] > 0


def test_build_focus_alerts_payload_sorts_active_first():
    clear_ftv_focus_alert_state()
    payload = build_ftv_focus_alerts(
        {
            "NIFTY": _snap(),
            "SENSEX": _snap(direction="BEARISH", side="PUT"),
        },
        {
            "enabled": True,
            "symbols": {
                "NIFTY": {"live": _live(dominant="CALL")},
                "SENSEX": {
                    "live": _live(
                        confidence="HIGH",
                        dominant="PUT",
                        put_peak=20.0,
                    ),
                },
            },
        },
    )

    assert payload["enabled"] is True
    assert payload["status"] == "LIVE"
    assert len(payload["active"]) == 1
    assert payload["active"][0]["symbol"] == "NIFTY"


def test_focus_alert_fires_with_index_momentum_bypass_on_counter_chart():
    clear_ftv_focus_alert_state()
    snap = _snap(direction="BEARISH", side="CALL")
    with patch(
        "app.engines.ftv_focus_alerts.index_trough_momentum_turn",
        return_value=True,
    ):
        alert = evaluate_ftv_focus_alert("NIFTY", snap, _live(dominant="CALL"))

    assert alert is not None
    assert alert["status"] == "ACTIVE"
    assert alert["indexMomentumBypass"] is True


def test_focus_alert_fires_with_option_led_base_when_index_not_compressed():
    clear_ftv_focus_alert_state()
    snap = _snap()
    live = _live(local_base_ready=False)
    live["effectiveLocalBaseReady"] = True
    live["optionLocalBaseReady"] = True
    live["baseRangePct"] = 0.35

    alert = evaluate_ftv_focus_alert("NIFTY", snap, live)

    assert alert is not None
    assert alert["status"] == "ACTIVE"
    assert alert["optionLedBase"] is True


def test_focus_alert_allows_building_radar_before_tradeable():
    clear_ftv_focus_alert_state()
    snap = _snap()
    snap.explosionAlerts = [{
        "side": "CALL",
        "strike": 24_500,
        "explosionScore": 42,
        "tradeable": False,
        "tier": "BUILDING",
        "ictFlatThenVertical": True,
        "localBaseMovePct": 12.0,
        "ictBaseRelativeMovePct": 12.0,
    }]
    alert = evaluate_ftv_focus_alert("NIFTY", snap, _live())

    assert alert is not None
    assert alert["status"] == "ACTIVE"
    assert alert["radarTradeable"] is False
    assert alert["radarTier"] == "BUILDING"


def test_focus_alert_low_confidence_with_strong_radar_and_momentum_bypass():
    clear_ftv_focus_alert_state()
    snap = _snap(direction="BEARISH", side="CALL")
    snap.explosionAlerts = [{
        "side": "CALL",
        "strike": 24_500,
        "explosionScore": 62,
        "tradeable": True,
        "tier": "ELITE",
        "ictFlatThenVertical": True,
        "localBaseMovePct": 12.0,
        "ictBaseRelativeMovePct": 12.0,
    }]
    with patch(
        "app.engines.ftv_focus_alerts.index_trough_momentum_turn",
        return_value=True,
    ):
        alert = evaluate_ftv_focus_alert(
            "NIFTY",
            snap,
            _live(confidence="LOW", call_peak=40.0),
        )

    assert alert is not None
    assert alert["status"] == "ACTIVE"
    assert alert["confidence"] == "LOW"
