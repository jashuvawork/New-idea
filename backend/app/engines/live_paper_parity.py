"""When armed for ₹2L live, match paper trading rules — only execution differs (real broker)."""

from __future__ import annotations

from typing import Any


def live_paper_parity_active(settings: Any | None = None) -> bool:
    from app.config import get_settings

    s = settings or get_settings()
    return bool(
        getattr(s, "live_paper_parity_enabled", False)
        or getattr(s, "live_trade_selection_parity_with_paper", False)
    )
