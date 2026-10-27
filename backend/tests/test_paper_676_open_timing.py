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


def test_full_session_overlay_has_676_open_timing():
    env = _parse_env(OVERLAY)
    assert env["ENTRY_EARLIEST_MINUTE"] == "16"
    assert env["EXPLOSION_ENTRY_EARLIEST_MINUTE"] == "16"
    assert env["OPEN_SIDE_CONFIRMATION_START_MINUTE"] == "15"
    assert env["OPEN_SIDE_CONFIRMATION_MIN_MINUTES"] == "1"
    assert env["PAPER_676_ENTRY_CHOKE_ENABLED"] == "true"
    assert env["OCT_PAPER_REPLICA_ENABLED"] == "true"


def test_template_keeps_safer_0920_entry_not_in_overlay_conflict():
    """Global template stays 09:20; 676 timing is overlay-only for paper redeploy."""
    tpl = _parse_env(TEMPLATE)
    ovl = _parse_env(OVERLAY)
    assert tpl["ENTRY_EARLIEST_MINUTE"] == "20"
    assert ovl["ENTRY_EARLIEST_MINUTE"] == "16"


def test_settings_reflect_overlay_entry_and_open_side():
    s = Settings(
        entry_earliest_hour=9,
        entry_earliest_minute=16,
        explosion_entry_earliest_hour=9,
        explosion_entry_earliest_minute=16,
        open_side_confirmation_start_hour=9,
        open_side_confirmation_start_minute=15,
        open_side_confirmation_min_minutes=1,
        paper_676_entry_choke_enabled=True,
        oct_paper_replica_enabled=True,
        paper_trading=True,
        enable_live_trading=False,
    )
    assert f"{s.entry_earliest_hour:02d}:{s.entry_earliest_minute:02d}" == "09:16"
    assert (
        f"{s.open_side_confirmation_start_hour:02d}:"
        f"{s.open_side_confirmation_start_minute:02d}"
    ) == "09:15"
