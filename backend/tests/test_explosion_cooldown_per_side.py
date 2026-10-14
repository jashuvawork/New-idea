"""Per-side explosion cooldown (Oct 13 NIFTY: a PE stop froze every CE for 180s)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.config import Settings
from app.engines import explosion_profit as ep
from app.models.schemas import Side

OPPOSITE = {Side.CALL: Side.PUT, Side.PUT: Side.CALL}


def _settings(enabled: bool) -> Settings:
    return Settings(explosion_cooldown_per_side_enabled=enabled, explosion_reentry_cooldown_seconds=180)


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_stop_cools_only_its_own_side(side):
    s = _settings(True)
    with patch.object(ep, "get_settings", lambda: s):
        ep.record_explosion_stop("NIFTY", side=side)
        assert ep.explosion_in_cooldown("NIFTY", side) is True
        assert 170 <= ep.cooldown_remaining_seconds("NIFTY", side) <= 180
        assert ep.explosion_in_cooldown("NIFTY", OPPOSITE[side]) is False
        assert ep.cooldown_remaining_seconds("NIFTY", OPPOSITE[side]) == 0
        assert ep.explosion_in_cooldown("SENSEX", side) is False


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_legacy_stop_cools_whole_index(side):
    s = _settings(False)
    with patch.object(ep, "get_settings", lambda: s):
        ep.record_explosion_stop("NIFTY", side=side)
        assert ep.explosion_in_cooldown("NIFTY", side) is True
        assert ep.explosion_in_cooldown("NIFTY", OPPOSITE[side]) is True
        assert ep.explosion_in_cooldown("NIFTY") is True


@pytest.mark.parametrize("side", [Side.CALL, Side.PUT])
def test_custom_cooldown_is_per_side(side):
    s = _settings(True)
    with patch.object(ep, "get_settings", lambda: s):
        ep.record_explosion_stop("NIFTY", cooldown_seconds=300, side=side)
        assert ep.cooldown_remaining_seconds("NIFTY", side) > 290
        ep.record_explosion_stop("NIFTY", side=OPPOSITE[side])
        assert ep.cooldown_remaining_seconds("NIFTY", side) > 290
        assert ep.cooldown_remaining_seconds("NIFTY", OPPOSITE[side]) <= 180


def test_flag_off_by_default_and_on_in_frozen_overlay():
    from pathlib import Path

    assert Settings().explosion_cooldown_per_side_enabled is False
    overlay = Path(__file__).resolve().parents[2] / "deploy" / "env.october-frozen.overlay"
    assert "EXPLOSION_COOLDOWN_PER_SIDE_ENABLED=true" in overlay.read_text()
