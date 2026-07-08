"""Explosion scan range — deep OTM SENSEX PE coverage."""

from unittest.mock import MagicMock, patch

from app.engines.explosion_detector import (
    _premium_ok_for_scan,
    resolve_explosion_scan_range,
    scan_chain_explosions,
)
from app.models.schemas import Side


def _settings() -> MagicMock:
    s = MagicMock()
    s.explosion_scan_range = 800
    s.explosion_sensex_scan_range = 1500
    s.min_option_premium_inr = 20.0
    s.explosion_max_premium_inr = 500.0
    s.max_option_premium_inr = 175.0
    s.all_day_explosion_session_move_min_pct = 40.0
    s.open_premium_min_move_pct = 25.0
    s.explosion_deep_otm_min_premium_inr = 3.0
    s.open_premium_explosion_enabled = True
    s.all_day_explosion_min_score = 45.0
    s.explosion_exhaustion_v15_pct = 18.0
    return s


def test_sensex_scan_range_covers_76500_pe():
    s = _settings()
    assert resolve_explosion_scan_range("SENSEX", s) >= 1500


def test_deep_otm_premium_bypass_on_session_move():
    s = _settings()
    assert _premium_ok_for_scan(12.0, 4808.0, s) is True
    assert _premium_ok_for_scan(2.0, 4808.0, s) is False


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
@patch("app.config.get_settings")
def test_scan_chain_includes_deep_otm_sensex_pe(mock_get_settings, _open):
    mock_get_settings.return_value = _settings()

    chain = [
        {
            "strike_price": 76500,
            "put_options": {"ltp": 8.0, "volume": 1000},
            "call_options": {"ltp": 5.0, "volume": 100},
        },
        {
            "strike_price": 77600,
            "put_options": {"ltp": 180.0, "volume": 50000},
            "call_options": {"ltp": 140.0, "volume": 80000},
        },
    ]
    scan_chain_explosions("SENSEX", chain, spot=77600.0, atm=77600.0)
    chain[0]["put_options"]["ltp"] = 392.65
    chain[0]["put_options"]["volume"] = 2_300_000
    events = scan_chain_explosions("SENSEX", chain, spot=77600.0, atm=77600.0)
    puts = [e for e in events if e.side == Side.PUT and e.strike == 76500]
    assert puts, "76500 PE should be scanned within 1500pt SENSEX range"
