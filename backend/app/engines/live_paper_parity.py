"""When armed for ₹2L live, match paper trading rules — only execution differs (real broker)."""

from __future__ import annotations

from typing import Any


def _strict_bool(value: Any, default: bool = False) -> bool:
    """Only real bools count — MagicMock attrs must not flip parity on in tests."""
    if isinstance(value, bool):
        return value
    return default


def live_paper_parity_active(settings: Any | None = None) -> bool:
    from app.config import get_settings

    s = settings or get_settings()
    return _strict_bool(getattr(s, "live_paper_parity_enabled", False)) or _strict_bool(
        getattr(s, "live_trade_selection_parity_with_paper", False)
    )
