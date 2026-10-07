"""Arming live keeps paper trade history and refuses to arm when env drifts from Frozen October."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GO_LIVE = ROOT / "deploy" / "go-live-10k-monday.sh"
AUDIT = ROOT / "deploy" / "audit-live-paper-env.sh"
APPLY = ROOT / "deploy" / "apply-env-overlay.sh"
RULES = ROOT / "deploy" / "env.october-frozen.overlay"
LIVE_150K = ROOT / "deploy" / "env.live-150k.overlay"

ARM_PATHS = [
    GO_LIVE,
    ROOT / ".github" / "workflows" / "arm-live-ec2.yml",
    ROOT / ".github" / "workflows" / "arm-live-on-push.yml",
    ROOT / ".github" / "workflows" / "deploy-ec2.yml",
]


@pytest.mark.parametrize("path", ARM_PATHS, ids=lambda p: p.name)
def test_arm_live_paths_do_not_purge_trade_logs(path: Path):
    assert "purge-logs" not in path.read_text()


def test_arm_live_audits_env_before_setting_live_flags():
    script = GO_LIVE.read_text()
    arm_block = script.split('if [ "$MODE" = "arm-live" ]; then', 1)[1]
    audit_at = arm_block.index("audit-live-paper-env.sh")
    flip_at = arm_block.index("_set_env_key ENABLE_LIVE_TRADING true")
    assert audit_at < flip_at
    assert 'CAPITAL_OVERLAY="$OVERLAY"' in arm_block


def test_arm_live_dry_run_reports_audit_and_no_purge():
    out = subprocess.run(
        ["bash", str(GO_LIVE), "--arm-live", "--dry-run"],
        capture_output=True,
        text=True,
        env={**os.environ, "REPO_DIR": str(ROOT), "ENV_FILE": "/nonexistent/env"},
        check=True,
    ).stdout
    assert "[dry-run] audit" in out
    assert "env.live-150k.overlay" in out
    assert "ENABLE_LIVE_TRADING=true" in out
    assert out.index("[dry-run] audit") < out.index("ENABLE_LIVE_TRADING=true")


def _build_env(tmp_path: Path) -> Path:
    env_file = tmp_path / "env"
    for overlay in (RULES, LIVE_150K):
        subprocess.run(
            ["bash", str(APPLY), str(overlay)],
            env={**os.environ, "ENV_FILE": str(env_file)},
            check=True,
            capture_output=True,
        )
    return env_file


def _audit(env_file: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(AUDIT)],
        env={
            **os.environ,
            "ENV_FILE": str(env_file),
            "REPO_DIR": str(ROOT),
            "RULES_OVERLAY": str(RULES),
            "CAPITAL_OVERLAY": str(LIVE_150K),
        },
        capture_output=True,
        text=True,
    )


def test_audit_passes_on_frozen_october_plus_live_150k(tmp_path: Path):
    result = _audit(_build_env(tmp_path))
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    "key,bad",
    [
        ("LIVE_BEST_TRADES_ONLY_ENABLED", "true"),
        ("SYMMETRIC_BEST_TRADE_CAPTURE_ENABLED", "false"),
        ("DAILY_LOSS_STOP_INR", "30000"),
    ],
)
def test_audit_fails_when_env_drifts_from_paper_rules(tmp_path: Path, key: str, bad: str):
    env_file = _build_env(tmp_path)
    lines = [
        f"{key}={bad}" if line.startswith(f"{key}=") else line
        for line in env_file.read_text().splitlines()
    ]
    env_file.write_text("\n".join(lines) + "\n")
    result = _audit(env_file)
    assert result.returncode == 1
    assert key in result.stdout
