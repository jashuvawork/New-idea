from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _env_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (ROOT / "deploy/env.production.template").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values


def test_production_template_uses_bounded_loss_policy():
    env = _env_values()
    assert env["DAILY_LOSS_STOP_INR"] == "6000"
    assert env["PER_TRADE_CAPITAL_PCT"] == "0.90"
    assert env["ORDINARY_ENTRY_MAX_CAPITAL_PCT"] == "0.35"
    assert env["FULL_SLEEVE_REQUIRES_ARMED_LAUNCH"] == "true"
    assert env["FULL_SLEEVE_REQUIRES_CVD"] == "true"
    assert env["FULL_SLEEVE_REQUIRES_CVD_ACCELERATION"] == "true"
    assert env["MAX_RISK_PER_TRADE_INR"] == "4000"
    assert env["EXPLOSION_PER_TRADE_MAX_LOSS_INR"] == "2000"
    assert env["EXPLOSION_EXCEPTIONAL_PER_TRADE_MAX_LOSS_INR"] == "4000"
    assert env["ENTRY_TIMING_STRUCTURED_COLD_MIN_VELOCITY_3S"] == "0.5"
    assert env["ENTRY_TIMING_STRUCTURED_COLD_MAX_LOTS"] == "false"
    assert env["EXPLOSION_FAILED_LAUNCH_EXIT_ENABLED"] == "true"
    assert env["EXPLOSION_EARLY_GREEN_LOCK_ENABLED"] == "true"
    assert env["ICT_ELITE_BASE_READY_ENABLED"] == "true"
    assert env["ICT_ELITE_BASE_READY_MIN_MOVE_PCT"] == "2"
    assert env["ICT_ELITE_BASE_READY_MAX_MOVE_PCT"] == "5"
    assert env["ICT_ELITE_BASE_READY_MIN_VELOCITY_3S"] == "1.5"
    assert env["ICT_ELITE_BASE_READY_MIN_VELOCITY_9S"] == "1.5"


def test_deploy_paths_sync_every_bounded_loss_setting():
    workflow = (ROOT / ".github/workflows/deploy-ec2.yml").read_text()
    updater = (ROOT / "deploy/ec2-update.sh").read_text()
    required = {
        "DAILY_LOSS_STOP_INR",
        "PER_TRADE_CAPITAL_PCT",
        "ORDINARY_ENTRY_MAX_CAPITAL_PCT",
        "FULL_SLEEVE_REQUIRES_ARMED_LAUNCH",
        "FULL_SLEEVE_REQUIRES_CVD",
        "FULL_SLEEVE_REQUIRES_CVD_ACCELERATION",
        "MAX_RISK_PER_TRADE_INR",
        "EXPLOSION_PER_TRADE_MAX_LOSS_INR",
        "EXPLOSION_EXCEPTIONAL_PER_TRADE_MAX_LOSS_INR",
        "ENTRY_TIMING_STRUCTURED_COLD_MIN_VELOCITY_3S",
        "ENTRY_TIMING_STRUCTURED_COLD_LOT_CAP",
        "ENTRY_TIMING_STRUCTURED_COLD_MAX_LOTS",
        "EXPLOSION_FAILED_LAUNCH_EXIT_ENABLED",
        "EXPLOSION_EARLY_GREEN_LOCK_ENABLED",
        "ICT_ELITE_BASE_READY_ENABLED",
        "ICT_ELITE_BASE_READY_MIN_MOVE_PCT",
        "ICT_ELITE_BASE_READY_MAX_MOVE_PCT",
        "ICT_ELITE_BASE_READY_MIN_VELOCITY_3S",
        "ICT_ELITE_BASE_READY_MIN_VELOCITY_9S",
        "ICT_ARMED_SUSTAINED_LIFT_MIN_MOVE_PCT",
        "ICT_ARMED_SUSTAINED_LIFT_MAX_MOVE_PCT",
        "ICT_ARMED_SUSTAINED_LIFT_LOOKBACK_SECONDS",
        "ICT_ARMED_SUSTAINED_LIFT_MIN_SAMPLES",
        "ICT_ARMED_SUSTAINED_LIFT_MIN_SPAN_SECONDS",
        "ICT_ARMED_SUSTAINED_LIFT_MIN_PROGRESS_PCT",
        "ICT_ARMED_SUSTAINED_LIFT_MAX_FADE_PCT",
    }
    for key in required:
        assert key in workflow
        assert key in updater
