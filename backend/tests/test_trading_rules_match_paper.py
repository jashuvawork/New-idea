"""Live Frozen Oct mirrors paper sizing and skips live-only exit narrowings."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.engines.capital_allocator import should_use_live_broker_capital
from app.engines.chop_live_guards import chop_live_early_fail_exit_reason
from app.engines.live_best_trades import live_early_fail_exit_reason
from app.engines.live_paper_parity import entry_gates_match_paper, trading_rules_match_paper
from tests.mock_defaults import settings_mock


def _frozen_live_no_parity_env(**kwargs):
    return settings_mock(
        october_frozen_profile_enabled=True,
        enable_live_trading=True,
        auto_trading_enabled=True,
        live_paper_parity_enabled=False,
        live_trade_selection_parity_with_paper=False,
        use_upstox_capital_for_sizing=True,
        **kwargs,
    )


def test_entry_gates_and_trading_rules_frozen_live_without_parity_flags():
    s = _frozen_live_no_parity_env()
    assert entry_gates_match_paper(s) is True
    assert trading_rules_match_paper(s) is True


def test_frozen_live_sizes_from_paper_book_not_upstox():
    s = _frozen_live_no_parity_env()
    with patch("app.engines.capital_allocator.get_settings", return_value=s):
        assert should_use_live_broker_capital() is False


def test_paper_mode_trading_rules_match_when_frozen_oct():
    s = settings_mock(
        enable_live_trading=False,
        auto_trading_enabled=True,
        october_frozen_profile_enabled=True,
    )
    assert trading_rules_match_paper(s) is True


def test_paper_mode_without_frozen_oct_does_not_auto_match():
    s = settings_mock(
        enable_live_trading=False,
        auto_trading_enabled=True,
        october_frozen_profile_enabled=False,
        live_paper_parity_enabled=False,
    )
    assert trading_rules_match_paper(s) is False


def test_live_early_fail_disabled_when_trading_rules_match_paper():
    s = _frozen_live_no_parity_env(live_early_fail_exit_enabled=True)
    trade = SimpleNamespace(entryContext={"executionMode": "LIVE"})
    with patch("app.engines.live_best_trades.get_settings", return_value=s):
        reason = live_early_fail_exit_reason(
        trade,
        hold_seconds=60,
        best_points=0,
        pnl_points=-5,
        live_velocity_3s=0,
        )
    assert reason is None


def test_chop_live_early_fail_disabled_when_trading_rules_match_paper():
    s = _frozen_live_no_parity_env(chop_live_early_fail_exit_enabled=True)
    trade = SimpleNamespace(entryContext={"chopLiveGuard": True, "conflictFlags": []})
    with patch("app.engines.chop_live_guards.get_settings", return_value=s):
        reason = chop_live_early_fail_exit_reason(
        trade,
        hold_seconds=60,
        best_points=0,
        pnl_points=-5,
        live_velocity_3s=0,
        )
    assert reason is None
