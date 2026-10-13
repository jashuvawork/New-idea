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
LIVE_CAPITAL = ROOT / "deploy" / "env.live-capital.overlay"

ARM_PATHS = [
    GO_LIVE,
    ROOT / ".github" / "workflows" / "arm-live-ec2.yml",
    ROOT / ".github" / "workflows" / "arm-live-on-push.yml",
    ROOT / ".github" / "workflows" / "deploy-ec2.yml",
]


@pytest.mark.parametrize("path", ARM_PATHS, ids=lambda p: p.name)
def test_arm_live_paths_do_not_purge_trade_logs(path: Path):
    assert "purge-logs" not in path.read_text()


@pytest.mark.parametrize(
    "path",
    [ROOT / ".github" / "workflows" / n for n in ("arm-live-on-push.yml", "deploy-ec2.yml")],
    ids=lambda p: p.name,
)
def test_arm_live_on_push_uses_100k_capital(path: Path):
    text = path.read_text()
    assert "LIVE_OVERLAY=deploy/env.live-capital.overlay LIVE_CAPITAL_INR=100000" in text
    assert "env.live-150k.overlay" not in text
    assert "env.live-50k.overlay" not in text


def test_manual_arm_takes_any_day_capital():
    text = (ROOT / ".github" / "workflows" / "arm-live-ec2.yml").read_text()
    assert 'default: "100000"' in text
    assert '[ "$CAP" -lt 45000 ]' in text
    assert "LIVE_OVERLAY=deploy/env.live-capital.overlay LIVE_CAPITAL_INR=${CAP}" in text


@pytest.mark.parametrize(
    "env_text,overlay",
    [
        ("FALLBACK_CAPITAL_INR=150000\n", "env.live-150k.overlay"),
        ("FALLBACK_CAPITAL_INR=50000\n", "env.live-50k.overlay"),
        (
            "FALLBACK_CAPITAL_INR=123000\nCAPITAL_SCALED_RISK_LIMITS_ENABLED=true\n",
            "env.live-capital.overlay",
        ),
    ],
)
def test_ec2_update_preserves_live_capital_overlay(tmp_path: Path, env_text: str, overlay: str):
    script = (ROOT / "deploy" / "ec2-update.sh").read_text()
    fn = script.split("_parity_cap_overlay() {", 1)[1].split("\n  }\n", 1)[0]
    env_file = tmp_path / "env"
    env_file.write_text("ENABLE_LIVE_TRADING=true\n" + env_text)
    out = subprocess.run(
        ["bash", "-c", f'_f() {{{fn}\n}}; _f'],
        env={**os.environ, "ENV_FILE": str(env_file), "REPO_DIR": "/repo"},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert out == f"/repo/deploy/{overlay}"


def test_live_capital_overlay_has_no_fixed_capital():
    vals = dict(
        line.split("=", 1) for line in LIVE_CAPITAL.read_text().splitlines()
        if line and not line.startswith("#")
    )
    assert vals["CAPITAL_SCALED_RISK_LIMITS_ENABLED"] == "true"
    assert vals["DAILY_LOSS_STOP_CAPITAL_PCT"] == "10"
    assert "FALLBACK_CAPITAL_INR" not in vals
    assert "MAX_SIZING_CAPITAL_INR" not in vals
    assert vals["ENABLE_LIVE_TRADING"] == "false"


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
    assert "env.live-capital.overlay" in out
    assert "₹100000" in out
    assert "FALLBACK_CAPITAL_INR=100000" in out
    assert "ENABLE_LIVE_TRADING=true" in out
    assert out.index("[dry-run] audit") < out.index("ENABLE_LIVE_TRADING=true")


def _build_env(tmp_path: Path, capital: Path = LIVE_150K) -> Path:
    env_file = tmp_path / "env"
    for overlay in (RULES, capital):
        subprocess.run(
            ["bash", str(APPLY), str(overlay)],
            env={**os.environ, "ENV_FILE": str(env_file)},
            check=True,
            capture_output=True,
        )
    return env_file


def _audit(env_file: Path, capital: Path = LIVE_150K) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(AUDIT)],
        env={
            **os.environ,
            "ENV_FILE": str(env_file),
            "REPO_DIR": str(ROOT),
            "RULES_OVERLAY": str(RULES),
            "CAPITAL_OVERLAY": str(capital),
        },
        capture_output=True,
        text=True,
    )


def test_audit_passes_on_frozen_october_plus_live_150k(tmp_path: Path):
    result = _audit(_build_env(tmp_path))
    assert result.returncode == 0, result.stdout


def test_audit_passes_on_frozen_october_plus_live_capital(tmp_path: Path):
    result = _audit(_build_env(tmp_path, LIVE_CAPITAL), LIVE_CAPITAL)
    assert result.returncode == 0, result.stdout
    assert _audit(_build_env(tmp_path / "x", LIVE_150K), LIVE_CAPITAL).returncode == 1


@pytest.mark.parametrize("capital", ["120000", "275000"])
def test_arm_live_dry_run_writes_any_day_capital(capital: str):
    out = subprocess.run(
        ["bash", str(GO_LIVE), "--arm-live", "--dry-run"],
        capture_output=True,
        text=True,
        env={**os.environ, "REPO_DIR": str(ROOT), "ENV_FILE": "/nonexistent/env",
             "LIVE_CAPITAL_INR": capital},
        check=True,
    ).stdout
    assert f"FALLBACK_CAPITAL_INR={capital}" in out
    assert f"MAX_SIZING_CAPITAL_INR={capital}" in out


@pytest.mark.parametrize("capital", ["1e5", "30000", ""])
def test_arm_live_rejects_bad_day_capital(capital: str):
    result = subprocess.run(
        ["bash", str(GO_LIVE), "--arm-live", "--dry-run"],
        capture_output=True,
        text=True,
        env={**os.environ, "REPO_DIR": str(ROOT), "ENV_FILE": "/nonexistent/env",
             "LIVE_CAPITAL_INR": capital},
    )
    if capital == "":
        assert result.returncode == 0
    else:
        assert result.returncode == 1
        assert "LIVE_CAPITAL_INR must be" in result.stderr


def test_set_day_capital_rewrites_env_and_requires_scaled_profile(tmp_path: Path):
    script = ROOT / "deploy" / "set-day-capital.sh"
    env_file = tmp_path / "env"
    env_file.write_text("FALLBACK_CAPITAL_INR=100000\nMAX_SIZING_CAPITAL_INR=100000\n")
    run = lambda cap: subprocess.run(  # noqa: E731
        ["bash", str(script), cap],
        capture_output=True,
        text=True,
        env={**os.environ, "ENV_FILE": str(env_file), "BASE_URL": "http://127.0.0.1:9"},
    )
    assert run("120000").returncode == 1
    env_file.write_text(env_file.read_text() + "CAPITAL_SCALED_RISK_LIMITS_ENABLED=true\n")
    assert run("20000").returncode == 1
    run("120000")
    text = env_file.read_text()
    assert "FALLBACK_CAPITAL_INR=120000" in text
    assert "MAX_SIZING_CAPITAL_INR=120000" in text


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
