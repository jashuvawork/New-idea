"""Daily 18% capital strategy."""

from unittest.mock import patch

from app.engines.daily_18pct_strategy import (
    compute_trading_limits,
    entries_allowed_by_limits,
    resolve_daily_target_inr,
    scale_lots_for_limits,
    TradingLimits,
)
from app.models.schemas import AutoTraderState


def _settings():
    from unittest.mock import MagicMock
    s = MagicMock()
    s.daily_profit_target_from_capital = True
    s.daily_profit_target_pct = 0.18
    s.daily_profit_target_inr = 44_000
    s.daily_18pct_strategy_enabled = True
    s.daily_18pct_medium_confidence_min = 55
    s.daily_18pct_high_confidence_min = 72
    s.daily_18pct_elite_confidence_min = 85
    s.daily_18pct_unlock_full_limits_min_confidence = 78
    s.daily_18pct_chop_max_trades = 10
    s.daily_18pct_expiry_max_trades = 5
    s.daily_18pct_expiry_min_rank = 65
    s.daily_18pct_full_limit_max_trades = 12
    s.quick_sideways_min_rank_score = 58
    s.quick_sideways_enabled = True
    s.best_trades_min_rank_score = 68
    s.pretrade_min_rank_score = 65
    s.controlled_max_trades_per_day = 6
    return s


@patch("app.engines.daily_18pct_strategy.get_settings", _settings)
def test_resolve_daily_target_18pct():
    assert resolve_daily_target_inr(200_000) == 36_000.0


@patch("app.engines.daily_18pct_strategy.get_settings", _settings)
def test_low_confidence_blocks_explosion():
    limits = TradingLimits(
        allowExplosion=False,
        minRankScore=58,
        maxTradesToday=8,
    )
    ok, reason = entries_allowed_by_limits(limits, "explosion", 75, 2)
    assert not ok
    assert "explosion" in reason


@patch("app.engines.daily_18pct_strategy.get_settings", _settings)
def test_scale_lots_reduced_without_full_unlock():
    limits = TradingLimits(lotSizeMultiplier=0.6, allowFullLots=False, unlockFullLimits=False)
    assert scale_lots_for_limits(100, limits) == 60


@patch("app.engines.daily_18pct_strategy.get_settings", _settings)
@patch("app.engines.daily_18pct_strategy.compute_market_confidence", return_value=(48.0, "CHOP DAY"))
def test_accumulate_phase_low_confidence(_conf):
    limits = compute_trading_limits({}, AutoTraderState(), session_pnl=5_000, capital_base=200_000)
    assert limits.phase == "ACCUMULATE"
    assert limits.confidenceTier == "LOW"
    assert limits.allowExplosion is False
    assert limits.allowQuickSideways is True
