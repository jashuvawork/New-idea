"""Flatten strategy opens without purge."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.engines.auto_trader import get_state, reset_session
from app.main import app
from app.models.schemas import PaperTrade
from app.services import trade_store


@pytest.fixture
def isolated_store(tmp_path):
    store = tmp_path / "trades"
    store.mkdir()
    trade_store._store_dir = store
    trade_store._log_path = store / "trades.log"
    yield store
    trade_store._store_dir = None
    trade_store._log_path = None
    from app.engines import auto_trader

    auto_trader._auto_trader_state = None
    auto_trader._state_loaded = False


def test_flatten_strategy_closes_open_legs(isolated_store):
    reset_session(preserve_open_trades=False)
    trade = PaperTrade(
        id="flat-test-1",
        symbol="NIFTY",
        side="CALL",
        strike=25850.0,
        entryPremium=80.0,
        currentPremium=79.0,
        lots=1,
        pnlInr=-65.0,
        status="OPEN",
        openedAt=datetime.now(ZoneInfo("Asia/Kolkata")),
    )
    trade_store.record_trade_opened(
        trade,
        {"executionMode": "LIVE", "instrumentKey": "NSE_FO|TEST"},
    )
    state = get_state()
    state.openPaperTrades = [trade]
    assert len(get_state().openPaperTrades) == 1

    client = TestClient(app)
    res = client.post("/api/auto-trader/flatten-strategy")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["openTradesRemaining"] == 0
    assert "flat-test-1" in body["closedIds"]