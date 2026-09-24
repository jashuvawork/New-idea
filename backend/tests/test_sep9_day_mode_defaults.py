"""Production defaults — Sep 9–17 symmetric capture; Sep21+ blockers off."""

from app.config import Settings


def test_sep9_symmetric_profile_defaults():
    s = Settings()
    assert s.symmetric_best_trade_capture_enabled is True
    assert s.elite_call_max_local_base_pct == 0.0
    assert s.elite_call_chop_shallow_block_enabled is False
    assert s.chop_rally_structure_bypass_enabled is True
    assert s.expiry_cycle_local_base_enabled is True
    assert s.expiry_worst_pe_structure_bypass_enabled is True
    assert s.expiry_worst_ce_structure_bypass_enabled is True
    assert s.put_slide_unlock_enabled is True
    assert s.put_slide_unlock_waive_expiry_otm is True
    assert s.ce_win_pe_mirror_enabled is True
    assert s.put_at_base_best_trade_enabled is True


def test_sep21_blockers_still_off_by_default():
    s = Settings()
    assert s.session_side_alignment_enabled is False
    assert s.symmetric_chop_counter_trend_guard_enabled is False
    assert s.chop_post_win_afternoon_block_enabled is False


def test_sep9_near_base_chop_waiver_still_on():
    """#626 Sep 9–17 near-base ELITE waiver — kept on."""
    s = Settings()
    assert s.top_trades_only_near_base_waives_chop is True
