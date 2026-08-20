"""Radar health: a lagging REST backup must not mark the radar unhealthy when WS is fresh."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.services.radar_health import (
    health_status,
    record_source,
    reset_health_for_tests,
)

IST = ZoneInfo("Asia/Kolkata")


def _snaps():
    snap = SimpleNamespace(explosionAlerts=[], dataAvailable=True)
    return {"SENSEX": snap}


def _health(now):
    # Live market + a healthy WS feed so only source-cadence logic is under test.
    with (
        patch("app.services.upstox.get_market_phase", return_value="LIVE_MARKET"),
        patch(
            "app.services.upstox_ws.ws_status",
            return_value={"connected": True, "streamStale": False, "hasRecentTicks": True},
        ),
        patch("app.routers.market.latency_stats", return_value={}),
    ):
        return health_status(now=now)


def test_stale_rest_backup_does_not_flip_unhealthy_when_ws_fresh():
    reset_health_for_tests()
    now = datetime.now(IST)
    # REST backup last seen 200s ago (stale, threshold ~105s); WS entry scan fresh (1s).
    record_source("rest_snapshot", _snaps(), now=now - timedelta(seconds=200))
    record_source("ws_entry_scan", _snaps(), now=now - timedelta(seconds=1))
    h = _health(now)
    assert h["healthy"] is True
    rest_alerts = [a for a in h["alerts"] if a["code"] == "RADAR_SCAN_STALE"]
    assert rest_alerts and all(a["severity"] == "info" for a in rest_alerts)


def test_both_sources_stale_is_unhealthy():
    reset_health_for_tests()
    now = datetime.now(IST)
    # Both the REST backup and the primary WS entry scan are stale → real outage.
    record_source("rest_snapshot", _snaps(), now=now - timedelta(seconds=200))
    record_source("ws_entry_scan", _snaps(), now=now - timedelta(seconds=200))
    h = _health(now)
    assert h["healthy"] is False
    sevs = {a["severity"] for a in h["alerts"] if a["code"] == "RADAR_SCAN_STALE"}
    assert "warning" in sevs


def test_all_fresh_is_healthy():
    reset_health_for_tests()
    now = datetime.now(IST)
    record_source("rest_snapshot", _snaps(), now=now - timedelta(seconds=5))
    record_source("ws_entry_scan", _snaps(), now=now - timedelta(seconds=1))
    h = _health(now)
    assert h["healthy"] is True
    assert not [a for a in h["alerts"] if a["code"] == "RADAR_SCAN_STALE"]
