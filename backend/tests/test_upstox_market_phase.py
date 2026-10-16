"""Market phase boundaries — live until the 15:45 broker last print."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings

IST = ZoneInfo("Asia/Kolkata")


@patch("app.config.get_settings")
def test_live_market_until_1544(mock_settings):
    from app.services.upstox import get_market_phase

    mock_settings.return_value = Settings(power_hour_end_hour=15, power_hour_end_minute=45)
    with patch("app.services.upstox.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 10, 1, 15, 44, tzinfo=IST)
        assert get_market_phase() == "LIVE_MARKET"


@patch("app.config.get_settings")
def test_post_market_from_1545(mock_settings):
    from app.services.upstox import get_market_phase

    mock_settings.return_value = Settings(power_hour_end_hour=15, power_hour_end_minute=45)
    with patch("app.services.upstox.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 10, 1, 15, 45, tzinfo=IST)
        assert get_market_phase() == "POST_MARKET"


def test_session_close_default_is_1545():
    assert Settings().power_hour_end_minute == 45
