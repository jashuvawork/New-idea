"""Oct 13 watchdog restart loop: radar telemetry I/O must not block the event loop."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from contextlib import ExitStack
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app import loop_watchdog
from app.services import radar_learning as rl

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 13, 13, 5, tzinfo=IST)
DATE = "2026-10-13"


def _settings(tmp_path, **overrides):
    values = {
        "trade_store_dir": str(tmp_path),
        "radar_archive_dir": "",
        "radar_learning_enabled": True,
        "radar_funnel_dedupe_seconds": 60,
        "radar_pipeline_history_enabled": True,
        "radar_premium_tape_sample_seconds": 10,
        "radar_alerts_tape_enabled": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def settings(tmp_path):
    s = _settings(tmp_path)
    with ExitStack() as stack:
        for target in (
            "app.services.radar_learning.get_settings",
            "app.services.radar_archive.get_settings",
            "app.services.radar_health.get_settings",
        ):
            stack.enter_context(patch(target, return_value=s))
        rl.reset_learning_state_for_tests()
        rl.drain_deferred_funnel_rows()
        yield s
        rl.drain_deferred_funnel_rows()
        rl.reset_learning_state_for_tests()


def _funnel_rows() -> list[dict]:
    path = rl.funnel_path(DATE)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_telemetry_append_skips_fsync_by_default(settings):
    with patch("app.services.radar_learning.os.fsync") as fsync:
        assert rl.record_funnel_gate_block("NIFTY", "CALL", 22250.0, "score_low", now=NOW)
    fsync.assert_not_called()
    assert [r["reason"] for r in _funnel_rows()] == ["score_low"]


def test_telemetry_fsync_opt_in(settings):
    settings.radar_telemetry_fsync_enabled = True
    with patch("app.services.radar_learning.os.fsync") as fsync:
        rl.record_funnel_gate_block("NIFTY", "PUT", 22250.0, "score_low", now=NOW)
    assert fsync.call_count == 1


@pytest.mark.parametrize("side", ["CALL", "PUT"])
def test_gate_block_on_event_loop_defers_file_io(settings, side):
    async def on_loop():
        with patch(
            "app.services.radar_learning._append_jsonl_lines",
            side_effect=AssertionError("file I/O on the event loop"),
        ):
            return rl.record_funnel_gate_block("NIFTY", side, 22250.0, "not_tradeable", now=NOW)

    assert asyncio.run(on_loop()) is True
    assert _funnel_rows() == []
    assert rl.drain_deferred_funnel_rows() == 1
    rows = _funnel_rows()
    assert [(r["side"], r["reason"], r["stage"]) for r in rows] == [
        (side, "not_tradeable", "SELECTOR_GATE")
    ]


def test_deferred_gate_block_keeps_dedupe(settings):
    async def on_loop():
        first = rl.record_funnel_gate_block("NIFTY", "CALL", 22250.0, "r", now=NOW)
        second = rl.record_funnel_gate_block("NIFTY", "CALL", 22250.0, "r", now=NOW)
        return first, second

    assert asyncio.run(on_loop()) == (True, False)
    assert rl.drain_deferred_funnel_rows() == 1


def test_funnel_state_drains_deferred_and_batches_one_append(settings):
    async def on_loop():
        rl.record_funnel_gate_block("NIFTY", "CALL", 22250.0, "selector_reject", now=NOW)

    asyncio.run(on_loop())
    skipped = [
        {"symbol": "NIFTY", "side": "CALL", "strike": 22300.0, "reason": "a"},
        {"symbol": "NIFTY", "side": "PUT", "strike": 22300.0, "reason": "b"},
    ]
    real = rl._append_jsonl_lines
    calls: list[int] = []

    def counting(path, lines):
        calls.append(len(lines))
        return real(path, lines)

    with patch("app.services.radar_learning._append_jsonl_lines", side_effect=counting):
        assert rl.record_funnel_state({}, skipped, now=NOW) == 2
    assert calls == [1, 2]
    assert {r["reason"] for r in _funnel_rows()} == {"selector_reject", "a", "b"}


def test_build_funnel_report_sees_deferred_rows(settings):
    async def on_loop():
        rl.record_funnel_gate_block("NIFTY", "PUT", 22250.0, "late_block", now=NOW)

    asyncio.run(on_loop())
    with patch("app.services.trade_store.get_day_detail", return_value={"trades": []}):
        rl.build_funnel_report(DATE)
    assert [r["reason"] for r in _funnel_rows()] == ["late_block"]


@pytest.mark.parametrize(
    "write",
    [
        lambda: rl.record_funnel_state(
            {}, [{"symbol": "NIFTY", "side": "CALL", "strike": 22250.0, "reason": "x"}], now=NOW
        ),
        lambda: rl.record_funnel_gate_block("NIFTY", "PUT", 22250.0, "y", now=NOW),
        lambda: rl.record_pipeline_event("SERVICE_START", source="test", now=NOW),
    ],
    ids=["funnel_state", "gate_block", "pipeline_event"],
)
def test_global_lock_not_held_during_file_io(settings, write):
    held: list[bool] = []
    real = rl._append_jsonl_lines

    def probe(path, lines):
        result: list[bool] = []

        def other():
            got = rl._lock.acquire(blocking=False)
            if got:
                rl._lock.release()
            result.append(got)

        t = threading.Thread(target=other)
        t.start()
        t.join()
        held.append(not result[0])
        return real(path, lines)

    with patch("app.services.radar_learning._append_jsonl_lines", side_effect=probe):
        write()
    assert held and not any(held)


def _blocking_section(seconds: float) -> None:
    time.sleep(seconds)


def test_watchdog_records_blocked_loop_stack_and_exits(tmp_path):
    exits: list[int] = []
    s = SimpleNamespace(trade_store_dir=str(tmp_path))

    async def main():
        loop_watchdog.start_loop_watchdog(
            stale_seconds=2.4,
            check_seconds=0.1,
            beat_interval_seconds=0.05,
            grace_seconds=5.0,
            exit_fn=exits.append,
        )
        await asyncio.sleep(0.2)
        _blocking_section(3.0)
        await asyncio.sleep(0.1)

    with patch("app.config.get_settings", return_value=s):
        try:
            asyncio.run(main())
        finally:
            loop_watchdog.stop_loop_watchdog()
        stalls = loop_watchdog.recent_stalls()

    assert exits == [1]
    assert [st["fatal"] for st in stalls] == [True, False]
    assert any("_blocking_section" in line for line in stalls[0]["stack"])
    assert any("_blocking_section" in line for line in stalls[1]["stack"])
    status = loop_watchdog.watchdog_status()["lastStall"]
    assert status["fatal"] is True and len(status["stack"]) <= 8
