"""Rolling 50-trade milestone batches."""

import json
from unittest.mock import patch

from app.engines.performance_milestone import (
    _current_batch_trades,
    _stats_for_trades,
    compute_milestone_stats,
)
from app.services import trade_store


def _trade(trade_id: str, pnl: float) -> dict:
    return {
        "id": trade_id,
        "status": "CLOSED",
        "pnlInr": pnl,
        "closedAt": f"2026-06-{int(trade_id):02d}T10:00:00+05:30",
    }


def test_current_batch_rolls_after_fifty():
    trades = [_trade(str(i), 1000.0) for i in range(1, 76)]
    batch_num, completed, batch = _current_batch_trades(trades)
    assert completed == 1
    assert batch_num == 2
    assert len(batch) == 25


def test_stats_use_current_batch_only():
    trades = [_trade(str(i), 1000.0) for i in range(1, 76)]
    _, _, batch = _current_batch_trades(trades)
    stats = _stats_for_trades(batch)
    assert stats["tradeCount"] == 25
    assert stats["netPnlInr"] == 25_000.0


@patch("app.engines.performance_milestone.trade_store.get_all_closed_trades_chronological")
def test_milestone_api_shape(mock_get):
    mock_get.return_value = [_trade(str(i), 500.0) for i in range(1, 56)]
    stats = compute_milestone_stats()
    assert stats["batchNumber"] == 2
    assert stats["completedBatches"] == 1
    assert stats["lifetimeTradeCount"] == 55
    assert stats["tradeCount"] == 5
    assert stats["tradeProgressPct"] == 10.0


@patch("app.services.trade_store.get_all_closed_trades_chronological")
def test_archive_on_fiftieth_close(mock_get, tmp_path, monkeypatch):
    batch_dir = tmp_path / "batches"
    batch_dir.mkdir()
    monkeypatch.setattr(trade_store, "_batches_dir", lambda: batch_dir)

    trades = [_trade(str(i), 1000.0) for i in range(1, 51)]
    mock_get.return_value = trades

    trade_store._maybe_archive_completed_batch()

    archive = batch_dir / "batch-001.json"
    assert archive.exists()
    data = json.loads(archive.read_text())
    assert data["batchNumber"] == 1
    assert data["tradeCount"] == 50
    assert data["summary"]["netPnlInr"] == 50_000.0
