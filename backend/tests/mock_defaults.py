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
