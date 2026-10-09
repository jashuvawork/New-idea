#!/usr/bin/env python3
"""
CI guard: enable_live_trading must only appear in allowlisted modules.

New rule forks belong behind trading_rules_match_paper / legacy_live_* in
live_paper_parity.py — not new files keyed on bare enable_live_trading.

Run: python backend/scripts/check_enable_live_trading_rule_forks.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "backend" / "app"

# Modules allowed to reference enable_live_trading (execution, HUD, parity defs).
ALLOWLIST = frozenset(
    {
        "engines/live_paper_parity.py",
        "engines/execution_backend.py",
        "engines/auto_trader.py",
        "engines/chop_live_guards.py",
        "engines/worst_day_guard.py",
        "engines/live_best_trades.py",
        "engines/session_close_guard.py",
        "engines/capital_allocator.py",
        "config.py",
        "routers/health.py",
        "routers/execution.py",
        "services/upstox.py",
    }
)


def main() -> int:
    violations: list[str] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        rel = path.relative_to(APP_ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "enable_live_trading" not in text:
            continue
        if rel not in ALLOWLIST:
            violations.append(rel)
    if violations:
        print(
            "enable_live_trading found outside allowlist — use trading_rules_match_paper "
            "or add to ALLOWLIST only for execution/HUD:\n"
            + "\n".join(f"  - {v}" for v in violations),
            file=sys.stderr,
        )
        return 1
    print(f"OK: enable_live_trading allowlist ({len(ALLOWLIST)} modules)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
