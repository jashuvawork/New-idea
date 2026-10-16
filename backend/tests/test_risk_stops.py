"""Risk stop helpers."""

from unittest.mock import MagicMock

from app.engines.risk_stops import live_hold_to_structural_sl


def test_live_hold_ignored_for_magic_mock_settings():
    s = MagicMock()
    assert live_hold_to_structural_sl(s) is False


def test_live_hold_when_explicitly_enabled():
    s = MagicMock()
    s.enable_live_trading = True
    s.auto_trading_enabled = True
    s.live_hold_to_structural_sl = True
    assert live_hold_to_structural_sl(s) is True


def test_live_hold_off_when_auto_trading_disabled():
    s = MagicMock()
    s.enable_live_trading = True
    s.auto_trading_enabled = False
    s.live_hold_to_structural_sl = True
    assert live_hold_to_structural_sl(s) is False
