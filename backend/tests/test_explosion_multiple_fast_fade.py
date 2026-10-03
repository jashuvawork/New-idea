"""N× entry touch (n > 1) + fast fade profit lock (Oct 1 NIFTY 22450 PE pattern)."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.explosion_profit import multiple_touch_fast_fade_exit_reason
from app.models.schemas import PaperTrade, Side, StrategyType
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _oct01_pe_trade(*, current: float, max_ltp: float = 223.65) -> PaperTrade:
    entry = 109.65
    return PaperTrade(
        id="e5822b71",
        symbol="NIFTY",
        side=Side.PUT,
        strike=22450.0,
        entryPremium=entry,
        currentPremium=current,
        lots=18,
        pnlInr=0,
        status="OPEN",
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime(2026, 10, 1, 14, 30, tzinfo=IST),
        maxLtp=max_ltp,
        entryContext={"explosionTier": "BUILDING"},
    )


def _call_trade(*, current: float, max_ltp: float = 225.0) -> PaperTrade:
    entry = 105.0
    return PaperTrade(
        id="ce-sym",
        symbol="NIFTY",
        side=Side.CALL,
        strike=22500.0,
        entryPremium=entry,
        currentPremium=current,
        lots=10,
        pnlInr=0,
        status="OPEN",
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime(2026, 10, 1, 10, 0, tzinfo=IST),
        maxLtp=max_ltp,
        entryContext={"explosionTier": "EXPLODING"},
    )


@patch("app.engines.explosion_profit._reversal_keep_rollover_confirmed", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
def test_oct01_fast_fade_exits_above_book_floor(mock_settings, _rollover):
    s = settings_mock(
        explosion_multiple_fast_fade_enabled=True,
        explosion_multiple_min_peak_giveback_points=3.0,
    )
    mock_settings.return_value = s
    trade = _oct01_pe_trade(current=220.0)
    best = trade.maxLtp - trade.entryPremium
    pnl = trade.currentPremium - trade.entryPremium
    reason = multiple_touch_fast_fade_exit_reason(
        trade,
        best=best,
        pnl_pts=pnl,
        current_premium=trade.currentPremium,
        live_velocity_3s=-3.0,
    )
    assert reason == "explosion_multiple_fast_fade_lock"
    assert trade.entryContext.get("multipleFastFadeArmed") is True


@patch("app.engines.explosion_profit._reversal_keep_rollover_confirmed", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
def test_nx_hot_velocity_defers(mock_settings, _rollover):
    mock_settings.return_value = settings_mock()
    trade = _oct01_pe_trade(current=220.0)
    best = trade.maxLtp - trade.entryPremium
    pnl = trade.currentPremium - trade.entryPremium
    reason = multiple_touch_fast_fade_exit_reason(
        trade,
        best=best,
        pnl_pts=pnl,
        current_premium=trade.currentPremium,
        live_velocity_3s=2.5,
    )
    assert reason is None


@patch("app.engines.explosion_profit.get_settings")
def test_never_reaches_2x_no_exit(mock_settings):
    mock_settings.return_value = settings_mock()
    trade = _oct01_pe_trade(current=140.0, max_ltp=150.0)
    best = trade.maxLtp - trade.entryPremium
    pnl = trade.currentPremium - trade.entryPremium
    reason = multiple_touch_fast_fade_exit_reason(
        trade,
        best=best,
        pnl_pts=pnl,
        current_premium=trade.currentPremium,
        live_velocity_3s=-3.0,
    )
    assert reason is None
    assert not trade.entryContext.get("multipleFastFadeArmed")


@patch("app.engines.explosion_profit._reversal_keep_rollover_confirmed", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
def test_below_book_floor_waits(mock_settings, _rollover):
    mock_settings.return_value = settings_mock()
    trade = _oct01_pe_trade(current=195.0)
    best = trade.maxLtp - trade.entryPremium
    pnl = trade.currentPremium - trade.entryPremium
    reason = multiple_touch_fast_fade_exit_reason(
        trade,
        best=best,
        pnl_pts=pnl,
        current_premium=trade.currentPremium,
        live_velocity_3s=-3.0,
    )
    assert reason is None


@patch("app.engines.explosion_profit._reversal_keep_rollover_confirmed", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
def test_ce_symmetry_same_math(mock_settings, _rollover):
    s = settings_mock(explosion_multiple_min_peak_giveback_points=3.0)
    mock_settings.return_value = s
    trade = _call_trade(current=212.0)
    best = trade.maxLtp - trade.entryPremium
    pnl = trade.currentPremium - trade.entryPremium
    reason = multiple_touch_fast_fade_exit_reason(
        trade,
        best=best,
        pnl_pts=pnl,
        current_premium=trade.currentPremium,
        live_velocity_3s=-2.5,
    )
    assert reason == "explosion_multiple_fast_fade_lock"


@patch("app.engines.explosion_profit._reversal_keep_rollover_confirmed", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
def test_4x_peak_ratchet_book_floor_not_2x_only(mock_settings, _rollover):
    """4× rip → fast fade books near 75% of peak LTP, not only min 2× entry."""
    entry = 100.0
    max_ltp = 400.0
    mock_settings.return_value = settings_mock(
        explosion_multiple_min_peak_giveback_points=10.0,
        explosion_multiple_book_peak_keep_ratio=0.75,
    )
    trade = PaperTrade(
        id="nx-4",
        symbol="NIFTY",
        side=Side.PUT,
        strike=23000.0,
        entryPremium=entry,
        currentPremium=305.0,
        lots=10,
        pnlInr=0,
        status="OPEN",
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime(2026, 10, 1, 11, 0, tzinfo=IST),
        maxLtp=max_ltp,
        entryContext={"explosionTier": "ELITE"},
    )
    best = max_ltp - entry
    pnl = trade.currentPremium - entry
    reason = multiple_touch_fast_fade_exit_reason(
        trade,
        best=best,
        pnl_pts=pnl,
        current_premium=trade.currentPremium,
        live_velocity_3s=-3.0,
    )
    assert reason == "explosion_multiple_fast_fade_lock"
    assert trade.entryContext.get("multipleFastFadePeakMultiple") == 4.0
    trade.currentPremium = 290.0
    reason_low = multiple_touch_fast_fade_exit_reason(
        trade,
        best=best,
        pnl_pts=190.0,
        current_premium=290.0,
        live_velocity_3s=-3.0,
    )
    assert reason_low is None


@patch("app.engines.explosion_profit._reversal_keep_rollover_confirmed", return_value=True)
@patch("app.engines.explosion_profit.get_settings")
def test_min_arm_ratio_3x_requires_3x_touch(mock_settings, _rollover):
    mock_settings.return_value = settings_mock(
        explosion_multiple_arm_ratio=3.0,
        explosion_multiple_min_peak_giveback_points=5.0,
    )
    entry = 100.0
    trade = PaperTrade(
        id="nx-3",
        symbol="NIFTY",
        side=Side.PUT,
        strike=23000.0,
        entryPremium=entry,
        currentPremium=250.0,
        lots=10,
        pnlInr=0,
        status="OPEN",
        strategyType=StrategyType.EXPLOSIVE,
        openedAt=datetime(2026, 10, 1, 11, 0, tzinfo=IST),
        maxLtp=250.0,
        entryContext={"explosionTier": "BUILDING"},
    )
    reason = multiple_touch_fast_fade_exit_reason(
        trade,
        best=150.0,
        pnl_pts=150.0,
        current_premium=250.0,
        live_velocity_3s=-3.0,
    )
    assert reason is None
    trade.maxLtp = 320.0
    trade.currentPremium = 308.0
    reason = multiple_touch_fast_fade_exit_reason(
        trade,
        best=220.0,
        pnl_pts=208.0,
        current_premium=308.0,
        live_velocity_3s=-3.0,
    )
    assert reason == "explosion_multiple_fast_fade_lock"
