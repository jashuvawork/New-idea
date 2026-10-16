"""Event-loop hang watchdog — exit so Docker restarts a frozen backend.

Aug6 outage: TCP:8000 stayed open but /health never answered (asyncio loop
blocked by sync work). Host cron watchdog did not recover in time. This
in-process watchdog updates a heartbeat from an asyncio task; a daemon thread
kills the process if the beat goes stale — Docker ``restart: unless-stopped``
brings the API back without waiting for cron.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_last_beat_mono: float = 0.0
_started: bool = False
_stop = threading.Event()
_thread: Optional[threading.Thread] = None
_beat_task: Optional[asyncio.Task] = None
_stale_seconds: float = 20.0
_exit_fn: Callable[[int], None] = os._exit


def last_beat_age_seconds() -> Optional[float]:
    if _last_beat_mono <= 0:
        return None
    return max(0.0, time.monotonic() - _last_beat_mono)


def watchdog_status() -> dict[str, Any]:
    age = last_beat_age_seconds()
    return {
        "enabled": _started,
        "staleSeconds": _stale_seconds,
        "lastBeatAgeSeconds": round(age, 3) if age is not None else None,
        "threadAlive": bool(_thread and _thread.is_alive()),
    }


def _watcher_loop(
    *,
    stale_seconds: float,
    check_seconds: float,
    grace_seconds: float,
) -> None:
    """Daemon thread — must not touch the asyncio loop."""
    deadline = time.monotonic() + max(1.0, grace_seconds)
    while not _stop.is_set():
        if _last_beat_mono > 0:
            break
        if time.monotonic() >= deadline:
            logger.error(
                "event_loop_watchdog: no heartbeat within %.0fs grace — exiting",
                grace_seconds,
            )
            _exit_fn(1)
            return
        _stop.wait(check_seconds)

    while not _stop.is_set():
        age = time.monotonic() - _last_beat_mono
        if age > stale_seconds:
            logger.error(
                "event_loop_watchdog: loop hung age=%.1fs (limit=%.1fs) — "
                "process exit for docker restart",
                age,
                stale_seconds,
            )
            _exit_fn(1)
            return
        _stop.wait(check_seconds)


async def _heartbeat_loop(interval_seconds: float) -> None:
    global _last_beat_mono
    while True:
        _last_beat_mono = time.monotonic()
        await asyncio.sleep(interval_seconds)


def start_loop_watchdog(
    *,
    enabled: bool = True,
    stale_seconds: float = 20.0,
    check_seconds: float = 2.0,
    beat_interval_seconds: float = 1.0,
    grace_seconds: float = 45.0,
    exit_fn: Optional[Callable[[int], None]] = None,
) -> None:
    """Start asyncio heartbeat + daemon killer thread."""
    global _started, _thread, _beat_task, _stale_seconds, _last_beat_mono, _exit_fn

    if not enabled:
        logger.info("event_loop_watchdog: disabled")
        return
    if _started:
        return

    if exit_fn is not None:
        _exit_fn = exit_fn
    else:
        _exit_fn = os._exit

    _stale_seconds = float(stale_seconds)
    _last_beat_mono = 0.0
    _stop.clear()
    _beat_task = asyncio.create_task(
        _heartbeat_loop(max(0.2, float(beat_interval_seconds))),
        name="event_loop_heartbeat",
    )
    _thread = threading.Thread(
        target=_watcher_loop,
        kwargs={
            "stale_seconds": float(stale_seconds),
            "check_seconds": max(0.5, float(check_seconds)),
            "grace_seconds": max(5.0, float(grace_seconds)),
        },
        name="event_loop_watchdog",
        daemon=True,
    )
    _thread.start()
    _started = True
    logger.info(
        "event_loop_watchdog: started stale=%.0fs check=%.1fs grace=%.0fs",
        stale_seconds,
        check_seconds,
        grace_seconds,
    )


def stop_loop_watchdog() -> None:
    """Stop heartbeat task and watcher thread (tests / shutdown)."""
    global _started, _thread, _beat_task, _last_beat_mono, _exit_fn

    _stop.set()
    if _beat_task is not None:
        _beat_task.cancel()
        _beat_task = None
    if _thread is not None and _thread.is_alive():
        _thread.join(timeout=2.0)
    _thread = None
    _started = False
    _last_beat_mono = 0.0
    _exit_fn = os._exit
