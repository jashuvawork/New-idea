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
    assert env["SEP917_LEGACY_PROFILE_ENABLED"] == "true"
    assert env["FTV_ELITE_TOP_ONLY_ENABLED"] == "false"
    assert env["MAX_OPTION_PREMIUM_INR"] == "350"
    assert env["TOP_FTV_A_ENABLED"] == "true"
    assert env["TOP_FTV_A_MAX_CAPITAL_PCT"] == "0.90"
    assert env["TOP_FTV_A_EXCEPTIONAL_MAX_MOVE_PCT"] == "40"
    # 15% of today's book. ₹2.75L → ₹41,250. The INR value is the fallback.
    assert env["DAILY_LOSS_STOP_FROM_CAPITAL"] == "true"
    assert env["DAILY_LOSS_STOP_PCT"] == "0.15"
    assert env["DAILY_LOSS_STOP_INR"] == "20000"
    assert env["FALLBACK_CAPITAL_INR"] == "275000"
    assert env["MAX_SIZING_CAPITAL_INR"] == "275000"
    assert env["UNIFIED_PROFIT_LADDER_ENABLED"] == "true"
    assert env["UNIFIED_PROFIT_LADDER_BREAKEVEN_ENABLED"] == "false"
    assert env["WORST_DAY_BLOCKS_LIVE"] == "false"
    assert env["CHOP_LIVE_HARD_BLOCK_WORST_DAY"] == "false"
    assert env["BEST_TRADE_BLOCK_CHOP_DEEP_CHASE_ENABLED"] == "true"
    assert env["LIVE_BEST_TRADES_ONLY_ENABLED"] == "true"
    assert env["LIVE_BEST_TRADES_MIN_GRADE"] == "A"
    assert env["WIN_REENTRY_REQUIRES_VELOCITY_ENABLED"] == "false"
    assert env["OPEN_SIDE_CONFIRMATION_ENABLED"] == "true"
    assert env["OPEN_SIDE_CONFIRMATION_MIN_MINUTES"] == "1"
    assert env["INDEX_CANDLE_ROLLOVER_BLOCK_ENABLED"] == "true"
    assert env["INDEX_CANDLE_ROLLOVER_STEPS"] == "3"
    assert env["INDEX_CANDLE_ROLLOVER_MIN_GIVEBACK_PCT"] == "0.04"
    assert env["LIVE_EARLY_FAIL_EXIT_ENABLED"] == "false"
    assert env["LIVE_DISABLE_SESSION_LIFT"] == "false"
    assert env["CHOP_LIVE_EARLY_FAIL_EXIT_ENABLED"] == "false"
    assert env["CHOP_LIVE_DISABLE_SESSION_LIFT"] == "false"
    assert env["TOP_MOMENTS_MIN_GRADE"] == "A"
    assert env["FTV_ALLOCATION_MAX_POSITIONS"] == "3"
    assert env["FTV_ALLOCATION_MAX_SAME_SIDE"] == "2"
    assert env["EMERGENCY_STOP_INR"] == "20000"
    assert env["DAILY_PROFIT_TARGET_INR"] == "44000"
    assert env["EXPIRY_EVENING_BLOCK_ENABLED"] == "false"
    assert env["POWER_HOUR_TOP_ONLY_ENABLED"] == "false"
    assert env["WORST_DAY_PAUSE_ENABLED"] == "true"
    assert env["EXPIRY_WORST_DAY_HALT_ENTRIES"] == "true"
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
    assert env["EXPLOSION_FAILED_LAUNCH_EXIT_ENABLED"] == "false"
    assert env["EXPLOSION_EARLY_GREEN_LOCK_ENABLED"] == "false"
    assert env["ICT_ARMED_BASE_LAUNCH_MAX_MOVE_PCT"] == "15"
    assert env["ICT_ARMED_BASE_LAUNCH_MIN_VELOCITY_3S"] == "2"
    assert env["ICT_ARMED_BASE_LAUNCH_MIN_QUALITY"] == "65"
    assert env["ICT_ARMED_BASE_LAUNCH_MIN_SCORE"] == "64.5"
    assert env["ICT_ELITE_BASE_READY_ENABLED"] == "true"
    assert env["ICT_ELITE_BASE_READY_MIN_MOVE_PCT"] == "2"
    assert env["ICT_ELITE_BASE_READY_MAX_MOVE_PCT"] == "5"
    assert env["ICT_ELITE_BASE_READY_MIN_VELOCITY_3S"] == "1.5"
    assert env["ICT_ELITE_BASE_READY_MIN_VELOCITY_9S"] == "1.5"


