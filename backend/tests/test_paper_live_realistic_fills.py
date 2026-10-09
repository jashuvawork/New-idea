"""Paper-live parity sim uses optional MARKET % slippage (PnL observability)."""

from app.engines.paper_slippage import apply_entry_fill, apply_exit_mark
from app.models.schemas import StrategyType
from tests.mock_defaults import settings_mock


def test_parity_realistic_entry_fill_worse_than_points_only():
    s = settings_mock(
        paper_slippage_enabled=True,
        paper_slippage_entry_points=0.0,
        paper_live_parity_enabled=True,
        paper_simulate_broker_orders=True,
        paper_live_parity_realistic_fills=True,
        paper_live_parity_market_slippage_pct=0.5,
    )
    from app.config import get_settings
    from unittest.mock import patch

    with patch("app.engines.paper_slippage.get_settings", return_value=s):
        fill, meta = apply_entry_fill(100.0, StrategyType.EXPLOSIVE, tier="ELITE")
    assert fill >= 100.5
    assert meta.get("parityRealisticFill") is True


def test_parity_realistic_exit_below_mark():
    s = settings_mock(
        paper_slippage_enabled=False,
        paper_live_parity_enabled=True,
        paper_simulate_broker_orders=True,
        paper_live_parity_realistic_fills=True,
        paper_live_parity_exit_slippage_pct=1.0,
    )
    from unittest.mock import patch

    with patch("app.engines.paper_slippage.get_settings", return_value=s):
        exit_fill = apply_exit_mark(100.0, StrategyType.EXPLOSIVE)
    assert exit_fill <= 99.0
