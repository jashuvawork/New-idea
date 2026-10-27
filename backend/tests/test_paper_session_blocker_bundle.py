"""Regression bundle: entry blockers fixed in PRs #839–#859 (defaults + smoke)."""

import importlib

import pytest

from app.config import Settings


# PRs that relaxed or fixed false blocks on #676 / pad-lane / parity (merged to main).
_BLOCKER_DEFAULTS: tuple[tuple[str, object], ...] = (
    ("reentry_ml_waive_on_base_capture_eligible_enabled", True),  # #854
    ("fake_explosion_trap_post_win_waive_on_base_capture_eligible_enabled", True),  # #854
    ("call_atm_itm_base_capture_enabled", True),  # #676 / #841
    ("call_atm_itm_base_waives_failed_launch_enabled", True),  # #842
    ("chop_live_near_base_fade_waive_enabled", True),  # #845
    ("win_reentry_requires_velocity_enabled", False),  # #676 Oct1 parity
    ("paper_mirror_live_entry_gates", True),  # #856 (inactive until parity env on)
)


@pytest.mark.parametrize("field,expected", _BLOCKER_DEFAULTS, ids=[f[0] for f in _BLOCKER_DEFAULTS])
def test_merged_pr_blocker_config_defaults(field: str, expected: object):
    assert getattr(Settings(), field) == expected


@pytest.mark.parametrize(
    "module_path",
    [
        "app.engines.live_paper_parity",
        "app.engines.oct_open_index_flip_otm",
        "app.engines.oct1_pad_location",
    ],
    ids=["live_paper_parity", "oct_open_index_flip_otm", "oct1_pad_location"],
)
def test_parity_engine_modules_importable(module_path: str):
    """PR #857 — restored modules must import (CI ModuleNotFoundError guard)."""
    importlib.import_module(module_path)


def test_production_template_676_choke_and_live_best_pin():
    from pathlib import Path

    template = Path(__file__).resolve().parents[2] / "deploy/env.production.template"
    env: dict[str, str] = {}
    for line in template.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v
    assert env.get("PAPER_676_ENTRY_CHOKE_ENABLED") == "true"
    assert env.get("OCT_PAPER_REPLICA_ENABLED") == "true"
    assert env.get("LIVE_BEST_TRADES_ONLY_ENABLED") == "true"