def test_deploy_leaves_the_day_capital_in_place():
    workflow = (ROOT / ".github/workflows/deploy-ec2.yml").read_text()
    updater = (ROOT / "deploy/ec2-update.sh").read_text()
    assert "FALLBACK_CAPITAL_INR" not in workflow
    assert "MAX_SIZING_CAPITAL_INR" not in workflow
    assert "FALLBACK_CAPITAL_INR" not in updater
    assert "MAX_SIZING_CAPITAL_INR" not in updater
    assert (ROOT / "deploy/set-day-capital.sh").is_file()
    assert (ROOT / ".github/workflows/set-day-capital-ec2.yml").is_file()


def test_deploy_paths_sync_every_bounded_loss_setting():
    workflow = (ROOT / ".github/workflows/deploy-ec2.yml").read_text()
    updater = (ROOT / "deploy/ec2-update.sh").read_text()
    required = {
        "FTV_ELITE_TOP_ONLY_ENABLED",
        "TOP_FTV_A_ENABLED",
        "TOP_FTV_A_MIN_EXPLOSION_SCORE",
        "TOP_FTV_A_MIN_QUALITY",
        "TOP_FTV_A_MIN_TQS",
        "TOP_FTV_A_MIN_VELOCITY_3S",
        "TOP_FTV_A_MIN_VELOCITY_9S",
        "TOP_FTV_A_NORMAL_MAX_MOVE_PCT",
        "TOP_FTV_A_MAX_CAPITAL_PCT",
        "TOP_FTV_A_EXCEPTIONAL_MIN_EXPLOSION_SCORE",
        "TOP_FTV_A_EXCEPTIONAL_MIN_QUALITY",
        "TOP_FTV_A_EXCEPTIONAL_MIN_TQS",
        "TOP_FTV_A_EXCEPTIONAL_MIN_VELOCITY_3S",
        "TOP_FTV_A_EXCEPTIONAL_MIN_VELOCITY_9S",
        "TOP_FTV_A_EXCEPTIONAL_MAX_MOVE_PCT",
        "WORST_DAY_BLOCKS_LIVE",
        "CHOP_LIVE_HARD_BLOCK_WORST_DAY",
        "BEST_TRADE_BLOCK_CHOP_DEEP_CHASE_ENABLED",
        "LIVE_BEST_TRADES_ONLY_ENABLED",
        "OPEN_SIDE_CONFIRMATION_ENABLED",
        "OPEN_SIDE_CONFIRMATION_MIN_MINUTES",
        "INDEX_CANDLE_ROLLOVER_BLOCK_ENABLED",
        "INDEX_CANDLE_ROLLOVER_STEPS",
        "INDEX_CANDLE_ROLLOVER_MIN_GIVEBACK_PCT",
        "LIVE_BEST_TRADES_MIN_GRADE",
        "WIN_REENTRY_REQUIRES_VELOCITY_ENABLED",
        "LIVE_EARLY_FAIL_EXIT_ENABLED",
        "LIVE_DISABLE_SESSION_LIFT",
        "CHOP_LIVE_EARLY_FAIL_EXIT_ENABLED",
        "CHOP_LIVE_DISABLE_SESSION_LIFT",
        "TOP_MOMENTS_MIN_GRADE",
        "FTV_ALLOCATION_MAX_POSITIONS",
        "FTV_ALLOCATION_MAX_SAME_SIDE",
        "EMERGENCY_STOP_ENABLED",
        "EMERGENCY_STOP_INR",
        "DAILY_PROFIT_TARGET_INR",
        "EXPIRY_EVENING_BLOCK_ENABLED",
        "POWER_HOUR_TOP_ONLY_ENABLED",
        "DAILY_LOSS_STOP_INR",
        "DAILY_LOSS_STOP_FROM_CAPITAL",
        "DAILY_LOSS_STOP_PCT",
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
        "ICT_ARMED_BASE_LAUNCH_MIN_MOVE_PCT",
        "ICT_ARMED_BASE_LAUNCH_MAX_MOVE_PCT",
        "ICT_ARMED_BASE_LAUNCH_MIN_VELOCITY_3S",
        "ICT_ARMED_BASE_LAUNCH_MIN_VELOCITY_9S",
        "ICT_ARMED_BASE_LAUNCH_MIN_ABSOLUTE_VOLUME",
        "ICT_ARMED_BASE_LAUNCH_MIN_QUALITY",
        "ICT_ARMED_BASE_LAUNCH_MIN_SCORE",
        "ICT_ARMED_BASE_LAUNCH_MIN_TQS",
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
