"""Production defaults — post–Sep17 stack off; core day-mode labels unchanged."""

from app.config import Settings


def test_post_sep17_stack_disabled_by_default():
    s = Settings()
    assert s.session_side_alignment_enabled is False
    assert s.symmetric_best_trade_capture_enabled is False
    assert s.symmetric_chop_counter_trend_guard_enabled is False
    assert s.chop_post_win_afternoon_block_enabled is False
    assert s.expiry_worst_pe_structure_bypass_enabled is False
    assert s.expiry_worst_ce_structure_bypass_enabled is False
    assert s.chop_rally_structure_bypass_enabled is False
    assert s.expiry_cycle_local_base_enabled is False


def test_sep9_near_base_chop_waiver_still_on():
    """#626 Sep 9–17 near-base ELITE waiver — kept on."""
    s = Settings()
    assert s.top_trades_only_near_base_waives_chop is True
