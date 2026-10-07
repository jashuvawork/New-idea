"""Adaptive stop loss on open trades — live, paper, and broker-adopted legs."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.adaptive_exits import (
    build_merged_adaptive_exit_plan,
    ensure_open_trade_exit_plan,
    should_trade_use_adaptive_stop,
)
from app.engines.explosion_profit import evaluate_explosion_exit
from app.models.schemas import (
    MarketPhase,
    PaperTrade,
    Side,
    StrategyType,
    SymbolSnapshot,
)

IST = ZoneInfo("Asia/Kolkata")


def _snap() -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=22700.0,
        topExplosion={"tier": "ELITE", "premium": 80.0, "velocity3s": 2.0},
    )


def test_entry_exit_plan_stamps_adaptive_stop():
    with patch("app.engines.adaptive_exits.get_settings") as mock_gs:
        s = Settings()
        s.adaptive_exits_enabled = True
        mock_gs.return_value = s
        with patch(
            "app.engines.adaptive_exits.compute_adaptive_exit_plan",
        ) as mock_plan:
            from app.engines.adaptive_exits import AdaptiveExitPlan

            mock_plan.return_value = AdaptiveExitPlan(
                stopPoints=12.0,
                targetPoints=30.0,
                trailArmPoints=8.0,
                trailKeepRatio=0.55,
            )
            with patch(
                "app.engines.chart_exit_levels.merge_chart_into_exit_plan",
                side_effect=lambda p, *_a, **_k: dict(p),
            ):
                plan = build_merged_adaptive_exit_plan(
                    _snap(),
                    StrategyType.EXPLOSIVE,
                    "CALL",
                    88.0,
                    entry_premium=80.0,
                )
    assert plan.get("adaptiveStop") is True


def test_should_trade_use_adaptive_stop_paper_and_live():
    s = Settings()
    s.adaptive_exits_enabled = True
    trade = PaperTrade(
        id="t1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22700.0,
        entryPremium=80.0,
        currentPremium=80.0,
        lots=2,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST),
        entryContext={
            "executionMode": "PAPER_LIVE_PARITY",
            "exitPlan": {"stopPoints": 10.0, "adaptiveStop": True},
        },
    )
    assert should_trade_use_adaptive_stop(trade, s) is True
    trade.entryContext["executionMode"] = "LIVE"
    assert should_trade_use_adaptive_stop(trade, s) is True


def test_evaluate_explosion_exit_uses_adaptive_stop_from_plan():
    s = Settings()
    s.adaptive_exits_enabled = True
    s.explosion_stop_min_hold_seconds = 0
    s.executed_entry_sl_only_loss_exits = True
    s.explosion_peak_fade_lock_enabled = False
    s.explosion_peak_capture_enabled = False
    s.explosion_no_progress_enabled = False
    trade = PaperTrade(
        id="t2",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22700.0,
        entryPremium=50.0,
        currentPremium=43.0,
        lots=2,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST) - timedelta(seconds=120),
        bestPnlPoints=0.0,
        entryContext={
            "exitPlan": {
                "stopPoints": 6.0,
                "entryStopPoints": 6.0,
                "adaptiveStop": True,
            },
        },
    )
    with (
        patch("app.engines.explosion_profit.get_settings", return_value=s),
        patch("app.engines.adaptive_exits.get_settings", return_value=s),
        patch("app.engines.explosion_profit._hold_seconds", return_value=120.0),
        patch("app.engines.explosion_profit._executed_entry_min_hold_before_loss", return_value=0),
    ):
        reason, _ = evaluate_explosion_exit(trade, 43.0, "ELITE", 75, live_velocity_3s=-0.5)
    assert reason == "adaptive_stop_loss"


def test_ensure_open_trade_exit_plan_persists_on_trade():
    trade = PaperTrade(
        id="adopt",
        symbol="NIFTY",
        side=Side.PUT,
        strike=22700.0,
        entryPremium=100.0,
        currentPremium=100.0,
        lots=1,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST),
        entryContext={"brokerAdopted": True, "executionMode": "LIVE"},
    )
    snap = _snap()
    with patch("app.engines.adaptive_exits.get_settings") as mock_gs:
        s = Settings()
        s.adaptive_exits_enabled = True
        mock_gs.return_value = s
        with patch(
            "app.engines.adaptive_exits.build_merged_adaptive_exit_plan",
            return_value={"stopPoints": 14.0, "adaptiveStop": True},
        ):
            plan = ensure_open_trade_exit_plan(trade, snap)
    assert plan["stopPoints"] == 14.0
    assert trade.entryContext["exitPlan"]["adaptiveStop"] is True
