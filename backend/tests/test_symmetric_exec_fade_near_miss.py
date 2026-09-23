"""Symmetric CE/PE — exec premium fade + explosion near-miss at structural base."""

from app.config import Settings
from app.engines.best_trade_policy import (
    symmetric_near_base_premium_fade_bypass,
    symmetric_structural_near_miss_waive,
)
from app.engines.winner_entry_guards import premium_fading_blocks_entry


def test_symmetric_premium_fade_bypass_early_pad_at_base(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "symmetric_best_trade_capture_enabled", True)
    s = Settings()
    alert = {
        "tier": "ELITE",
        "localBaseMovePct": 12.0,
        "earlyRadarPadCapture": True,
    }
    assert symmetric_near_base_premium_fade_bypass(alert, settings=s) is True
    blocked, reason = premium_fading_blocks_entry(
        premium_momentum_3s=-0.4,
        premium_momentum_5s=-0.3,
        explosion_event=type("E", (), {"tier": "ELITE", "daily_move_pct": 12.0})(),
        pad_lane_bypass=True,
        symmetric_near_base_bypass=True,
    )
    assert blocked is False
    assert reason in ("symmetric_near_base_shallow_fade_ok", "pad_lane_shallow_fade_ok")


def test_symmetric_near_miss_waive_building_rip(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "symmetric_best_trade_capture_enabled", True)
    s = Settings()
    alert = {
        "tier": "BUILDING",
        "localBaseMovePct": 8.0,
        "buildingRipReady": True,
    }
    assert symmetric_structural_near_miss_waive(alert, settings=s) is True
