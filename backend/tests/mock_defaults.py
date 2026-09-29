"""Production-aligned test stubs — import these instead of hand-rolling MagicMock fields.

When production signatures or config defaults change, update Settings / DailyProfitGate
once here rather than chasing drift across dozens of test files (Sep03 #548 vs #549).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from app.config import Settings
from app.engines.capital_allocator import DailyProfitGate


def cheap_otm_stack_settings(**overrides: Any) -> Settings:
    """Opt-in cheap/shallow OTM + FTV stack (off under Sep 9–17 legacy production defaults)."""
    base = {
        "sep917_legacy_profile_enabled": False,
        "best_trade_cheap_base_rank_priority_enabled": True,
        "near_base_session_capture_enabled": True,
        "explosion_shallow_otm_entry_enabled": True,
        "explosion_shallow_otm_history_steps": 1,
        "ftv_elite_top_only_enabled": True,
    }
    base.update(overrides)
    return Settings(**base)


def post_sep17_stack_settings(**overrides: Any) -> Settings:
    """Opt-in flags for tests of #623–#631 (production defaults are off)."""
    base = {
        "session_side_alignment_enabled": True,
        "chop_day_require_side_alignment_enabled": True,
        "symmetric_best_trade_capture_enabled": True,
        "symmetric_chop_counter_trend_guard_enabled": True,
        "chop_post_win_afternoon_block_enabled": True,
        "fake_explosion_trap_chop_post_win_afternoon_enabled": True,
        "expiry_worst_pe_structure_bypass_enabled": True,
        "expiry_worst_ce_structure_bypass_enabled": True,
        "chop_rally_structure_bypass_enabled": True,
        "expiry_cycle_local_base_enabled": True,
    }
    base.update(overrides)
    return Settings(**base)


def settings_mock(**overrides: Any) -> MagicMock:
    """MagicMock whose attributes mirror live Settings defaults unless overridden."""
    base = Settings()
    mock = MagicMock()
    for name in base.model_fields:
        setattr(mock, name, getattr(base, name))
    for key, value in overrides.items():
        setattr(mock, key, value)
    return mock


def profit_gate_stub(**overrides: Any) -> SimpleNamespace:
    """Process-loop profit gate stub matching DailyProfitGate field names."""
    gate = DailyProfitGate()
    payload = {
        "newEntriesAllowed": gate.newEntriesAllowed,
        "dailyLossStopExpiryTopOnly": gate.dailyLossStopExpiryTopOnly,
        "status": gate.status,
        "message": gate.message,
        "to_dict": lambda: gate.to_dict(),
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)
