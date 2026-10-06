"""ELITE near-ATM index rip waives stale first-lift v3 near-miss."""

from unittest.mock import MagicMock

from app.engines.rally_capture import (
    elite_near_atm_index_rip_first_lift_waive,
    explosion_near_miss_waive,
)


def _settings():
    s = MagicMock()
    s.elite_near_atm_index_rip_waive_enabled = True
    s.elite_near_atm_index_rip_min_score = 95.0
    s.elite_near_atm_index_rip_max_strike_steps = 2.0
    s.elite_near_atm_index_rip_min_move_pct = 25.0
    s.live_entry_best_trade_capture_waives_near_miss = False
    return s


def test_elite_near_atm_index_rip_waive_ok():
    alert = {
        "tier": "ELITE",
        "explosionScore": 100.0,
        "strikeStepsFromAtm": 1.0,
        "moneyness": "OTM",
        "dailyMovePct": 38.0,
        "ictFirstLift": True,
        "indexMomAlign": True,
        "velocity3s": 0.0,
    }
    assert elite_near_atm_index_rip_first_lift_waive(alert, settings=_settings()) is True
    assert explosion_near_miss_waive(alert, settings=_settings()) is True


def test_elite_near_atm_index_rip_blocks_deep_itm():
    alert = {
        "tier": "ELITE",
        "explosionScore": 100.0,
        "strikeStepsFromAtm": 1.0,
        "moneyness": "ITM",
        "dailyMovePct": 38.0,
        "ictFirstLift": True,
        "indexMomAlign": True,
    }
    assert elite_near_atm_index_rip_first_lift_waive(alert, settings=_settings()) is False
