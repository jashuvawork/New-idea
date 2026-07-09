"""Cache touch refreshes timestamp without full rebuild."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.auto_trader import get_state
from app.models.schemas import MultiSnapshot
from app.routers import market as market_router

IST = ZoneInfo("Asia/Kolkata")


def _empty_snapshot() -> MultiSnapshot:
    return MultiSnapshot(
        timestamp=datetime.now(IST) - timedelta(seconds=5),
        dataReady=True,
        snapshots={},
        autoTrader=get_state(),
    )


def test_touch_cached_snapshot_refreshes_timestamp():
    market_router._cache = _empty_snapshot()
    old_ts = market_router._cache.timestamp

    with patch("app.routers.market.is_ws_active", return_value=False):
        touched = market_router._touch_cached_snapshot()

    assert touched is not None
    assert touched.timestamp > old_ts


def test_touch_cached_snapshot_overlays_ws_when_active():
    snap = _empty_snapshot()
    market_router._cache = snap

    with (
        patch("app.routers.market.is_ws_active", return_value=True),
        patch("app.routers.market.overlay_snapshot_ltps", return_value=snap.snapshots) as mock_overlay,
    ):
        market_router._touch_cached_snapshot(overlay_ws=True)

    mock_overlay.assert_called_once()
