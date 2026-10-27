"""Paper full #676 overlay — open/entry timing vs production template."""

from pathlib import Path

import pytest

from app.config import Settings

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "deploy/env.paper-676-full-session.overlay"
TEMPLATE = ROOT / "deploy/env.production.template"


def _parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key] = value
    return out


def test_full_session_overlay_has_0920_entry_and_0925_macro():
    env = _parse_env(OVERLAY)
    assert env["ENTRY_EARLIEST_MINUTE"] == "20"
    assert env["EXPLOSION_ENTRY_EARLIEST_MINUTE"] == "20"
    assert env["OPEN_SIDE_CONFIRMATION_START_MINUTE"] == "25"
    assert env["OPEN_SIDE_CONFIRMATION_MIN_MINUTES"] == "1"
    assert env["PAPER_676_ENTRY_CHOKE_ENABLED"] == "true"
    assert env["OCT_PAPER_REPLICA_ENABLED"] == "true"


def test_overlay_matches_template_open_clock():
    """Paper redeploy must not put the macro back at 09:15 or the first order at 09:16."""
    tpl = _parse_env(TEMPLATE)
    ovl = _parse_env(OVERLAY)
    assert tpl["ENTRY_EARLIEST_MINUTE"] == "20"
    assert ovl["ENTRY_EARLIEST_MINUTE"] == "20"
    assert tpl["OPEN_SIDE_CONFIRMATION_START_MINUTE"] == "25"
    assert ovl["OPEN_SIDE_CONFIRMATION_START_MINUTE"] == "25"


def test_full_session_overlay_pins_816_mega_tp_rung_exits():
    """Paper redeploy must not drift off #816 mega TP-rung / unified ladder defaults."""
    env = _parse_env(OVERLAY)
    assert env["UNIFIED_PROFIT_LADDER_ENABLED"] == "true"
    assert env["TP_RUNG_LADDER_EXIT_ENABLED"] == "true"
    assert env["TP_RUNG_LADDER_MEGA_FADE_MIN_GIVEBACK_POINTS"] == "12"
    assert env["TP_RUNG_LADDER_MEGA_HOT_DEFER_VELOCITY_3S"] == "4"
    assert env["TP_RUNG_LADDER_MEGA_DISABLE_BETWEEN_FADE_MIN_BEST_POINTS"] == "55"
    assert env["TP_RUNG_LADDER_MEGA_LADDER_FIRST_MIN_BEST_POINTS"] == "55"
    assert env["DAILY_PROFIT_STAGE_LOCKS_ENABLED"] == "true"


def test_settings_reflect_overlay_entry_and_open_side():
    s = Settings(
        entry_earliest_hour=9,
        entry_earliest_minute=20,
        explosion_entry_earliest_hour=9,
        explosion_entry_earliest_minute=20,
        open_side_confirmation_start_hour=9,
        open_side_confirmation_start_minute=25,
        open_side_confirmation_min_minutes=1,
        paper_676_entry_choke_enabled=True,
        oct_paper_replica_enabled=True,
        paper_trading=True,
        enable_live_trading=False,
    )
    assert f"{s.entry_earliest_hour:02d}:{s.entry_earliest_minute:02d}" == "09:20"
    assert (
        f"{s.open_side_confirmation_start_hour:02d}:"
        f"{s.open_side_confirmation_start_minute:02d}"
    ) == "09:25"


def test_overlay_816_exit_env_loads_into_settings():
    env = _parse_env(OVERLAY)
    mega_keys = {
        "TP_RUNG_LADDER_MEGA_FADE_MIN_GIVEBACK_POINTS": "tp_rung_ladder_mega_fade_min_giveback_points",
        "TP_RUNG_LADDER_MEGA_LADDER_FIRST_MIN_BEST_POINTS": "tp_rung_ladder_mega_ladder_first_min_best_points",
    }
    kwargs = {}
    for env_key, field in mega_keys.items():
        val = env[env_key]
        kwargs[field] = float(val) if "." in val else int(val)
    s = Settings(**kwargs)
    assert s.tp_rung_ladder_mega_fade_min_giveback_points == 12.0
    assert s.tp_rung_ladder_mega_ladder_first_min_best_points == 55.0
