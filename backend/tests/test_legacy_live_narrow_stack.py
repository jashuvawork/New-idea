"""Legacy ₹10k live stack is opt-in and hard-off under Frozen October."""

from unittest.mock import MagicMock, patch

from app.engines.live_best_trades import live_best_trade_entry_blocked
from app.engines.live_paper_parity import legacy_live_narrow_stack_active
from app.models.schemas import AutoTraderState
from tests.mock_defaults import settings_mock


def test_legacy_stack_off_on_frozen_live_even_if_best_trades_env_true():
    s = settings_mock(
        october_frozen_profile_enabled=True,
        enable_live_trading=True,
        auto_trading_enabled=True,
        live_best_trades_only_enabled=True,
        legacy_live_narrow_stack_enabled=False,
    )
    assert legacy_live_narrow_stack_active(s) is False


def test_legacy_stack_on_only_with_explicit_flag():
    s = settings_mock(
        october_frozen_profile_enabled=False,
        enable_live_trading=True,
        auto_trading_enabled=True,
        legacy_live_narrow_stack_enabled=True,
        live_best_trades_only_enabled=True,
    )
    assert legacy_live_narrow_stack_active(s) is True


def test_live_best_gate_inert_without_legacy_stack():
    s = MagicMock()
    s.enable_live_trading = True
    s.auto_trading_enabled = True
    s.october_frozen_profile_enabled = True
    s.legacy_live_narrow_stack_enabled = False
    s.live_best_trades_only_enabled = True
    cand = MagicMock(mode="explosion", score=300.0)
    snap = MagicMock()
    with patch("app.engines.live_best_trades.get_settings", return_value=s):
        blocked, reason, _ = live_best_trade_entry_blocked(
            cand, snap, AutoTraderState(),
        )
    assert blocked is False
    assert reason == "ok"
