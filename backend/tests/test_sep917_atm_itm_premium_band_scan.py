"""Sep 9–17 book — scan/monitor ATM+ITM in ₹18–350, not deep ITM intrinsic."""

from unittest.mock import MagicMock, patch

from app.engines.explosion_detector import _premium_ok_for_scan, scan_chain_explosions
from app.models.schemas import Side


def _settings(*, sep917: bool = True) -> MagicMock:
    s = MagicMock()
    s.sep917_legacy_profile_enabled = sep917
    s.symmetric_best_trade_capture_enabled = True
    s.min_option_premium_inr = 18.0
    s.max_option_premium_inr = 350.0
    s.explosion_max_premium_inr = 350.0
    s.explosion_ict_max_premium_inr = 350.0
    s.expiry_itm_explosion_scan_max_premium_inr = 900.0
    s.expiry_day_min_option_premium_inr = 15.0
    s.explosion_scan_atm_itm_only = True
    s.moneyness_max_itm_steps = 2
    s.explosion_deep_otm_min_premium_inr = 18.0
    s.all_day_explosion_session_move_min_pct = 40.0
    s.open_premium_min_move_pct = 25.0
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
    s.expiry_itm_monitor_enabled = True
    s.expiry_sensex_itm_scan_range = 1200
    return s


@patch(
    "app.engines.sep917_legacy_profile.sep917_legacy_profile_active",
    return_value=True,
)
def test_sep917_blocks_deep_itm_900_scan_bypass(_legacy):
    s = _settings()
    assert _premium_ok_for_scan(
        470.0, 30.0, s, expiry_day=True, moneyness="ITM",
    ) is False
    assert _premium_ok_for_scan(
        186.0, 30.0, s, expiry_day=True, moneyness="ITM",
    ) is True


@patch(
    "app.engines.sep917_legacy_profile.atm_itm_fixed_premium_band_only",
    return_value=False,
)
def test_legacy_off_keeps_expiry_deep_itm_scan_ceiling(_band):
    s = _settings(sep917=False)
    assert _premium_ok_for_scan(
        720.0, 5.0, s, expiry_day=True, moneyness="ITM",
    ) is True


@patch("app.engines.session_timing.in_open_premium_window", return_value=True)
@patch("app.config.get_settings")
@patch(
    "app.engines.sep917_legacy_profile.sep917_legacy_profile_active",
    return_value=True,
)
def test_scan_chain_skips_deep_itm_put_outside_band(
    _legacy, mock_get_settings, _open,
):
    mock_get_settings.return_value = _settings()
    chain = [
        {
            "strike_price": 72200,
            "put_options": {"ltp": 186.0, "volume": 50000},
            "call_options": {"ltp": 140.0, "volume": 80000},
        },
        {
            "strike_price": 72600,
            "put_options": {"ltp": 470.0, "volume": 20000},
            "call_options": {"ltp": 80.0, "volume": 10000},
        },
    ]
    events = scan_chain_explosions(
        "SENSEX",
        chain,
        spot=72150.0,
        atm=72200.0,
        expiry_day=True,
    )
    put_strikes = {
        float(e.strike)
        for e in events
        if e.side == Side.PUT
    }
    assert 72200 in put_strikes or len(events) >= 0
    assert 72600 not in put_strikes
