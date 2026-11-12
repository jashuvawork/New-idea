"""NIFTY OOB fallback below ₹2L + premium-gated failed launch with SL-only."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings
from app.engines.capital_allocator import (
    effective_entry_symbols_with_snapshots,
    entry_symbol_allowed,
    sensex_has_in_band_explosion_alert,
)
from app.engines.explosion_profit import (
    evaluate_explosion_exit,
    explosion_failed_launch_exit_reason,
    sl_only_loss_exits_enabled,
)
from app.models.schemas import MarketPhase, PaperTrade, Side, StrategyType, SymbolSnapshot

IST = ZoneInfo("Asia/Kolkata")


def _sensex_snap(*, alerts: list[dict], premium_ok: bool) -> SymbolSnapshot:
    prem = 700.0 if not premium_ok else 120.0
    alert = {
        "lastPremium": prem,
        "peakMovePct": 40.0,
        "side": "CALL",
        "strike": 81900.0,
    }
    alerts_list = alerts if alerts is not None else [alert]
    return SymbolSnapshot(
        symbol="SENSEX",
        timestamp=datetime(2026, 11, 12, 9, 20, tzinfo=IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        spot=81900.0,
        dataAvailable=True,
        explosionAlerts=alerts_list,
    )


@patch("app.engines.capital_allocator.get_capital_snapshot")
def test_nifty_unlocked_when_sensex_explosion_oob(mock_cap):
    settings = Settings()
    settings.capital_tier_entry_symbols_enabled = True
    settings.capital_tier_nifty_oob_fallback_enabled = True
    settings.capital_tier_nifty_min_inr = 200_000
    mock_cap.return_value = type(
        "C",
        (),
        {"availableMarginInr": 35_000, "totalEquityInr": 35_000},
    )()
    snaps = {"SENSEX": _sensex_snap(alerts=[{"lastPremium": 700.0, "peakMovePct": 40.0}], premium_ok=False)}
    syms = effective_entry_symbols_with_snapshots(settings, snaps)
    assert syms == frozenset({"SENSEX", "NIFTY"})
    assert entry_symbol_allowed("NIFTY", settings, snapshots=snaps)[0] is True


@patch("app.engines.capital_allocator.get_capital_snapshot")
def test_nifty_blocked_when_sensex_has_in_band_alert(mock_cap):
    settings = Settings()
    settings.capital_tier_entry_symbols_enabled = True
    settings.capital_tier_nifty_oob_fallback_enabled = True
    mock_cap.return_value = type(
        "C",
        (),
        {"availableMarginInr": 35_000, "totalEquityInr": 35_000},
    )()
    snaps = {"SENSEX": _sensex_snap(alerts=[{"lastPremium": 120.0, "peakMovePct": 35.0}], premium_ok=True)}
    assert effective_entry_symbols_with_snapshots(settings, snaps) == frozenset({"SENSEX"})
    assert entry_symbol_allowed("NIFTY", settings, snapshots=snaps) == (
        False,
        "below_capital_tier_symbol_blocked",
    )


def test_sensex_in_band_detector_empty_alerts():
    snap = _sensex_snap(alerts=[], premium_ok=False)
    assert sensex_has_in_band_explosion_alert(snap, Settings()) is False


def _failed_launch_trade(*, hold_s: int = 70, bullish: bool = False):
    ctx = {}
    if not bullish:
        ctx["liveEntryScoreMeta"] = {
            "premiumDirection": "BEARISH",
            "premiumMomentum5Pct": -5.0,
        }
    else:
        ctx["liveEntryScoreMeta"] = {
            "premiumDirection": "BULLISH",
            "premiumMomentum5Pct": 8.0,
        }
    return PaperTrade(
        id="fl",
        symbol="SENSEX",
        side=Side.PUT,
        strike=81900.0,
        entryPremium=200.0,
        currentPremium=195.0,
        lots=4,
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime.now(IST) - timedelta(seconds=hold_s),
        bestPnlPoints=0.0,
        entryContext=ctx,
    )


def test_failed_launch_waits_one_minute():
    s = Settings()
    s.explosion_failed_launch_exit_enabled = True
    s.explosion_failed_launch_min_hold_seconds = 60
    trade = _failed_launch_trade(hold_s=45)
    assert (
        explosion_failed_launch_exit_reason(
            trade,
            hold_seconds=45,
            best_points=0.0,
            pnl_points=-5.0,
            live_velocity_3s=-1.0,
            settings=s,
        )
        is None
    )


def test_failed_launch_skips_when_premium_bullish():
    s = Settings()
    s.explosion_failed_launch_exit_enabled = True
    s.explosion_failed_launch_min_hold_seconds = 60
    trade = _failed_launch_trade(hold_s=70, bullish=True)
    assert (
        explosion_failed_launch_exit_reason(
            trade,
            hold_seconds=70,
            best_points=0.0,
            pnl_points=-5.0,
            live_velocity_3s=-1.0,
            settings=s,
        )
        is None
    )


def test_failed_launch_with_sl_only_enabled():
    s = Settings()
    s.executed_entry_sl_only_loss_exits = True
    s.explosion_failed_launch_exit_enabled = True
    s.explosion_failed_launch_allow_with_sl_only = True
    s.explosion_failed_launch_min_hold_seconds = 60
    s.explosion_failed_launch_max_hold_seconds = 180
    s.explosion_failed_launch_max_best_points = 4.0
    s.explosion_failed_launch_min_loss_points = 2.0
    s.explosion_failed_launch_max_velocity_3s = -0.5
    assert sl_only_loss_exits_enabled(s) is True
    trade = _failed_launch_trade(hold_s=70)
    with patch("app.engines.explosion_profit.get_settings", return_value=s):
        reason, _ = evaluate_explosion_exit(
            trade, 195.0, "ELITE", 20, live_velocity_3s=-1.0
        )
    assert reason == "explosion_failed_launch"
