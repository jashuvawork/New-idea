"""Replay settings override + seeded session pause proof."""

from pathlib import Path

import pytest

from app.config import Settings, get_settings, reset_settings_for_tests, set_settings_override

_SEP02_ARCHIVE = Path("/tmp/eod_audit_archives/radar-2026-09-02.zip")


def test_settings_override_routes_get_settings():
    base = get_settings()
    custom = Settings(**{**base.model_dump(), "session_loss_pause_enabled": True})
    set_settings_override(custom)
    try:
        assert get_settings().session_loss_pause_enabled is True
    finally:
        set_settings_override(None)


def test_seeded_loss_triggers_session_pause():
    """Unit proof: replay seed path arms large_loss_pause without premium tape."""
    from app.engines.chop_day_guards import (
        record_session_trade_close,
        reset_session_guards,
        session_pause_active,
    )

    base = get_settings()
    custom = Settings(
        **{
            **base.model_dump(),
            "session_loss_pause_enabled": True,
            "chop_day_guards_enabled": True,
        }
    )
    set_settings_override(custom)
    try:
        reset_session_guards()
        record_session_trade_close(-15_042.0)
        paused, reason = session_pause_active()
        assert paused is True
        assert reason.startswith("large_loss_pause")
    finally:
        set_settings_override(None)


@pytest.mark.skipif(
    not _SEP02_ARCHIVE.is_file(),
    reason="Sep 2 radar archive not present (integration only)",
)
def test_seeded_loss_triggers_pause_in_replay():
    from app.engines.chop_day_guards import reset_session_guards
    from app.engines.eod_local_base_replay import replay_local_base_day

    base = Settings()
    base.radar_archive_dir = "/tmp/eod_audit_archives"
    base.trade_store_dir = "/tmp/eod_audit_archives/trades"
    base.eod_replay_live_session_gates_enabled = True
    base.session_loss_pause_enabled = True
    base.session_large_loss_pause_bypass_enabled = False

    reset_session_guards()
    report = replay_local_base_day(
        "2026-09-02",
        settings=base,
        window_start="13:00:00",
        window_end="13:05:00",
        side_filter="CALL",
        seed_session_loss_inr=15_042.0,
    )
    assert report.get("status") == "ok"
    gates = report.get("gateStats") or {}
    pause_hits = sum(
        int(v)
        for k, v in gates.items()
        if str(k).startswith("large_loss_pause_")
        and str(k) != "large_loss_pause_bypass_active"
    )
    assert pause_hits > 0
