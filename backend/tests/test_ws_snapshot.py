"""WebSocket fallback snapshot during Upstox REST cooldown."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.ws_snapshot import build_ws_index_snapshot
from app.models.schemas import AutoTraderState, MarketPhase

IST = ZoneInfo("Asia/Kolkata")


@patch("app.engines.ws_snapshot.is_ws_active", return_value=True)
@patch("app.engines.ws_snapshot.get_index_spot")
@patch("app.engines.ws_snapshot.get_settings")
@patch("app.engines.ws_snapshot.rate_limit_active", return_value=True)
@patch("app.engines.ws_snapshot.rate_limit_cooldown_remaining", return_value=12.0)
@patch("app.engines.ws_snapshot.get_market_phase", return_value="LIVE_MARKET")
@patch("app.engines.ws_snapshot.get_state")
def test_build_ws_index_snapshot_during_cooldown(
    mock_state,
    _phase,
    _remaining,
    _active,
    mock_settings,
    mock_spot,
    _ws,
):
    settings = MagicMock()
    settings.symbols = ["NIFTY", "SENSEX"]
    mock_settings.return_value = settings
    mock_spot.side_effect = lambda sym, **_: 24500.0 if sym == "NIFTY" else 81000.0
    mock_state.return_value = AutoTraderState()

    snap = build_ws_index_snapshot()

    assert snap is not None
    assert snap.dataReady is True
    assert "WebSocket" in (snap.waitingReason or "")
    assert snap.snapshots["NIFTY"].spot == 24500.0
    assert snap.snapshots["NIFTY"].marketPhase == MarketPhase.LIVE_MARKET


@patch("app.engines.ws_snapshot.is_ws_active", return_value=False)
def test_build_ws_index_snapshot_requires_ws(_ws):
    assert build_ws_index_snapshot() is None
