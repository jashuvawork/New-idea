"""Market phase boundaries — aligned with power_hour_end / Upstox LTP tail."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.config import Settings

IST = ZoneInfo("Asia/Kolkata")


@patch("app.config.get_settings")
def test_live_market_until_1535(mock_settings):
    from app.services.upstox import get_market_phase

    mock_settings.return_value = Settings(power_hour_end_hour=15, power_hour_end_minute=35)
    with patch("app.services.upstox.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 10, 1, 15, 34, tzinfo=IST)
        assert get_market_phase() == "LIVE_MARKET"


@patch("app.config.get_settings")
def test_post_market_from_1535(mock_settings):
    from app.services.upstox import get_market_phase

    mock_settings.return_value = Settings(power_hour_end_hour=15, power_hour_end_minute=35)
    with patch("app.services.upstox.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 10, 1, 15, 35, tzinfo=IST)
        assert get_market_phase() == "POST_MARKET"
