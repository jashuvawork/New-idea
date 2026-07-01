"""Trade store purge — clears persisted logs that block session gates."""

import json
from pathlib import Path

import pytest

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


def test_purge_removes_day_files_and_clears_log(isolated_store):
    day = isolated_store / "2026-07-01.json"
    day.write_text(json.dumps({"date": "2026-07-01", "trades": [{"id": "1", "status": "CLOSED"}], "events": []}))
    log = isolated_store / "trades.log"
    log.write_text('{"type":"TRADE_CLOSED"}\n' * 100)

    batches = isolated_store / "batches"
    batches.mkdir()
    (batches / "batch-001.json").write_text("{}")

    result = trade_store.purge_all_trade_data()

    assert not day.exists()
    assert log.read_text() == "" or "PURGE_ALL" in log.read_text()
    assert not (batches / "batch-001.json").exists()
    assert result["removedCount"] >= 3
    assert trade_store.get_milestone_batch_offset() == 0
    assert trade_store.count_today_trades()["closed"] == 0
