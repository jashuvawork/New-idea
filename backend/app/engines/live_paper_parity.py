"""Paper book vs live execution — gates must match; only broker plumbing differs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings

# ``enable_live_trading`` allowed outside entry/exit gate logic (broker + HUD only).
_ENABLE_LIVE_ALLOWLIST: tuple[str, ...] = (
    "app/engines/auto_trader.py",
    "app/engines/capital_allocator.py",
    "app/engines/chop_live_guards.py",
    "app/engines/live_paper_parity.py",
    "app/engines/open_setup_policy.py",
    "app/engines/risk_engine.py",
    "app/engines/risk_stops.py",
    "app/engines/session_close_guard.py",
    "app/services/upstox.py",
    "app/services/upstox_trade_manager.py",
    "app/routers/health.py",
    "app/routers/execution.py",
    "app/config.py",
)

# Settings that must match paper/Oct1 book when ``live_match_paper_book`` (template pins these).
PAPER_BOOK_LIVE_PARITY_FIELDS: dict[str, Any] = {
    "live_hold_to_structural_sl": False,
    "use_upstox_capital_for_sizing": False,
    "live_early_fail_exit_enabled": False,
    "chop_live_early_fail_exit_enabled": False,
    "live_best_trades_only_enabled": False,
    "worst_day_blocks_live": False,
    "live_match_paper_book": True,
}


def is_live_execution(settings: Any = None) -> bool:
    settings = settings or get_settings()
    return bool(
        getattr(settings, "enable_live_trading", False)
        and getattr(settings, "auto_trading_enabled", True)
    )


def uses_paper_live_broker_sim(settings: Any = None) -> bool:
    settings = settings or get_settings()
    return (
        bool(getattr(settings, "paper_live_parity_enabled", False))
        and bool(getattr(settings, "paper_simulate_broker_orders", False))
        and not is_live_execution(settings)
    )


def paper_book_entry_fill_slippage_applies(settings: Any = None) -> bool:
    """Lot sizing uses paper slippage on live too (broker fill price is still real)."""
    settings = settings or get_settings()
    if not bool(getattr(settings, "paper_slippage_enabled", True)):
        return False
    if uses_paper_live_broker_sim(settings):
        return True
    if is_live_execution(settings):
        return bool(getattr(settings, "live_match_paper_book", True))
    return bool(getattr(settings, "paper_trading", True))


def verify_paper_book_live_settings(settings: Any = None) -> tuple[bool, list[str]]:
    settings = settings or get_settings()
    if not bool(getattr(settings, "live_match_paper_book", True)):
        return True, []
    drift: list[str] = []
    for key, expected in PAPER_BOOK_LIVE_PARITY_FIELDS.items():
        if key == "live_match_paper_book":
            continue
        actual = getattr(settings, key, None)
        if isinstance(expected, bool):
            ok = bool(actual) == expected
        else:
            ok = actual == expected
        if not ok:
            drift.append(f"{key}={actual!r} expected {expected!r}")
    return (len(drift) == 0, drift)


def scan_enable_live_outside_allowlist(backend_root: Path | None = None) -> list[str]:
    """Return engine paths that reference enable_live_trading outside the allowlist."""
    root = backend_root or Path(__file__).resolve().parents[2]
    app = root / "app"
    pattern = re.compile(r"enable_live_trading")
    violations: list[str] = []
    for path in sorted(app.rglob("*.py")):
        rel = path.relative_to(app.parent).as_posix()
        if not pattern.search(path.read_text(encoding="utf-8")):
            continue
        if rel in _ENABLE_LIVE_ALLOWLIST:
            continue
        violations.append(rel)
    return violations


def live_paper_parity_status(settings: Any = None) -> dict[str, Any]:
    settings = settings or get_settings()
    aligned, drift = verify_paper_book_live_settings(settings)
    scan = scan_enable_live_outside_allowlist()
    return {
        "liveMatchPaperBook": bool(getattr(settings, "live_match_paper_book", True)),
        "settingsAligned": aligned,
        "settingsDrift": drift,
        "entrySlippageForSizing": paper_book_entry_fill_slippage_applies(settings),
        "enableLiveAllowlistViolations": scan,
        "note": (
            "Gates (selector, pretrade, open setup, live_entry_score, chart) do not branch on "
            "enable_live_trading. Live-only code = broker orders, adoption, capital refresh. "
            "Chop-live entry blocks apply on chop days only."
        ),
    }
