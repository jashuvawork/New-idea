"""Live arm uses the paper book. The ₹10k overlay is gone."""

import asyncio
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.explosion_profit import evaluate_explosion_exit
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType
from app.routers.health import deployment_readiness

IST = ZoneInfo("Asia/Kolkata")

ROOT = Path(__file__).resolve().parents[2]


def test_live_10k_profile_is_removed():
    assert not (ROOT / "deploy/env.live-10k.overlay").exists()
    assert not (ROOT / "deploy/go-live-10k-monday.sh").exists()
    assert not (ROOT / ".github/workflows/arm-live-10k.yml").exists()
    blob = "\n".join(
        path.read_text()
        for path in (ROOT / ".github/workflows").glob("*.yml")
    )
    assert "go-live-10k-monday.sh" not in blob
    assert "env.live-10k.overlay" not in blob
    assert "ARM-LIVE-10K" not in blob
    settings = Settings()
    assert settings.live_best_trades_only_enabled is True
    assert settings.live_disable_session_lift is False
    assert settings.chop_live_disable_session_lift is False
    assert settings.live_early_fail_exit_enabled is False
    assert settings.chop_live_early_fail_exit_enabled is False
    assert settings.fallback_capital_inr == 275_000
    assert settings.max_sizing_capital_inr == 275_000
    assert settings.daily_loss_stop_inr == 20_000


def test_arm_live_rewrites_a_stale_10k_env_back_to_the_paper_book(tmp_path):
    env_file = tmp_path / "env"
    env_file.write_text(
        "\n".join(
            [
                "FALLBACK_CAPITAL_INR=10000",
                "MAX_SIZING_CAPITAL_INR=10000",
                "DAILY_LOSS_STOP_INR=1000",
                "EMERGENCY_STOP_INR=1000",
                "TOP_MOMENTS_MIN_GRADE=S",
                "LIVE_BEST_TRADES_ONLY_ENABLED=true",
                "LIVE_EARLY_FAIL_EXIT_ENABLED=true",
                "LIVE_DISABLE_SESSION_LIFT=true",
                "CHOP_LIVE_EARLY_FAIL_EXIT_ENABLED=true",
                "CHOP_LIVE_DISABLE_SESSION_LIFT=true",
                "CHOP_LIVE_HARD_BLOCK_WORST_DAY=true",
                "LOSS_STREAK_PAUSE_COUNT=1",
                "SESSION_LARGE_LOSS_PAUSE_INR=400",
                "DAILY_PROFIT_TARGET_INR=1800",
                "FTV_ALLOCATION_MAX_POSITIONS=1",
                "ENABLE_LIVE_TRADING=false",
                "PAPER_TRADING=true",
                "",
            ]
        )
    )
    subprocess.run(
        ["bash", str(ROOT / "deploy/set-execution-mode.sh"), "--live"],
        check=True,
        env={
            **os.environ,
            "ENV_FILE": str(env_file),
            "REPO_DIR": str(ROOT),
            "SKIP_RESTART": "1",
        },
        cwd=ROOT,
    )
    text = env_file.read_text()
    values = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    assert values["FALLBACK_CAPITAL_INR"] == "275000"
    assert values["MAX_SIZING_CAPITAL_INR"] == "275000"
    assert values["DAILY_LOSS_STOP_INR"] == "20000"
    assert values["EMERGENCY_STOP_INR"] == "20000"
    assert values["TOP_MOMENTS_MIN_GRADE"] == "A"
    assert values["LIVE_BEST_TRADES_ONLY_ENABLED"] == "true"
    assert values["LIVE_EARLY_FAIL_EXIT_ENABLED"] == "false"
    assert values["LIVE_DISABLE_SESSION_LIFT"] == "false"
    assert values["CHOP_LIVE_EARLY_FAIL_EXIT_ENABLED"] == "false"
    assert values["CHOP_LIVE_DISABLE_SESSION_LIFT"] == "false"
    assert values["CHOP_LIVE_HARD_BLOCK_WORST_DAY"] == "false"
    assert values["DAILY_PROFIT_TARGET_INR"] == "44000"
    assert values["FTV_ALLOCATION_MAX_POSITIONS"] == "3"
    assert values["ENABLE_LIVE_TRADING"] == "true"
    assert values["PAPER_TRADING"] == "false"
    assert "10000" not in text


