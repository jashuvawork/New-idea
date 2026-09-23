"""Thread-local replay clock — EOD replay must not patch live session time helpers."""

from __future__ import annotations

import contextvars
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

_replay_minutes_fn: contextvars.ContextVar[Callable[[], int] | None] = contextvars.ContextVar(
    "replay_minutes_fn",
    default=None,
)


def ist_minutes_now() -> int:
    """IST minutes since midnight — live wall clock unless replay override is set in this thread."""
    fn = _replay_minutes_fn.get()
    if fn is not None:
        return fn()
    now = datetime.now(IST)
    return now.hour * 60 + now.minute


def install_replay_minutes(fn: Callable[[], int]) -> contextvars.Token:
    return _replay_minutes_fn.set(fn)


def restore_replay_minutes(token: contextvars.Token) -> None:
    _replay_minutes_fn.reset(token)
