"""Regression: live arming must not fork entry/exit gates away from paper."""

from pathlib import Path

from app.config import Settings
from app.engines.live_paper_parity import (
    PAPER_BOOK_LIVE_PARITY_FIELDS,
    live_paper_parity_status,
    paper_book_entry_fill_slippage_applies,
    scan_enable_live_outside_allowlist,
    verify_paper_book_live_settings,
)


def test_paper_book_settings_defaults_aligned():
    ok, drift = verify_paper_book_live_settings(Settings())
    assert ok, drift


def test_live_entry_slippage_sizing_when_match_paper_book():
    live = Settings(
        enable_live_trading=True,
        auto_trading_enabled=True,
        paper_trading=False,
        paper_slippage_enabled=True,
        live_match_paper_book=True,
    )
    assert paper_book_entry_fill_slippage_applies(live) is True


def test_enable_live_only_in_allowlisted_modules():
    root = Path(__file__).resolve().parents[2]
    violations = scan_enable_live_outside_allowlist(root)
    assert violations == [], f"enable_live_trading in non-allowlisted: {violations}"


def test_live_paper_parity_status_clean():
    status = live_paper_parity_status(Settings())
    assert status["settingsAligned"] is True
    assert status["enableLiveAllowlistViolations"] == []
    assert status["entrySlippageForSizing"] is True


def test_frozen_paper_book_live_fields_match_settings():
    settings = Settings()
    for key, expected in PAPER_BOOK_LIVE_PARITY_FIELDS.items():
        if key == "live_match_paper_book":
            continue
        assert getattr(settings, key) == expected, key
