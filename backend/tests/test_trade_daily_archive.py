"""Daily trade ZIP archives — paper + live persistence."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.models.schemas import PaperTrade, Side, StrategyType
from app.services import trade_store

IST = ZoneInfo("Asia/Kolkata")


def test_finalize_daily_trades_archive_writes_zip(tmp_path):
    store = tmp_path / "trades"
    store.mkdir()
    date = "2026-10-01"
    day = {
        "date": date,
        "trades": [
            {
                "id": "t1",
                "symbol": "NIFTY",
                "side": "PUT",
                "strike": 22450.0,
                "lots": 25,
                "pnlInr": 122460.0,
                "status": "CLOSED",
                "executionMode": "PAPER",
                "exitReason": "explosion_peak_keep_trail",
            }
        ],
        "events": [],
        "summary": {"netPnlInr": 122460.0, "totalTrades": 1},
    }
    (store / f"{date}.json").write_text(json.dumps(day), encoding="utf-8")
    log = store / "trades.log"
    log.write_text(
        json.dumps(
            {
                "ts": f"{date}T09:31:51+05:30",
                "event": "TRADE_CLOSED",
                "trade": {"sessionDate": date, "symbol": "NIFTY"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with patch.object(trade_store, "get_store_dir", return_value=store):
        with patch.object(trade_store, "get_log_path", return_value=log):
            with patch.object(trade_store, "get_trade_archive_dir", return_value=store / "trade_archives"):
                result = trade_store.finalize_daily_trades_archive(date)

    assert result["closedCount"] == 1
    zip_path = store / "trade_archives" / f"trades-{date}.zip"
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["netPnlInr"] == 122460.0
        assert "2026-10-01.json" in zf.namelist()
        assert "closed_trades.json" in zf.namelist()
        assert "trades_log.jsonl" in zf.namelist()


def test_get_history_ignores_non_session_json(tmp_path):
    store = tmp_path / "trades"
    store.mkdir()
    (store / "2026-10-07.json").write_text(
        json.dumps({"date": "2026-10-07", "trades": [], "summary": {}, "events": []}),
        encoding="utf-8",
    )
    (store / "milestone_meta.json").write_text("{}", encoding="utf-8")
    with patch.object(trade_store, "get_store_dir", return_value=store):
        rows = trade_store.get_history(days=10)
    assert len(rows) == 1
    assert rows[0]["date"] == "2026-10-07"
