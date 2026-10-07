"""Live overlays (₹2L default, ₹10k legacy) and milestone bypass for go-live."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_profit import evaluate_explosion_exit
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType
from app.routers.health import deployment_readiness

IST = ZoneInfo("Asia/Kolkata")

ROOT = Path(__file__).resolve().parents[2]


def _overlay_values(name: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (ROOT / "deploy" / name).read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return values


def test_live_paper_parity_deploy_scripts_exist():
    root = ROOT / "deploy"
    assert (root / "apply-live-paper-parity-env.sh").is_file()
    assert (root / "audit-live-paper-env.sh").is_file()


def test_live_200k_overlay_scales_capital_and_risk():
    env = _overlay_values("env.live-200k.overlay")
    assert env["FALLBACK_CAPITAL_INR"] == "200000"
    assert env["MAX_SIZING_CAPITAL_INR"] == "200000"
    assert env["USE_UPSTOX_CAPITAL_FOR_SIZING"] == "false"
    assert env["SEP917_LEGACY_PROFILE_ENABLED"] == "true"
    assert env["TOP_MOMENTS_ONLY_ENABLED"] == "false"
    assert env["PAPER_SIMPLE_PROFIT_MODE"] == "true"
    assert env["LIVE_MILESTONE_REQUIRED"] == "false"
    assert env["DAILY_LOSS_STOP_INR"] == "20000"
    assert env["EMERGENCY_STOP_INR"] == "20000"
    assert env["SESSION_LARGE_LOSS_PAUSE_INR"] == "8000"
    assert env["MAX_RISK_PER_TRADE_INR"] == "4000"
    assert env["DAILY_PROFIT_TARGET_FROM_CAPITAL"] == "true"
    assert env["ENABLE_LIVE_TRADING"] == "false"
    assert env["LIVE_PAPER_PARITY_ENABLED"] == "true"
    assert env["LIVE_TRADE_SELECTION_PARITY_WITH_PAPER"] == "true"
    assert env["LIVE_BEST_TRADES_ONLY_ENABLED"] == "false"
    assert env["TOP_MOMENTS_MIN_GRADE"] == "A"
    assert env["WORST_DAY_BLOCKS_LIVE"] == "false"
    assert env["FTV_ALLOCATION_MAX_POSITIONS"] == "3"
    assert env["LIVE_HOLD_TO_STRUCTURAL_SL"] == "false"
    assert env["CHOP_LIVE_EARLY_FAIL_EXIT_ENABLED"] == "false"
    assert env["LIVE_BROKER_RECONCILIATION_ENABLED"] == "false"


def test_worst_day_blocks_live_off_when_selection_parity():
    from unittest.mock import MagicMock, patch

    from app.engines.worst_day_guard import worst_day_blocks_live
    from app.models.schemas import AutoTraderState

    settings = MagicMock()
    settings.live_trade_selection_parity_with_paper = True
    settings.worst_day_blocks_live = True
    settings.enable_live_trading = True
    verdict = SimpleNamespace(is_worst=True, to_dict=lambda: {"isWorst": True})
    with (
        patch("app.engines.worst_day_guard.get_settings", return_value=settings),
        patch("app.engines.worst_day_guard.identify_worst_day", return_value=verdict),
    ):
        blocked, reason, _ = worst_day_blocks_live(AutoTraderState(), {})
    assert blocked is False
    assert reason == "ok"


def test_live_10k_overlay_scales_capital_and_risk():
    env = _overlay_values("env.live-10k.overlay")
    assert env["FALLBACK_CAPITAL_INR"] == "10000"
    assert env["MAX_SIZING_CAPITAL_INR"] == "10000"
    assert env["USE_UPSTOX_CAPITAL_FOR_SIZING"] == "true"
    assert env["LIVE_MILESTONE_REQUIRED"] == "false"
    assert env["DAILY_LOSS_STOP_INR"] == "1000"
    assert env["EMERGENCY_STOP_ENABLED"] == "false"
    assert env["EMERGENCY_STOP_INR"] == "1000"
    assert env["LIVE_HOLD_TO_STRUCTURAL_SL"] == "true"
    assert env["MAX_RISK_PER_TRADE_INR"] == "0"
    assert env["EXPLOSION_PER_TRADE_MAX_LOSS_INR"] == "0"
    assert env["EXPLOSION_EXCEPTIONAL_PER_TRADE_MAX_LOSS_INR"] == "0"
    assert env["INDEX_CONFIRMED_FTV_PER_TRADE_MAX_LOSS_INR"] == "0"
    assert env["SESSION_LARGE_LOSS_PAUSE_INR"] == "400"
    assert env["ENABLE_LIVE_TRADING"] == "false"


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
        patch(
            "app.engines.live_paper_parity.live_paper_profile_ok",
            return_value=(True, []),
        ),
        patch(
            "app.engines.october_frozen_profile.october_frozen_profile_ok",
            return_value=(True, []),
        ),
        patch(
            "app.engines.october_frozen_profile.october_frozen_profile_summary",
            return_value={
                "active": True,
                "padEntryGuardEnabled": True,
                "symmetricBestTradeCaptureEnabled": True,
            },
        ),
    ):
        payload = asyncio.run(deployment_readiness())

    assert payload["checks"]["milestoneRequired"] is False
    assert payload["checks"]["milestonePassed"] is True
    assert payload["checks"]["livePaperProfileOk"] is True
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
        patch("app.engines.explosion_profit.get_settings", return_value=s),
        patch("app.engines.adaptive_exits.get_settings", return_value=s),
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
        patch("app.engines.explosion_profit.get_settings", return_value=s),
        patch("app.engines.adaptive_exits.get_settings", return_value=s),
        patch("app.engines.explosion_profit._adaptive_stop_min_hold", return_value=0),
    ):
        reason2, _ = evaluate_explosion_exit(trade, 43.0, "ELITE", 65, live_velocity_3s=-1.0)
    assert reason2 in ("adaptive_stop_loss", "explosion_stop_loss")


def test_live_structural_hold_bypasses_entry_per_trade_risk_cap():
    """₹10k live: full sleeve + structural SL must not die on pre-entry INR clip."""
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
        patch("app.engines.live_paper_parity.live_paper_parity_active", return_value=False),
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
