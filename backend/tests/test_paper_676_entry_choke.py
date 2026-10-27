"""Paper deploy must arm the #676-era entry choke (Oct replica + base capture)."""

from pathlib import Path

import pytest

from app.config import Settings
from app.engines.live_paper_parity import (
    oct_paper_entry_loosening_active,
    oct_paper_replica_active,
    oct_paper_skip_live_only_session_gates,
    paper_676_entry_choke_active,
    trading_rules_match_paper,
)

_TEMPLATE = Path(__file__).resolve().parents[2] / "deploy" / "env.production.template"


def _template_env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in _TEMPLATE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key] = value
    return out


@pytest.fixture
def use_settings(monkeypatch):
    def _apply(settings: Settings) -> Settings:
        getter = lambda: settings  # noqa: E731
        monkeypatch.setattr("app.config.get_settings", getter)
        return settings

    return _apply


def test_production_template_arms_paper_676_entry_choke():
    env = _template_env()
    assert env.get("PAPER_676_ENTRY_CHOKE_ENABLED") == "true"
    assert env.get("OCT_PAPER_REPLICA_ENABLED") == "true"
    # Live arm pin keeps grade gate true; --paper mode sets live_best false explicitly.
    assert env.get("LIVE_BEST_TRADES_ONLY_ENABLED") == "true"


def test_set_execution_mode_paper_disables_live_best_gate(tmp_path):
    import os
    import subprocess

    root = _TEMPLATE.parents[1]
    env_file = tmp_path / "env"
    env_file.write_text("ENABLE_LIVE_TRADING=true\nLIVE_BEST_TRADES_ONLY_ENABLED=true\n")
    subprocess.run(
        ["bash", str(root / "deploy/set-execution-mode.sh"), "--paper"],
        check=True,
        env={**os.environ, "ENV_FILE": str(env_file), "REPO_DIR": str(root), "SKIP_RESTART": "1"},
    )
    text = env_file.read_text()
    assert "LIVE_BEST_TRADES_ONLY_ENABLED=false" in text
    assert "PAPER_676_ENTRY_CHOKE_ENABLED=true" in text
    assert "PAPER_816_EXIT_PACK_ENABLED=true" in text


def test_paper_676_flag_enables_replica_stack(use_settings):
    raw = {k.lower(): v for k, v in _template_env().items()}
    # Settings uses field names, not env keys — set the choke flags explicitly.
    s = Settings(
        enable_live_trading=False,
        paper_trading=True,
        paper_676_entry_choke_enabled=True,
        live_best_trades_only_enabled=False,
    )
    use_settings(s)
    assert paper_676_entry_choke_active(s) is True
    assert oct_paper_replica_active(s) is True
    assert trading_rules_match_paper(s) is True
    assert oct_paper_skip_live_only_session_gates(s) is True
    assert oct_paper_entry_loosening_active(s) is False


def test_live_execution_does_not_use_paper_676_choke(use_settings):
    s = Settings(
        enable_live_trading=True,
        auto_trading_enabled=True,
        paper_trading=False,
        paper_676_entry_choke_enabled=True,
        oct_paper_replica_enabled=True,
    )
    use_settings(s)
    assert paper_676_entry_choke_active(s) is False
