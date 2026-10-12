"""Full live ↔ paper parity flag."""

from unittest.mock import MagicMock, patch

from app.engines.capital_allocator import should_use_live_broker_capital
from app.engines.live_paper_parity import (
    live_paper_parity_active,
    live_paper_profile_ok,
    live_paper_profile_summary,
)
from app.engines.risk_stops import live_hold_to_structural_sl


def test_live_paper_parity_active_from_either_flag():
    s = MagicMock(live_paper_parity_enabled=True, live_trade_selection_parity_with_paper=False)
    assert live_paper_parity_active(s) is True
    s2 = MagicMock(live_paper_parity_enabled=False, live_trade_selection_parity_with_paper=True)
    assert live_paper_parity_active(s2) is True


def test_should_not_size_from_broker_margin_under_parity():
    s = MagicMock(
        live_paper_parity_enabled=True,
        use_upstox_capital_for_sizing=True,
        enable_live_trading=True,
    )
    with patch("app.engines.live_paper_parity.live_paper_parity_active", return_value=True):
        assert should_use_live_broker_capital() is False


def test_live_paper_profile_ok_matches_oct_overlay():
    s = MagicMock(
        live_paper_parity_enabled=True,
        live_best_trades_only_enabled=False,
        worst_day_blocks_live=False,
        live_hold_to_structural_sl=False,
        sep917_live_checklist_enforcement_enabled=False,
        sep917_legacy_profile_enabled=True,
        fallback_capital_inr=200_000,
        use_upstox_capital_for_sizing=False,
        enable_live_trading=True,
    )
    with patch(
        "app.engines.live_paper_parity.should_use_live_broker_capital_for_summary",
        return_value=False,
    ):
        ok, issues = live_paper_profile_ok(s)
    assert ok is True
    assert issues == []


def test_live_paper_profile_ok_accepts_150k_book():
    s = MagicMock(
        live_paper_parity_enabled=True,
        live_best_trades_only_enabled=False,
        worst_day_blocks_live=False,
        live_hold_to_structural_sl=False,
        sep917_live_checklist_enforcement_enabled=False,
        sep917_legacy_profile_enabled=True,
        fallback_capital_inr=150_000,
        use_upstox_capital_for_sizing=False,
        enable_live_trading=True,
    )
    with patch(
        "app.engines.live_paper_parity.should_use_live_broker_capital_for_summary",
        return_value=False,
    ):
        ok, issues = live_paper_profile_ok(s)
    assert ok is True
    assert issues == []


def test_sizes_from_paper_book_false_on_50k():
    s = MagicMock(
        live_paper_parity_enabled=True,
        live_trade_selection_parity_with_paper=False,
        enable_live_trading=True,
        auto_trading_enabled=True,
        october_frozen_profile_enabled=True,
        fallback_capital_inr=50_000,
        max_sizing_capital_inr=50_000,
        oct_paper_reference_capital_inr=149_000.0,
        oct_paper_first_lift_negative_velocity_waiver_enabled=True,
        oct_paper_peak_keep_exit_parity_enabled=True,
        oct_paper_exec_strict_bypass_enabled=True,
        live_paper_parity_pad_entry_guard_enabled=True,
        live_paper_parity_max_session_range_position=0.52,
    )
    with patch(
        "app.engines.live_paper_parity.should_use_live_broker_capital_for_summary",
        return_value=False,
    ):
        summary = live_paper_profile_summary(s)
    assert summary["sizesFromPaperBook"] is False
    assert summary["bookMatchesOctPaperReferenceLots"] is False
    assert summary["octPaperBehaviorParity"]["negativeVelocityWaiver"] is True


def test_live_hold_to_structural_sl_off_under_parity():
    s = MagicMock(
        enable_live_trading=True,
        auto_trading_enabled=True,
        live_hold_to_structural_sl=True,
        live_paper_parity_enabled=True,
        live_trade_selection_parity_with_paper=False,
    )
    with patch("app.engines.live_paper_parity.live_paper_parity_active", return_value=True):
        assert live_hold_to_structural_sl(s) is False
