"""#676 live guards: never-green hard stop at 300s, reentry velocity after a win."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.explosion_profit import ExplosionExitParams, evaluate_explosion_exit
from app.engines.session_mode_feedback import win_reentry_velocity_blocked
from app.models.schemas import AutoTraderState, PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _never_green_trade(side: Side, *, best: float) -> PaperTrade:
    return PaperTrade(
        id=f"ng-{side.value}",
        symbol="SENSEX",
        side=side,
        strike=72400.0,
        entryPremium=100.0,
        currentPremium=70.0,
        lots=10,
        openedAt=datetime(2026, 10, 1, 9, 38, tzinfo=IST),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=best,
        entryContext={
            "selectionMode": "explosion",
            "explosionTier": "ELITE",
            "eliteAssessment": {"eliteScore": 92.0},
            "exitPlan": {"stopPoints": 20.0, "adaptiveStop": True},
        },
    )


def _settings() -> Settings:
    return Settings(
        never_green_hard_stop_enabled=True,
        never_green_hard_stop_min_hold_seconds=300.0,
        never_green_hard_stop_max_best_pct=2.0,
        executed_entry_sl_only_loss_exits=True,
        win_reentry_requires_velocity_enabled=True,
        explosion_post_peak_reentry_min_velocity_3s=1.5,
    )


def _exit(side: Side, *, hold: float, best: float, premium: float):
    trade = _never_green_trade(side, best=best)
    settings = _settings()
    with patch("app.engines.explosion_profit._hold_seconds", return_value=hold):
        with patch("app.engines.explosion_profit.get_settings", return_value=settings):
            return evaluate_explosion_exit(
                trade,
                premium,
                "ELITE",
                lot_multiplier=20,
                params=ExplosionExitParams(
                    stop_points=20.0,
                    target_points=40.0,
                    trail_arm_points=8.0,
                    trail_keep_ratio=0.75,
                    adaptive_stop=True,
                ),
                live_velocity_3s=-0.4,
            )


def test_never_green_hard_stop_fires_at_300s_for_put_and_call():
    for side in (Side.PUT, Side.CALL):
        reason, pnl = _exit(side, hold=300, best=0.0, premium=70.0)
        assert reason == "explosion_never_green_hard_stop"
        assert pnl < 0


def test_never_green_hard_stop_waits_out_299s():
    reason, _pnl = _exit(Side.PUT, hold=299, best=0.0, premium=70.0)
    assert reason != "explosion_never_green_hard_stop"


def test_never_green_hard_stop_leaves_a_green_trade():
    reason, _pnl = _exit(Side.CALL, hold=400, best=12.0, premium=70.0)
    assert reason != "explosion_never_green_hard_stop"


def _winner(side: Side) -> PaperTrade:
    closed = datetime.now(IST) - timedelta(minutes=11)
    return PaperTrade(
        id=f"win-{side.value}",
        symbol="SENSEX",
        side=side,
        strike=71500.0,
        entryPremium=143.0,
        currentPremium=177.0,
        lots=20,
        openedAt=closed - timedelta(minutes=13),
        closedAt=closed,
        status="CLOSED",
        exitReason="explosion_peak_keep_trail",
        strategyType=StrategyType.EXPLOSIVE,
        pnlInr=40_000.0,
        bestPnlPoints=45.0,
        entryContext={"selectionMode": "explosion"},
    )


def test_reentry_after_win_requires_velocity_on_both_sides():
    settings = _settings()
    for side in (Side.PUT, Side.CALL):
        state = AutoTraderState(closedPaperTrades=[_winner(side)])
        with patch("app.engines.session_mode_feedback.get_settings", return_value=settings):
            blocked, reason = win_reentry_velocity_blocked(
                state,
                symbol="SENSEX",
                side=side,
                strike=71500.0,
                velocity_3s=0.2,
            )
            allowed, _ = win_reentry_velocity_blocked(
                state,
                symbol="SENSEX",
                side=side,
                strike=71500.0,
                velocity_3s=1.5,
            )
        assert blocked is True
        assert reason.startswith("win_reentry_velocity_")
        assert allowed is False


def test_reentry_velocity_does_not_block_after_a_loss():
    settings = _settings()
    loser = _winner(Side.PUT)
    loser.pnlInr = -36_000.0
    state = AutoTraderState(closedPaperTrades=[loser])
    with patch("app.engines.session_mode_feedback.get_settings", return_value=settings):
        blocked, reason = win_reentry_velocity_blocked(
            state,
            symbol="SENSEX",
            side=Side.PUT,
            strike=71500.0,
            velocity_3s=0.0,
        )
    assert blocked is False
    assert reason == ""
