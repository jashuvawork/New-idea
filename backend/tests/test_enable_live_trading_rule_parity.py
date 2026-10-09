"""Legacy live-only rule stacks stay off under Frozen Oct / paper parity live."""

from unittest.mock import MagicMock, patch

from app.engines.live_best_trades import live_best_trade_entry_blocked
from app.engines.live_paper_parity import (
    legacy_live_narrow_stack_active,
    trading_rules_match_paper,
)
from app.engines.worst_day_guard import worst_day_blocks_live
from app.models.schemas import AutoTraderState, Side, SymbolSnapshot
from tests.mock_defaults import settings_mock


def _frozen_live_parity_settings(**kwargs):
    return settings_mock(
        october_frozen_profile_enabled=True,
        enable_live_trading=True,
        auto_trading_enabled=True,
        live_paper_parity_enabled=True,
        live_trade_selection_parity_with_paper=True,
        legacy_live_narrow_stack_enabled=False,
        **kwargs,
    )


def test_trading_rules_match_paper_on_frozen_live():
    s = _frozen_live_parity_settings()
    assert trading_rules_match_paper(s) is True
    assert legacy_live_narrow_stack_active(s) is False


def test_live_best_trades_gate_inert_under_paper_rules():
    s = _frozen_live_parity_settings(live_best_trades_only_enabled=True)
    state = AutoTraderState()
    snap = MagicMock(spec=SymbolSnapshot)
    cand = MagicMock(mode="explosion", side=Side.CALL, explosion_event=None)
    blocked, reason, _ = live_best_trade_entry_blocked(cand, snap, state)
    assert blocked is False
    assert reason == "ok"


def test_worst_day_blocks_live_inert_under_paper_rules():
    s = _frozen_live_parity_settings(worst_day_blocks_live=True)
    state = AutoTraderState()
    snapshots = {"NIFTY": MagicMock(spec=SymbolSnapshot)}
    with patch("app.engines.worst_day_guard.identify_worst_day") as ident:
        ident.return_value = MagicMock(is_worst=True, to_dict=lambda: {})
        blocked, reason, _ = worst_day_blocks_live(state, snapshots)
    assert blocked is False
