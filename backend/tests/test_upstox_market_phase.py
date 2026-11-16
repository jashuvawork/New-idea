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


def test_live_force_close_default_is_1535():
    s = Settings()
    assert s.live_session_close_force_exit_hour == 15
    assert s.live_session_close_force_exit_minute == 35


@patch("app.config.get_settings")
def test_equity_closed_commodity_live_evening(mock_settings):
    from app.services.upstox import get_market_phase, get_market_phase_for_symbol

    mock_settings.return_value = Settings(
        power_hour_end_hour=15,
        power_hour_end_minute=45,
        commodity_session_start_hour=9,
        commodity_session_start_minute=0,
        commodity_session_end_hour=23,
        commodity_session_end_minute=30,
    )
    with patch("app.services.upstox.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 10, 1, 20, 0, tzinfo=IST)
        assert get_market_phase() == "CLOSED"
        assert get_market_phase_for_symbol("NIFTY") == "CLOSED"
        assert get_market_phase_for_symbol("CRUDEOIL") == "LIVE_MARKET"


@patch("app.config.get_settings")
def test_commodity_closed_after_mcx_end(mock_settings):
    from app.services.upstox import get_market_phase_for_symbol

    mock_settings.return_value = Settings(
        commodity_session_end_hour=23,
        commodity_session_end_minute=30,
    )
    with patch("app.services.upstox.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 10, 1, 23, 31, tzinfo=IST)
        assert get_market_phase_for_symbol("NATURALGAS") == "CLOSED"


@patch("app.config.get_settings")
def test_effective_session_live_when_mcx_open(mock_settings):
    from app.services.upstox import effective_market_phase_for_session

    mock_settings.return_value = Settings(
        symbols_csv="NIFTY,SENSEX",
        commodity_symbols_csv="CRUDEOIL,NATURALGAS",
        commodity_session_end_hour=23,
        commodity_session_end_minute=30,
    )
    with patch("app.services.upstox.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 10, 1, 20, 0, tzinfo=IST)
        assert effective_market_phase_for_session() == "LIVE_MARKET"
