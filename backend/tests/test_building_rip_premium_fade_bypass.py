"""BUILDING rip + index helpers — shallow premium fade fill at execution."""

from app.config import Settings
from app.engines.building_ftv_gates import building_rip_premium_fade_bypass
from app.engines.winner_entry_guards import premium_fading_blocks_entry
from types import SimpleNamespace


def test_building_rip_premium_fade_bypass_on_helper_confirmed_alert():
    alert = {
        "tier": "EXPLODING",
        "ictBuildingRipReady": True,
        "indexHelpersConfirm": True,
        "buildingHelperBonus": 40.0,
        "buildingRipHelpersOk": True,
        "velocity3s": 2.0,
        "peakVelocity3s": 2.0,
    }
    assert building_rip_premium_fade_bypass(alert) is True
    event = SimpleNamespace(tier="EXPLODING", daily_move_pct=25.0)
    blocked, reason = premium_fading_blocks_entry(
        trade_score=85.0,
        premium_momentum_3s=-0.4,
        premium_momentum_5s=-0.8,
        explosion_event=event,
        building_rip_bypass=True,
    )
    assert blocked is False
    assert reason == "building_rip_shallow_fade_ok"
