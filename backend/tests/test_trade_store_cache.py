"""trade_store day/session-reset cache — no per-call disk reads on the event loop hot path."""

import json
import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import trade_store

DATE = "2026-10-13"


@pytest.fixture
def store(tmp_path):
    log = tmp_path / "trades.log"
    with patch.object(trade_store, "get_store_dir", return_value=tmp_path), \
         patch.object(trade_store, "get_log_path", return_value=log), \
         patch.object(trade_store, "_today", return_value=DATE):
        trade_store.reset_trade_store_cache()
        yield tmp_path
        trade_store.reset_trade_store_cache()


def _write_day(store: Path, trades: list[dict]) -> Path:
    path = store / f"{DATE}.json"
    path.write_text(json.dumps({"date": DATE, "trades": trades, "events": [], "summary": {}}))
    return path


def _count_reads(fn, calls: int) -> int:
    real = Path.read_text
    n = {"reads": 0}

    def counting(self, *a, **k):
        n["reads"] += 1
        return real(self, *a, **k)

    with patch.object(Path, "read_text", counting):
        for _ in range(calls):
            fn()
    return n["reads"]


def test_repeated_day_reads_hit_disk_once(store):
    _write_day(store, [{"id": "t1", "status": "CLOSED"}])
    reads = _count_reads(lambda: trade_store.get_day_detail(DATE), 50)
    assert reads == 1
    assert trade_store.get_day_detail(DATE)["trades"][0]["id"] == "t1"


def test_load_day_returns_private_copy(store):
    _write_day(store, [{"id": "t1", "status": "OPEN"}])
    mine = trade_store._load_day(DATE)
    mine["trades"].append({"id": "t2"})
    mine["trades"][0]["status"] = "CLOSED"
    shared = trade_store.get_day_detail(DATE)
    assert [t["id"] for t in shared["trades"]] == ["t1"]
    assert shared["trades"][0]["status"] == "OPEN"


def test_save_day_writes_through_without_reread(store):
    _write_day(store, [])
    trade_store.get_day_detail(DATE)
    data = trade_store._load_day(DATE)
    data["trades"].append({"id": "new", "status": "CLOSED"})
    trade_store._save_day(DATE, data)
    reads = _count_reads(lambda: trade_store.get_day_detail(DATE), 5)
    assert reads == 0
    assert [t["id"] for t in trade_store.get_day_detail(DATE)["trades"]] == ["new"]
    on_disk = json.loads((store / f"{DATE}.json").read_text())
    assert [t["id"] for t in on_disk["trades"]] == ["new"]


def test_external_change_picked_up_after_revalidate_window(store):
    path = _write_day(store, [{"id": "a"}])
    assert trade_store.get_day_detail(DATE)["trades"][0]["id"] == "a"
    _write_day(store, [{"id": "a"}, {"id": "b"}])
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    with patch.object(trade_store.time, "monotonic",
                      return_value=trade_store.time.monotonic() + trade_store._CACHE_REVALIDATE_SECONDS + 1):
        ids = [t["id"] for t in trade_store.get_day_detail(DATE)["trades"]]
    assert ids == ["a", "b"]


def test_unchanged_file_revalidates_by_stat_not_read(store):
    _write_day(store, [{"id": "a"}])
    trade_store.get_day_detail(DATE)
    later = trade_store.time.monotonic() + trade_store._CACHE_REVALIDATE_SECONDS + 1
    with patch.object(trade_store.time, "monotonic", return_value=later):
        reads = _count_reads(lambda: trade_store.get_day_detail(DATE), 3)
    assert reads == 0


def test_missing_day_file_returns_empty_and_caches(store):
    assert trade_store.get_day_detail(DATE)["trades"] == []
    assert trade_store.count_today_trades() == {"open": 0, "closed": 0, "total": 0}


def test_record_close_visible_to_session_gate_immediately(store):
    _write_day(store, [{"id": "t1", "status": "OPEN"}])
    trade_store.get_day_detail(DATE)
    data = trade_store._load_day(DATE)
    data["trades"][0]["status"] = "CLOSED"
    trade_store._save_day(DATE, data)
    assert trade_store.count_today_trades()["closed"] == 1


def test_session_reset_cached_and_invalidated_on_set(store):
    assert trade_store.get_session_reset_at() is None
    reads = _count_reads(trade_store.get_session_reset_at, 20)
    assert reads == 0
    ts = datetime.fromisoformat(f"{DATE}T11:30:00+05:30")
    trade_store.set_session_reset_at(ts)
    assert trade_store.get_session_reset_at() == ts


def test_purge_resets_cache(store):
    _write_day(store, [{"id": "t1", "status": "CLOSED"}])
    assert trade_store.count_today_trades()["closed"] == 1
    trade_store.purge_all_trade_data()
    assert trade_store.get_day_detail(DATE)["trades"] == []
