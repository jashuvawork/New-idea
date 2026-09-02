"""Aug26 afternoon — SENSEX deep ITM PUT 78200–78400 detection gap."""

from unittest.mock import MagicMock, patch

from app.engines.explosion_detector import (
    _premium_ok_for_scan,
    reset_detector_state_for_tests,
    resolve_explosion_scan_range,
    scan_chain_explosions,
)
from app.models.schemas import Side


def _settings(*, atm_itm_only: bool = True) -> MagicMock:
    s = MagicMock()
    s.explosion_scan_range = 800
    s.explosion_sensex_scan_range = 1500
    s.explosion_sensex_worst_day_scan_range = 500
    s.explosion_worst_day_scan_range = 500
    s.expiry_itm_monitor_enabled = True
    s.expiry_sensex_itm_scan_range = 1200
    s.expiry_itm_scan_range = 800
    s.min_option_premium_inr = 18.0
    s.explosion_max_premium_inr = 650.0
    s.max_option_premium_inr = 300.0
    s.explosion_ict_max_premium_inr = 800.0
    s.expiry_itm_explosion_scan_max_premium_inr = 900.0
    s.expiry_day_min_option_premium_inr = 15.0
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
    s.explosion_cheap_rip_min_premium_inr = 12.0
    s.explosion_cheap_rip_min_peak_pct = 28.0
    s.expiry_atm_tier_velocity_mult = 1.0
    return s


def test_expiry_day_scan_uses_1200pt_even_when_session_cache_off():
    s = _settings()
    with patch(
        "app.engines.expiry_day_guards.any_expiry_session_active",
        return_value=False,
    ):
        assert resolve_explosion_scan_range("SENSEX", s, expiry_day=True) == 1200
        assert resolve_explosion_scan_range("SENSEX", s, expiry_day=False) >= 1500


def test_expiry_day_scan_covers_78200_put_when_atm_77600():
    """78200 is 600pt from ATM — inside 1200, outside 500 worst-day clamp."""
    s = _settings()
    with patch(
        "app.engines.expiry_day_guards.any_expiry_session_active",
        return_value=False,
    ):
        tight = resolve_explosion_scan_range("SENSEX", s, tight_scan=True)
        expiry = resolve_explosion_scan_range("SENSEX", s, expiry_day=True)
    assert tight == 1200  # ITM monitor on
    # Simulate worst-day fallback when monitor off
    s.expiry_itm_monitor_enabled = False
    with patch(
        "app.engines.expiry_day_guards.any_expiry_session_active",
        return_value=True,
    ):
        worst = resolve_explosion_scan_range("SENSEX", s, tight_scan=True)
        expiry = resolve_explosion_scan_range("SENSEX", s, expiry_day=True)
    assert worst == 500
    assert expiry == 500  # monitor off → same fallback
    assert abs(78200 - 77600) > worst
    assert abs(78200 - 77600) <= 1200


def test_deep_itm_premium_allowed_on_expiry_scan():
    s = _settings()
    # ₹720 resting LTP — above ₹650 explosion max, allowed on expiry ITM scan only.
    assert _premium_ok_for_scan(
        720.0, 5.0, s, expiry_day=True, moneyness="ITM",
    ) is True
    assert _premium_ok_for_scan(
        720.0, 5.0, s, expiry_day=False, moneyness="ITM",
    ) is False


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
@patch("app.config.get_settings")
def test_scan_chain_detects_deep_itm_puts_on_expiry_day(mock_get_settings, _open):
    """Aug26 geometry: ATM 77600, deep ITM PUT 78200–78400 must enter scan on expiry."""
    reset_detector_state_for_tests()
    mock_get_settings.return_value = _settings()

    chain = [
        {"strike_price": 77600, "put_options": {"ltp": 180.0, "volume": 50000}, "call_options": {"ltp": 140.0, "volume": 80000}},
        {"strike_price": 77800, "put_options": {"ltp": 220.0, "volume": 45000}, "call_options": {"ltp": 120.0, "volume": 70000}},
        {"strike_price": 78200, "put_options": {"ltp": 420.0, "volume": 35000}, "call_options": {"ltp": 80.0, "volume": 20000}},
        {"strike_price": 78300, "put_options": {"ltp": 510.0, "volume": 30000}, "call_options": {"ltp": 65.0, "volume": 15000}},
        {"strike_price": 78400, "put_options": {"ltp": 600.0, "volume": 28000}, "call_options": {"ltp": 55.0, "volume": 12000}},
    ]

    # Seed history
    scan_chain_explosions("SENSEX", chain, spot=77600.0, atm=77600.0, expiry_day=True)

    # Afternoon vertical on deep ITM puts
    chain[2]["put_options"]["ltp"] = 590.0
    chain[3]["put_options"]["ltp"] = 710.0
    chain[4]["put_options"]["ltp"] = 840.0

    events = scan_chain_explosions(
        "SENSEX", chain, spot=77600.0, atm=77600.0, expiry_day=True,
    )
    put_strikes = {e.strike for e in events if e.side == Side.PUT}
    assert 78200.0 in put_strikes, "78200 PE must be scanned on expiry day"
    assert 78300.0 in put_strikes, "78300 PE must be scanned on expiry day"
    assert 78400.0 in put_strikes, "78400 PE must be scanned on expiry day"


@patch("app.engines.session_timing.in_open_premium_window", return_value=False)
@patch("app.config.get_settings")
def test_scan_chain_clips_deep_itm_when_not_expiry_day(mock_get_settings, _open):
    """Without expiry_day flag, 78200+ must not appear when tight_scan uses 500pt."""
    reset_detector_state_for_tests()
    s = _settings()
    s.expiry_itm_monitor_enabled = False
    mock_get_settings.return_value = s

    chain = [
        {"strike_price": 77600, "put_options": {"ltp": 180.0, "volume": 50000}, "call_options": {"ltp": 140.0, "volume": 80000}},
        {"strike_price": 78200, "put_options": {"ltp": 420.0, "volume": 35000}, "call_options": {"ltp": 80.0, "volume": 20000}},
    ]

    with patch(
        "app.engines.expiry_day_guards.any_expiry_session_active",
        return_value=True,
    ):
        scan_chain_explosions("SENSEX", chain, spot=77600.0, atm=77600.0, expiry_day=False)
        chain[1]["put_options"]["ltp"] = 590.0
        events = scan_chain_explosions(
            "SENSEX", chain, spot=77600.0, atm=77600.0, expiry_day=False,
        )

    put_strikes = {e.strike for e in events if e.side == Side.PUT}
    assert 78200.0 not in put_strikes
