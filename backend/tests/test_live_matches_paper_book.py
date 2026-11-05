"""Live arming must use the same entry/exit/sizing book as paper — broker orders only."""

from types import SimpleNamespace
from unittest.mock import patch

from app.config import Settings
from app.engines.risk_stops import live_hold_to_structural_sl


def test_live_hold_structural_sl_off_by_default():
    assert live_hold_to_structural_sl(Settings()) is False
    live = Settings(enable_live_trading=True, auto_trading_enabled=True)
    assert live_hold_to_structural_sl(live) is False


def test_chop_live_entry_not_forced_on_live_non_chop_day():
    """Regression: live must not run chop_live entry guards on calm days (paper does not)."""
    from app.engines import auto_trader

    source = auto_trader.__file__
    with open(source, encoding="utf-8") as f:
        blob = f.read()
    assert "is_live or chop_live_guard_day_active" not in blob
    assert "chop_live_guard_day_active(" in blob


def test_should_not_use_broker_capital_when_live_matches_paper():
    from app.engines.capital_allocator import should_use_live_broker_capital

    s = Settings(
        enable_live_trading=True,
        use_upstox_capital_for_sizing=False,
    )
    with patch("app.engines.capital_allocator.get_settings", return_value=s):
        assert should_use_live_broker_capital() is False
