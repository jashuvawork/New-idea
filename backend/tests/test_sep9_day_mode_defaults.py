"""Production defaults — symmetric capture book + audit session discipline (09:45, chop stand-aside)."""

from app.config import Settings


def test_sep9_symmetric_profile_defaults():
    s = Settings()
    assert s.symmetric_best_trade_capture_enabled is True
    assert s.elite_call_max_local_base_pct == 0.0
    assert s.elite_call_chop_shallow_block_enabled is True
    assert s.chop_rally_structure_bypass_enabled is True
    assert s.expiry_cycle_local_base_enabled is True
    assert s.expiry_worst_pe_structure_bypass_enabled is True
    assert s.expiry_worst_ce_structure_bypass_enabled is True
    assert s.put_slide_unlock_enabled is True
    assert s.ce_win_pe_mirror_enabled is True
    assert s.put_at_base_best_trade_enabled is True


def test_audit_session_discipline_defaults():
    s = Settings()
    assert s.session_side_alignment_enabled is True
    assert s.entry_earliest_minute == 45
    assert s.explosion_entry_earliest_minute == 45
    assert s.top_trades_only_near_base_waives_chop is False
    assert s.top_trades_only_ce_at_base_waives_chop is False
    assert s.top_trades_only_pe_at_base_waives_chop is False
    assert s.call_rally_unlock_waive_chop_shallow is False
    assert s.pe_win_ce_mirror_waive_chop_shallow is False


def test_sep21_soft_blockers_still_off_by_default():
    s = Settings()
    assert s.symmetric_chop_counter_trend_guard_enabled is False
    assert s.chop_post_win_afternoon_block_enabled is True
    assert s.plain_chop_afternoon_standdown_enabled is True


def test_post_sep17_hard_gates_off_for_sep9_17_profile():
    """Production defaults match Sep 9–17 capture (#618, #639, #652, #653–#655, WORST BREAKOUT_ONLY)."""
    s = Settings()
    assert s.top_trades_only_strict_enabled is False
    assert s.sep09_intent_enforcement_enabled is False
    assert s.sep917_live_checklist_enforcement_enabled is False
    assert s.premium_post_spike_dump_guard_enabled is False
    assert s.explosion_late_reentry_block_enabled is False
    assert s.worst_day_breakout_only_enabled is False
    assert s.worst_day_block_building_ict is False


def test_sep917_legacy_profile_defaults():
    """Sep 9–17 full stack — ATM/ITM ₹18–350, cheap OTM off, FTV book relaxed."""
    s = Settings()
    assert s.sep917_legacy_profile_enabled is True
    assert s.max_option_premium_inr == 350.0
    assert s.explosion_max_premium_inr == 350.0
    assert s.best_trade_cheap_base_rank_priority_enabled is False
    assert s.explosion_shallow_otm_entry_enabled is False
    assert s.near_base_session_capture_enabled is False
    assert s.put_slide_unlock_waive_expiry_otm is False
    assert s.call_rally_unlock_waive_expiry_otm is False
    assert s.ftv_elite_top_only_enabled is False
    assert s.top_moments_only_enabled is False
    assert s.open_premium_shallow_otm_all_sessions_enabled is False
    assert s.explosion_open_cheap_rip_min_premium_inr == 18.0