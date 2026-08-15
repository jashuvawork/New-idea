"""Shared pytest fixtures — isolate module-level state between tests.

Several engines keep process-level globals (detector history, cooldown maps, the
last composer brief, whipsaw/reentry timestamps, session gates). If a test leaves
one set, it silently changes the outcome of a later test in a different file —
producing order-dependent "flaky" failures (e.g. a leaked composer stand-down
brief later reads as `composer_stand_down`). Reset all of them around every test
so the suite result is stable regardless of collection order.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

_IST = ZoneInfo("Asia/Kolkata")
# Deterministic "wall clock" for the suite. get_market_phase() and the capture/
# session time-windows read app.services.upstox.datetime.now(IST); without a fixed
# clock the suite result depends on the time of day it runs (e.g. incomplete settings
# mocks only reach the live-market capture-window code between 09:15–15:30 IST and
# crash). Freeze to a weekday mid-session time so time-windows are consistent, and
# let any test that needs a different phase patch get_market_phase locally.
_FROZEN_NOW = datetime(2026, 8, 12, 16, 30, 0, tzinfo=_IST)  # Wed 16:30 IST — CLOSED


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return _FROZEN_NOW.astimezone(tz)
        return _FROZEN_NOW.replace(tzinfo=None)


def _reset_all_engine_globals() -> None:
    from app.config import get_settings

    get_settings.cache_clear()

    # Each reset is guarded so an import/signature change in one engine can't
    # disable isolation for all the others.
    def _safe(fn):
        try:
            fn()
        except Exception:
            pass

    from app.engines.explosion_detector import reset_detector_state_for_tests
    from app.engines.confidence_hold import reset_confidence_hold_state
    from app.engines.composer_market_monitor import reset_monitor_state
    from app.engines.symbol_cooldown import reset_symbol_cooldowns
    from app.engines.whipsaw_guards import reset_whipsaw_guards
    from app.engines.directional_lock import reset_directional_lock
    from app.engines.chop_day_guards import reset_session_guards
    from app.engines.capital_allocator import (
        reset_capital_for_tests,
        reset_session_profit_gate,
    )
    from app.engines.realtime_engine import reset_realtime_detector_state
    from app.engines.preorder_rejection_suppression import (
        reset_preorder_rejection_suppressions,
    )
    from app.services.radar_health import reset_health_for_tests
    from app.services.radar_learning import reset_learning_state_for_tests
    from app.services.upstox_trade_manager import (
        reset_upstox_trade_manager_cache_for_tests,
    )

    for fn in (
        reset_detector_state_for_tests,
        reset_confidence_hold_state,
        reset_monitor_state,
        reset_symbol_cooldowns,
        reset_whipsaw_guards,
        reset_directional_lock,
        reset_session_guards,
        reset_session_profit_gate,
        reset_capital_for_tests,
        reset_realtime_detector_state,
        reset_preorder_rejection_suppressions,
        reset_health_for_tests,
        reset_learning_state_for_tests,
        reset_upstox_trade_manager_cache_for_tests,
    ):
        _safe(fn)

    from app.engines.explosion_profit import _explosion_stop_at, _explosion_stop_cooldown_sec

    _explosion_stop_at.clear()
    _explosion_stop_cooldown_sec.clear()

    from app.engines import expiry_day_guards

    expiry_day_guards._expiry_session_active = False

    _safe(lambda: __import__("app.services.cvd_store", fromlist=["clear"]).clear())


@pytest.fixture(autouse=True)
def _freeze_market_clock(monkeypatch):
    """Freeze the market wall-clock so time-of-day never changes suite results.

    get_market_phase() (app/services/upstox.py) reads the module-level `datetime`;
    freezing it there makes every caller deterministic. Tests that need a specific
    phase still override get_market_phase locally.
    """
    monkeypatch.setattr("app.services.upstox.datetime", _FrozenDateTime, raising=False)
    yield


@pytest.fixture(autouse=True)
def _reset_module_globals_between_tests():
    _reset_all_engine_globals()
    yield
    _reset_all_engine_globals()
