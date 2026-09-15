"""Sep-9-style best trade policy — near-base max lots, block deep chop chase."""

from unittest.mock import MagicMock

from app.engines.best_trade_policy import (
    best_trade_chop_deep_chase_blocked,
    best_trade_near_base_assessment,
    elite_base_setup_allowed,
    timing_allows_best_trade_full_size,
)
from tests.mock_defaults import settings_mock


def test_near_base_ftv_allows_cold_base_max_lots():
    s = settings_mock()
    timing = {"assessment": "COLD_BASE", "structuredColdBase": True}
    assessment = {
        "eliteScore": 95.0,
        "localBasePct": 12.0,
        "setup": "FTV",
    }
    assert best_trade_near_base_assessment(assessment, settings=s)
    assert timing_allows_best_trade_full_size(timing, assessment, settings=s)


def test_deep_itm_chop_trap_blocked():
    s = settings_mock()
    cand = MagicMock(mode="explosion", premium=242.42)
    assessment = {
        "eliteScore": 95.5,
        "localBasePct": 16.4,
        "setup": "V",
        "dayMode": "EXPIRY WORST",
    }
    blocked, reason = best_trade_chop_deep_chase_blocked(
        cand,
        {"fakeExplosionTrap": True},
        assessment,
        day_mode="EXPIRY WORST",
        settings=s,
    )
    assert blocked is True
    assert reason == "best_trade_block_chop_deep_itm_chase"


def test_cheap_near_base_not_deep_chase_blocked():
    s = settings_mock()
    cand = MagicMock(mode="explosion", premium=52.0)
    assessment = {
        "eliteScore": 92.0,
        "localBasePct": 11.0,
        "setup": "FTV",
        "dayMode": "EXPIRY WORST",
    }
    blocked, _ = best_trade_chop_deep_chase_blocked(
        cand,
        {"fakeExplosionTrap": True},
        assessment,
        day_mode="EXPIRY WORST",
        settings=s,
    )
    assert blocked is False


def test_elite_base_setup_allows_ftv_not_explosive_chase():
    s = settings_mock(elite_trade_v_rip_only_enabled=False)
    assert elite_base_setup_allowed("FTV", settings=s) is True
    assert elite_base_setup_allowed("V", settings=s) is True
    assert elite_base_setup_allowed("EXPLOSIVE", settings=s) is False
