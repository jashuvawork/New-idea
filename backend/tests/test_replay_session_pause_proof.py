"""Replay settings override + seeded session pause proof."""

from copy import deepcopy

import pytest

from app.config import Settings, get_settings, set_settings_override


def test_settings_override_routes_get_settings():
    base = get_settings()
    custom = Settings(**{**base.model_dump(), "session_loss_pause_enabled": True})
    set_settings_override(custom)
    try:
        assert get_settings().session_loss_pause_enabled is True
    finally:
        set_settings_override(None)


def test_seeded_loss_triggers_pause_in_replay():
    from app.engines.chop_day_guards import reset_session_guards, session_pause_active
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
    assert report.get("status") in ("ok", "no_tape")
    gates = report.get("gateStats") or {}
    pause_hits = sum(
        int(v)
        for k, v in gates.items()
        if str(k).startswith("large_loss_pause_")
        and str(k) != "large_loss_pause_bypass_active"
    )
    assert pause_hits > 0 or session_pause_active()[0]
