"""Loss-recovery snatch — bank small green after underwater bounce, before next fade."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.engines.explosion_profit import loss_recovery_entry_snatch_reason
from app.models.schemas import PaperTrade, Side, StrategyType

IST = ZoneInfo("Asia/Kolkata")


def _settings(**overrides):
    s = MagicMock()
    s.explosion_loss_recovery_snatch_enabled = True
    s.explosion_loss_recovery_min_underwater_pts = 8.0
    s.explosion_loss_recovery_profit_min_pts = 0.35
    s.explosion_loss_recovery_profit_max_pts = 9.0
    s.explosion_loss_recovery_max_velocity_3s = 0.25
    s.explosion_loss_recovery_min_hold_seconds = 45.0
    s.explosion_loss_recovery_skip_max_profit = True
    s.explosion_peak_capture_max_live_velocity_3s = 1.0
    s.explosion_peak_capture_max_premium_mom_pct = 0.15
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _trade(*, entry: float = 232.0, worst: float = -18.0, ctx: dict | None = None) -> PaperTrade:
    base = {"executionChart": {"premiumChart": {"momentum3Pct": -0.4}}}
    if ctx:
        base.update(ctx)
    base["worstPnlPoints"] = worst
    return PaperTrade(
        id="loss-recovery-1",
        symbol="NIFTY",
        side=Side.CALL,
        strike=25750.0,
        entryPremium=entry,
        currentPremium=entry + 4.0,
        lots=1,
        openedAt=datetime.now(IST),
        strategyType=StrategyType.EXPLOSIVE,
        worstPnlPoints=worst,
        entryContext=base,
    )


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.explosion_profit._premium_rolling_over", return_value=True)
def test_snatch_when_underwater_revisit_fades(mock_roll, mock_gs):
    mock_gs.return_value = _settings()
    trade = _trade()
    reason = loss_recovery_entry_snatch_reason(
        trade, pnl_pts=4.0, hold_seconds=120.0, live_velocity_3s=-0.3
    )
    assert reason == "explosion_loss_recovery_snatch"


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.explosion_profit._premium_rolling_over", return_value=True)
def test_no_snatch_without_prior_underwater(mock_roll, mock_gs):
    mock_gs.return_value = _settings()
    trade = _trade(worst=-3.0)
    reason = loss_recovery_entry_snatch_reason(
        trade, pnl_pts=4.0, hold_seconds=120.0, live_velocity_3s=-0.3
    )
    assert reason is None


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.explosion_profit._premium_rolling_over", return_value=True)
def test_no_snatch_on_hot_velocity(mock_roll, mock_gs):
    mock_gs.return_value = _settings()
    trade = _trade()
    reason = loss_recovery_entry_snatch_reason(
        trade, pnl_pts=4.0, hold_seconds=120.0, live_velocity_3s=2.0
    )
    assert reason is None


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.explosion_profit._premium_rolling_over", return_value=False)
def test_no_snatch_without_rollover(mock_roll, mock_gs):
    mock_gs.return_value = _settings()
    trade = _trade()
    reason = loss_recovery_entry_snatch_reason(
        trade, pnl_pts=4.0, hold_seconds=120.0, live_velocity_3s=-0.3
    )
    assert reason is None


@patch("app.engines.explosion_profit.get_settings")
@patch("app.engines.explosion_profit._premium_rolling_over", return_value=True)
def test_put_side_symmetric(mock_roll, mock_gs):
    mock_gs.return_value = _settings()
    trade = _trade()
    trade.side = Side.PUT
    reason = loss_recovery_entry_snatch_reason(
        trade, pnl_pts=3.0, hold_seconds=90.0, live_velocity_3s=0.0
    )
    assert reason == "explosion_loss_recovery_snatch"