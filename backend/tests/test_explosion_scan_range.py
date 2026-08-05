"""Explosion scan range — ATM/ITM-only monitoring + premium band."""

from unittest.mock import MagicMock, patch

from app.engines.explosion_detector import (
    _premium_ok_for_scan,
    resolve_explosion_scan_range,
    reset_detector_state_for_tests,
    scan_chain_explosions,
)
from app.models.schemas import Side


def _settings(*, atm_itm_only: bool = True) -> MagicMock:
    s = MagicMock()
    s.explosion_scan_range = 800
    s.explosion_sensex_scan_range = 1500
    s.min_option_premium_inr = 18.0
    s.explosion_max_premium_inr = 500.0
    s.max_option_premium_inr = 175.0
    s.all_day_explosion_session_move_min_pct = 40.0
    s.open_premium_min_move_pct = 25.0
    s.explosion_deep_otm_min_premium_inr = 18.0
    s.explosion_scan_atm_itm_only = atm_itm_only
    s.open_premium_explosion_enabled = True
    s.all_day_explosion_min_score = 45.0
    s.explosion_exhaustion_v15_pct = 18.0
    s.moneyness_atm_tolerance_points = 50.0
    s.nifty_strike_step = 50.0
    s.sensex_strike_step = 100.0
    s.banknifty_strike_step = 100.0
    s.explosion_cheap_rip_min_premium_inr = 18.0
    s.explosion_cheap_rip_min_peak_pct = 25.0
    s.expiry_day_min_option_premium_inr = 15.0
    return s


def test_sensex_scan_range_covers_76500_pe():
    s = _settings()
    assert resolve_explosion_scan_range("SENSEX", s) >= 1500


def test_deep_otm_premium_bypass_disabled_when_atm_itm_only():
    s = _settings(atm_itm_only=True)
    # Sub-band premiums never scan when ATM+ITM-only is on.
    assert _premium_ok_for_scan(12.0, 4808.0, s) is False
    assert _premium_ok_for_scan(2.0, 4808.0, s) is False


def test_deep_otm_premium_bypass_when_legacy_scan_enabled():
    s = _settings(atm_itm_only=False)
    s.explosion_deep_otm_min_premium_inr = 3.0
    assert _premium_ok_for_scan(12.0, 4808.0, s) is True
    assert _premium_ok_for_scan(2.0, 4808.0, s) is False


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
@patch("app.config.get_settings")
def test_scan_chain_skips_deep_otm_when_atm_itm_only(mock_get_settings, _open):
    """Aug5: deep OTM 24050-style noise must not dominate radar over ATM/ITM."""
    reset_detector_state_for_tests()
    mock_get_settings.return_value = _settings(atm_itm_only=True)

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
    assert not puts, "Deep OTM 76500 PE must be excluded from ATM+ITM-only scan"


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
@patch("app.config.get_settings")
def test_scan_chain_keeps_atm_itm_with_premium_band(mock_get_settings, _open):
    reset_detector_state_for_tests()
    mock_get_settings.return_value = _settings(atm_itm_only=True)

    # NIFTY ATM 24500 PUT + ITM 24550 PUT + OTM 24400 PUT
    chain = [
        {
            "strike_price": 24400,
            "put_options": {"ltp": 40.0, "volume": 100_000},
            "call_options": {"ltp": 80.0, "volume": 10_000},
        },
        {
            "strike_price": 24500,
            "put_options": {"ltp": 70.0, "volume": 200_000},
            "call_options": {"ltp": 55.0, "volume": 50_000},
        },
        {
            "strike_price": 24550,
            "put_options": {"ltp": 95.0, "volume": 180_000},
            "call_options": {"ltp": 40.0, "volume": 40_000},
        },
    ]
    # Seed history then rip ATM/ITM
    scan_chain_explosions("NIFTY", chain, spot=24500.0, atm=24500.0)
    chain[1]["put_options"]["ltp"] = 88.0
    chain[2]["put_options"]["ltp"] = 120.0
    chain[0]["put_options"]["ltp"] = 55.0
    events = scan_chain_explosions("NIFTY", chain, spot=24500.0, atm=24500.0)
    put_strikes = {e.strike for e in events if e.side == Side.PUT}
    assert 24400.0 not in put_strikes, "OTM PUT must be excluded"
    assert 24500.0 in put_strikes or 24550.0 in put_strikes, "ATM/ITM PUT should scan"
