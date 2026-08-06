"""Event-loop hang watchdog — exits frozen uvicorn for Docker restart."""

from __future__ import annotations

import asyncio
import time

from app import loop_watchdog as lw


def _reset():
    lw.stop_loop_watchdog()


def test_heartbeat_updates_age():
    _reset()
    exits: list[int] = []

    async def _run():
        lw.start_loop_watchdog(
            enabled=True,
            stale_seconds=30.0,
            check_seconds=0.5,
            beat_interval_seconds=0.1,
            grace_seconds=10.0,
            exit_fn=exits.append,
        )
        await asyncio.sleep(0.35)
        age = lw.last_beat_age_seconds()
        status = lw.watchdog_status()
        lw.stop_loop_watchdog()
        return age, status

    try:
        age, status = asyncio.run(_run())
        assert age is not None
        assert age < 1.0
        assert status["enabled"] is True
        assert status["threadAlive"] is True
        assert exits == []
    finally:
        _reset()


def test_stale_heartbeat_triggers_exit():
    _reset()
    exits: list[int] = []

    async def _run():
        lw.start_loop_watchdog(
            enabled=True,
            stale_seconds=0.4,
            check_seconds=0.1,
            beat_interval_seconds=0.05,
            grace_seconds=5.0,
            exit_fn=exits.append,
        )
        await asyncio.sleep(0.2)
        assert lw._beat_task is not None
        lw._beat_task.cancel()
        try:
            await lw._beat_task
        except asyncio.CancelledError:
            pass
        lw._beat_task = None

        deadline = time.monotonic() + 3.0
        while not exits and time.monotonic() < deadline:
            await asyncio.sleep(0.05)

    try:
        asyncio.run(_run())
        assert exits == [1]
    finally:
        _reset()


def test_disabled_watchdog_noop():
    _reset()
    exits: list[int] = []

    async def _run():
        lw.start_loop_watchdog(enabled=False, exit_fn=exits.append)
        status = lw.watchdog_status()
        await asyncio.sleep(0.2)
        age = lw.last_beat_age_seconds()
        return status, age

    try:
        status, age = asyncio.run(_run())
        assert status["enabled"] is False
        assert age is None
        assert exits == []
    finally:
        _reset()
