"""Full live ↔ paper parity flag."""

from unittest.mock import MagicMock, patch

from app.engines.live_paper_parity import live_paper_parity_active
from app.engines.risk_stops import live_hold_to_structural_sl


def test_live_paper_parity_active_from_either_flag():
    s = MagicMock(live_paper_parity_enabled=True, live_trade_selection_parity_with_paper=False)
    assert live_paper_parity_active(s) is True
    s2 = MagicMock(live_paper_parity_enabled=False, live_trade_selection_parity_with_paper=True)
    assert live_paper_parity_active(s2) is True


def test_live_hold_to_structural_sl_off_under_parity():
    s = MagicMock(
        enable_live_trading=True,
        auto_trading_enabled=True,
        live_hold_to_structural_sl=True,
        live_paper_parity_enabled=True,
        live_trade_selection_parity_with_paper=False,
    )
    with patch("app.engines.live_paper_parity.live_paper_parity_active", return_value=True):
        assert live_hold_to_structural_sl(s) is False