def test_readiness_skips_milestone_when_not_required():
    nifty = SimpleNamespace(dataAvailable=True, marketPhase="LIVE_MARKET")
    fast_snapshot = AsyncMock(
        return_value=SimpleNamespace(snapshots={"NIFTY": nifty, "SENSEX": nifty}),
    )
    shared_risk = SimpleNamespace(safe_mode=False)
    milestone = {
        "readyForLiveMilestone": False,
        "message": "Batch 1 · 12/50 toward review",
    }
    settings = SimpleNamespace(
        enable_live_trading=True,
        auto_trading_enabled=True,
        live_milestone_required=False,
        paper_trading=False,
        symbols=["NIFTY", "SENSEX"],
        per_trade_capital_pct=0.9,
        top_ftv_a_normal_max_move_pct=25,
        top_ftv_a_exceptional_max_move_pct=40,
        top_ftv_a_max_capital_pct=0.9,
    )

    with (
        patch("app.routers.health.get_settings", return_value=settings),
        patch(
            "app.routers.health.get_daily_token_status",
            new=AsyncMock(return_value={"validToday": True}),
        ),
        patch(
            "app.routers.health.trade_store.check_store_health",
            return_value={
                "storeDir": "/tmp/trades",
                "logFile": "/tmp/trades/events.jsonl",
                "logSizeBytes": 0,
                "checks": {"healthy": True},
            },
        ),
        patch(
            "app.routers.health.trade_store.count_today_trades",
            return_value={"open": 0, "closed": 0, "total": 0},
        ),
        patch("app.routers.health.get_market_phase", return_value="LIVE_MARKET"),
        patch("app.routers.health.rate_limit_active", return_value=False),
        patch("app.routers.health.rate_limit_cooldown_remaining", return_value=0.0),
        patch("app.routers.health.ws_status", return_value={"enabled": False, "connected": False}),
        patch("app.engines.auto_trader.get_risk_engine", return_value=shared_risk),
        patch("app.engines.auto_trader.get_state", return_value=AutoTraderState()),
        patch("app.loop_watchdog.watchdog_status", return_value={"enabled": False}),
        patch("app.routers.market.get_multi_snapshot_fast", new=fast_snapshot),
        patch(
            "app.engines.performance_milestone.compute_milestone_stats",
            return_value=milestone,
        ),
        patch(
            "app.engines.worst_day_guard.worst_day_blocks_live",
            return_value=(False, "", {}),
        ),
    ):
        payload = asyncio.run(deployment_readiness())

    assert payload["checks"]["milestoneRequired"] is False
    assert payload["checks"]["milestonePassed"] is True
    assert payload["readyForLive"] is True


def test_live_hold_skips_inr_force_stop_and_rides_to_adaptive_sl():
    """Live + hold_to_sl: no INR cap — exit only at structural adaptive SL."""
    from app.config import get_settings

    s = get_settings()
    trade = PaperTrade(
        id="live1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=24500.0,
        entryPremium=50.0,
        currentPremium=48.0,
        lots=2,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST) - timedelta(seconds=120),
        bestPnlPoints=0.0,
        entryContext={"exitPlan": {"stopPoints": 6.0, "adaptiveStop": True}},
    )
    with (
        patch.object(s, "enable_live_trading", True),
        patch.object(s, "live_hold_to_structural_sl", True),
        patch.object(s, "explosion_failed_launch_exit_enabled", True),
        patch.object(s, "explosion_never_green_stop_enabled", True),
        patch.object(s, "explosion_per_trade_max_loss_inr", 100.0),
        patch.object(s, "explosion_exceptional_per_trade_max_loss_inr", 200.0),
        patch.object(s, "emergency_stop_enabled", True),
        patch.object(s, "emergency_stop_inr", 1000.0),
        patch.object(s, "explosion_peak_fade_lock_enabled", False),
        patch.object(s, "explosion_peak_capture_enabled", False),
        patch.object(s, "explosion_no_progress_enabled", False),
    ):
        reason, _ = evaluate_explosion_exit(trade, 48.0, "ELITE", 65, live_velocity_3s=-1.0)
    assert reason not in (
        "explosion_never_green_stop",
        "explosion_failed_launch",
        "explosion_per_trade_risk_cap",
        "explosion_emergency_stop",
    )

    with (
        patch.object(s, "enable_live_trading", True),
        patch.object(s, "live_hold_to_structural_sl", True),
        patch.object(s, "explosion_peak_fade_lock_enabled", False),
        patch.object(s, "explosion_peak_capture_enabled", False),
        patch.object(s, "explosion_no_progress_enabled", False),
    ):
        reason2, _ = evaluate_explosion_exit(trade, 43.0, "ELITE", 65, live_velocity_3s=-1.0)
    assert reason2 in ("adaptive_stop_loss", "explosion_stop_loss")


def test_live_structural_hold_bypasses_entry_per_trade_risk_cap():
    """Live structural hold must not die on a pre-entry INR clip."""
    from unittest.mock import MagicMock, patch

    from app.engines.risk_engine import RiskEngine
    from app.models.schemas import AutoTraderState, Side, StrategyType

    settings = MagicMock()
    settings.aggressive_lot_sizing = False
    settings.aggressive_max_open_scalps = 3
    settings.swing_max_open = 1
    settings.per_trade_capital_pct = 0.9
    settings.max_risk_per_trade_inr = 200
    settings.swing_max_loss_inr = 20_000
    settings.emergency_stop_enabled = False
    settings.daily_loss_stop_inr = 1000
    settings.block_duplicate_open_leg = True
    settings.enable_live_trading = True
    settings.live_hold_to_structural_sl = True
    settings.ftv_ranked_allocation_enabled = True
    settings.ftv_allocation_max_positions = 3
    settings.ftv_allocation_max_same_side = 2

    cap = MagicMock()
    cap.availableMarginInr = 10_000
    cap.perTradeCapitalInr = 9_000

    engine = RiskEngine()
    state = AutoTraderState(running=True)

    with (
        patch("app.engines.risk_engine.get_settings", return_value=settings),
        patch("app.engines.risk_engine.get_capital_snapshot", return_value=cap),
    ):
        ok, reason = engine.check_new_entry(
            state,
            "NIFTY",
            Side.PUT,
            lots=2,
            premium=68.0,
            lot_multiplier=65,
            strategy_type=StrategyType.EXPLOSIVE,
            strike=24050.0,
            stop_points=8.0,
            ignore_per_trade_risk_cap=False,
        )

    assert ok is True
    assert reason == "passed"
