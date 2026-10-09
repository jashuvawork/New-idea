"""Gap-open days — high-score ELITE legs must survive explosionAlerts cap (Oct 9 RCA)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.engines.explosion_detector import select_explosion_events_for_selector


def _ev(tier: str, score: float, strike: float, side: str = "CALL") -> SimpleNamespace:
    return SimpleNamespace(
        tier=tier,
        explosion_score=score,
        strike=strike,
        side=side,
    )


def test_force_includes_elite_above_min_score_after_cap():
    settings = MagicMock()
    settings.explosion_alerts_selector_cap = 25
    settings.explosion_alerts_open_window_selector_cap = 45
    settings.explosion_alerts_force_include_min_score = 90.0
    ordered = [_ev("ELITE", 100.0 - i * 0.1, 22000 + i * 50) for i in range(40)]
    out = select_explosion_events_for_selector(ordered, settings)
    assert len(out) >= 26
    assert any(getattr(e, "strike") == 22000 + 25 * 50 for e in out)
    low = _ev("EXPLODING", 50.0, 99999.0)
    ordered2 = ordered + [low]
    out2 = select_explosion_events_for_selector(ordered2, settings)
    assert not any(getattr(e, "strike") == 99999.0 for e in out2)
