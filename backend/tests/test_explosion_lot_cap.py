"""Explosion lot cap for expensive premiums."""

from unittest.mock import MagicMock, patch

from app.engines.explosion_profit import cap_explosion_lots


@patch("app.engines.explosion_profit.get_settings")
def test_cap_explosion_lots_high_premium(mock_settings):
    s = MagicMock()
    s.explosion_high_premium_threshold_inr = 90.0
    s.explosion_high_premium_lot_cap = 10
    mock_settings.return_value = s
    assert cap_explosion_lots(16, 126.9) == 10
    assert cap_explosion_lots(16, 75.0) == 16
