"""Scalp hard lot ceiling — no more unlimited 24/25-lot scalps."""

from unittest.mock import MagicMock, patch

from app.engines.capital_allocator import compute_lots
from app.models.schemas import StrategyType


def _settings(**overrides):
    s = MagicMock()
    s.aggressive_lot_sizing = True
    s.max_lots_per_trade = 0
    s.scalp_max_lots = 10
    s.explosion_max_lots = 0
    s.min_lots_per_trade = 1
    s.simple_min_lots = 1
    s.per_trade_capital_pct = 0.95
    s.fallback_capital_inr = 200_000
    s.max_sizing_capital_inr = 200_000
    s.nifty_lot_size = 65
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@patch("app.engines.capital_allocator.max_lots_for_capital", return_value=24)
@patch("app.engines.capital_allocator.get_settings")
def test_scalp_hard_capped_at_10(mock_settings, _max):
    mock_settings.return_value = _settings()
    lots = compute_lots(
        "NIFTY", 121.0, 3.0, strategy_type=StrategyType.SCALP, confidence=90,
    )
    assert lots == 10


@patch("app.engines.capital_allocator.max_lots_for_capital", return_value=24)
@patch("app.engines.capital_allocator.get_settings")
def test_explosion_not_forced_to_scalp_cap(mock_settings, _max):
    mock_settings.return_value = _settings(explosion_max_lots=0)
    lots = compute_lots(
        "NIFTY", 121.0, 6.0, strategy_type=StrategyType.EXPLOSIVE, confidence=90,
        tier="ELITE",
    )
    assert lots == 24
