"""Frozen October profile — symmetric CE/PE deploy sign-off."""

from unittest.mock import patch

from app.engines.october_frozen_profile import (
    october_frozen_profile_active,
    october_frozen_profile_ok,
)
from tests.mock_defaults import settings_mock


def _frozen_settings():
    return settings_mock(
        october_frozen_profile_enabled=True,
        symmetric_best_trade_capture_enabled=True,
        index_rally_side_flip_enabled=True,
        directional_side_lock_enabled=True,
        sep917_legacy_profile_enabled=True,
        live_paper_parity_enabled=True,
        live_trade_selection_parity_with_paper=True,
        live_best_trades_only_enabled=False,
        worst_day_blocks_live=False,
        live_hold_to_structural_sl=False,
        top_moments_only_enabled=False,
        sep917_live_checklist_enforcement_enabled=False,
        live_paper_parity_pad_entry_guard_enabled=True,
        use_upstox_capital_for_sizing=False,
        enable_live_trading=False,
    )


def test_october_frozen_profile_ok_when_marker_and_symmetric_flags():
    s = _frozen_settings()
    assert october_frozen_profile_active(s) is True
    with patch(
        "app.engines.live_paper_parity.live_paper_parity_active",
        return_value=True,
    ):
        ok, issues = october_frozen_profile_ok(s)
    assert ok is True
    assert issues == []


def test_october_frozen_profile_fails_when_disabled():
    s = _frozen_settings()
    s.october_frozen_profile_enabled = False
    ok, issues = october_frozen_profile_ok(s)
    assert ok is False
    assert "october_frozen_profile_disabled" in issues


def test_october_frozen_profile_fails_live_best_trades_only():
    s = _frozen_settings()
    s.live_best_trades_only_enabled = True
    with patch(
        "app.engines.live_paper_parity.live_paper_parity_active",
        return_value=True,
    ):
        ok, issues = october_frozen_profile_ok(s)
    assert ok is False
    assert "live_best_trades_only_still_enabled" in issues


def test_october_frozen_profile_fails_without_index_rally_flip():
    s = _frozen_settings()
    s.index_rally_side_flip_enabled = False
    with patch(
        "app.engines.live_paper_parity.live_paper_parity_active",
        return_value=True,
    ):
        ok, issues = october_frozen_profile_ok(s)
    assert ok is False
    assert "index_rally_side_flip_disabled" in issues
