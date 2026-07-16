"""Shared pytest fixtures — isolate module-level detector state between tests."""

import pytest


@pytest.fixture(autouse=True)
def _reset_module_globals_between_tests():
    from app.config import get_settings
    from app.engines.explosion_detector import reset_detector_state_for_tests
    from app.engines.confidence_hold import reset_confidence_hold_state
    from app.engines.explosion_profit import _explosion_stop_at, _explosion_stop_cooldown_sec

    get_settings.cache_clear()
    reset_detector_state_for_tests()
    reset_confidence_hold_state()
    _explosion_stop_at.clear()
    _explosion_stop_cooldown_sec.clear()

    from app.engines import expiry_day_guards

    expiry_day_guards._expiry_session_active = False

    yield

    get_settings.cache_clear()
    reset_detector_state_for_tests()
    reset_confidence_hold_state()
    _explosion_stop_at.clear()
    _explosion_stop_cooldown_sec.clear()
    expiry_day_guards._expiry_session_active = False
