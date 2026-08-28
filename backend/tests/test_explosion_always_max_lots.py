"""Explosion entries must use capital max lots — no 3/6-lot throttles."""

from unittest.mock import MagicMock, patch

from app.engines.capital_allocator import apply_explosion_always_max_lots
from app.engines.session_mode_feedback import cap_lots_until_first_green
from app.models.schemas import AutoTraderState


@patch("app.engines.capital_allocator.get_settings")
@patch("app.engines.capital_allocator.max_lots_for_capital", return_value=42)
def test_apply_explosion_always_max_lots_floors(_max, mock_settings):
    s = MagicMock()
    s.explosion_always_force_max_lots = True
    mock_settings.return_value = s
    assert apply_explosion_always_max_lots(6, "NIFTY", 61.0, mode="explosion") == 42
    assert apply_explosion_always_max_lots(6, "NIFTY", 61.0, mode="scalp") == 6


@patch("app.engines.capital_allocator.get_settings")
@patch("app.engines.capital_allocator.max_lots_for_capital", return_value=42)
def test_apply_respects_disabled_flag(_max, mock_settings):
    s = MagicMock()
    s.explosion_always_force_max_lots = False
    mock_settings.return_value = s
    assert apply_explosion_always_max_lots(6, "NIFTY", 61.0, mode="explosion") == 6


@patch("app.engines.session_mode_feedback.get_settings")
def test_first_green_skipped_when_always_max_config(mock_settings):
    s = MagicMock()
    s.size_until_first_green_enabled = True
    s.size_until_first_green_lot_cap = 6
    s.size_until_first_green_modes_csv = "explosion,scalp"
    s.explosion_always_force_max_lots = True
    mock_settings.return_value = s
    state = AutoTraderState()
    # When always-max bypasses first-green in auto_trader, cap helper still caps if called.
    assert cap_lots_until_first_green(40, state, mode="explosion") == 6
