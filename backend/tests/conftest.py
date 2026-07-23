"""Shared pytest fixtures — isolate module-level state between tests.

Several engines keep process-level globals (detector history, cooldown maps, the
last composer brief, whipsaw/reentry timestamps, session gates). If a test leaves
one set, it silently changes the outcome of a later test in a different file —
producing order-dependent "flaky" failures (e.g. a leaked composer stand-down
brief later reads as `composer_stand_down`). Reset all of them around every test
so the suite result is stable regardless of collection order.
"""

import pytest


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
    from app.engines.capital_allocator import reset_session_profit_gate

    for fn in (
        reset_detector_state_for_tests,
        reset_confidence_hold_state,
        reset_monitor_state,
        reset_symbol_cooldowns,
        reset_whipsaw_guards,
        reset_directional_lock,
        reset_session_guards,
        reset_session_profit_gate,
    ):
        _safe(fn)

    from app.engines.explosion_profit import _explosion_stop_at, _explosion_stop_cooldown_sec

    _explosion_stop_at.clear()
    _explosion_stop_cooldown_sec.clear()

    from app.engines import expiry_day_guards

    expiry_day_guards._expiry_session_active = False


@pytest.fixture(autouse=True)
def _reset_module_globals_between_tests():
    _reset_all_engine_globals()
    yield
    _reset_all_engine_globals()
