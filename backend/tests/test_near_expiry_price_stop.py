"""0–1 DTE planned stop fires on price, not after 300–900s defer (CE/PE)."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.explosion_profit import (
    ExplosionExitParams,
    _defer_adaptive_stop,
    _executed_entry_min_hold_before_loss,
    _never_green_min_hold_seconds,
    evaluate_explosion_exit,
    near_expiry_price_stop_active,
    trade_option_dte_days,
)
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _expiry_trade(
    side: Side,
    *,
    expiry: str = "2026-11-26",
    session: str = "2026-11-26",
    tier: str = "ELITE",
) -> PaperTrade:
    return PaperTrade(
        id=f"dte-{side.value}",
        symbol="SENSEX",
        side=side,
        strike=84400.0,
        entryPremium=232.0,
        currentPremium=192.0,
        lots=11,
        openedAt=datetime(2026, 11, 26, 11, 17, 2, tzinfo=IST),
        strategyType=StrategyType.EXPLOSIVE,
        bestPnlPoints=0.0,
        sessionDate=session,
        entryContext={
            "selectionMode": "explosion",
            "explosionTier": tier,
            "optionExpiry": expiry,
            "sessionDate": session,
            "exitPlan": {"stopPoints": 40.0, "entryStopPoints": 40.0, "adaptiveStop": True},
        },
    )


def _settings() -> Settings:
    return Settings(
        near_expiry_price_stop_enabled=True,
        near_expiry_price_stop_max_dte_days=1,
        near_expiry_price_stop_min_hold_seconds=15.0,
        near_expiry_price_stop_breach_ratio=1.0,
        never_green_hard_stop_enabled=True,
        never_green_hard_stop_min_hold_seconds=300.0,
        never_green_hard_stop_elite_min_hold_seconds=900.0,
        executed_entry_min_hold_before_loss_seconds=300,
        executed_entry_elite_min_hold_before_loss_seconds=600,
        executed_entry_sl_only_loss_exits=True,
        explosion_stop_min_hold_seconds=120,
    )


def test_trade_option_dte_zero_and_one():
    t0 = _expiry_trade(Side.CALL, expiry="2026-11-26", session="2026-11-26")
    assert trade_option_dte_days(t0) == 0
    t1 = _expiry_trade(Side.PUT, expiry="2026-11-27", session="2026-11-26")
    assert trade_option_dte_days(t1) == 1
    t2 = _expiry_trade(Side.CALL, expiry="2026-11-28", session="2026-11-26")
    assert trade_option_dte_days(t2) == 2


def test_near_expiry_shortens_min_hold_ce_pe():
    s = _settings()
    for side in (Side.CALL, Side.PUT):
        trade = _expiry_trade(side)
        assert near_expiry_price_stop_active(trade, settings=s)
        assert _executed_entry_min_hold_before_loss(trade, settings=s) == 15
        assert _never_green_min_hold_seconds(trade, s) == 15.0


def test_far_expiry_keeps_elite_never_green_min_hold():
    trade = _expiry_trade(Side.CALL, expiry="2026-11-30", session="2026-11-26")
    s = _settings()
    assert not near_expiry_price_stop_active(trade, settings=s)
    assert _never_green_min_hold_seconds(trade, s) == 900.0


def test_defer_adaptive_stop_off_after_breach_on_0_dte():
    trade = _expiry_trade(Side.CALL)
    s = _settings()
    assert not _defer_adaptive_stop(
        trade, best=0.0, hold=20.0, settings=s, pnl_pts=-40.0, stop_floor=40.0,
    )
    assert _defer_adaptive_stop(
        trade, best=0.0, hold=10.0, settings=s, pnl_pts=-35.0, stop_floor=40.0,
    )


def test_adaptive_stop_at_planned_pts_not_600s_on_expiry_day():
    trade = _expiry_trade(Side.CALL)
    settings = _settings()
    params = ExplosionExitParams(
        stop_points=40.0,
        target_points=80.0,
        trail_arm_points=8.0,
        trail_keep_ratio=0.75,
        adaptive_stop=True,
    )
    with patch("app.engines.explosion_profit._hold_seconds", return_value=300.0):
        with patch("app.engines.explosion_profit.get_settings", return_value=settings):
            reason, pnl = evaluate_explosion_exit(
                trade,
                192.0,
                "ELITE",
                lot_multiplier=20,
                params=params,
                live_velocity_3s=-0.5,
            )
    assert reason in ("adaptive_stop_loss", "explosion_never_green_hard_stop")
    assert pnl < 0


def test_never_green_hard_stop_on_expiry_before_legacy_900s():
    trade = _expiry_trade(Side.PUT)
    settings = _settings()
    params = ExplosionExitParams(
        stop_points=40.0,
        target_points=80.0,
        trail_arm_points=8.0,
        trail_keep_ratio=0.75,
        adaptive_stop=False,
    )
    with patch("app.engines.explosion_profit._hold_seconds", return_value=20.0):
        with patch("app.engines.explosion_profit.get_settings", return_value=settings):
            reason, _ = evaluate_explosion_exit(
                trade,
                192.0,
                "ELITE",
                lot_multiplier=20,
                params=params,
                live_velocity_3s=-0.5,
            )
    assert reason == "explosion_never_green_hard_stop"