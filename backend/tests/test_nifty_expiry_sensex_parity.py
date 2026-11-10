"""NIFTY expiry mirrors SENSEX expiry book when parity flag is on."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.best_trade_policy import expiry_cheap_otm_entry_blocked
from app.engines.expiry_day_guards import resolve_expiry_itm_scan_range
from app.engines.nifty_expiry_sensex_parity import resolve_nifty_expiry_max_premium_inr
from app.engines.premium_filter import resolve_premium_band_limits
from app.models.schemas import Side, SymbolSnapshot
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _nifty_expiry_snap() -> SymbolSnapshot:
    today = datetime.now(IST).strftime("%Y-%m-%d")
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST).isoformat(),
        marketPhase="LIVE_MARKET",
        dataAvailable=True,
        optionExpiry=today,
        spotPrice=25000.0,
        atmStrike=25000.0,
    )


@patch("app.engines.expiry_day_guards._today_str")
def test_nifty_expiry_blocks_all_otm_like_sensex(mock_today):
    mock_today.return_value = datetime.now(IST).strftime("%Y-%m-%d")
    s = settings_mock(nifty_expiry_sensex_parity_enabled=True)
    snap = _nifty_expiry_snap()
    cand = type(
        "C",
        (),
        {
            "mode": "explosion",
            "symbol": "NIFTY",
            "side": Side.CALL,
            "strike": 25100.0,
            "premium": 45.0,
            "alert": {},
            "explosion_event": None,
        },
    )()
    blocked, reason = expiry_cheap_otm_entry_blocked(cand, snap, {}, settings=s)
    assert blocked is True
    assert reason == "best_trade_block_expiry_otm_itm_atm_only"


@patch("app.engines.expiry_day_guards._today_str")
def test_nifty_expiry_premium_near_strike_not_sensex_650(mock_today):
    mock_today.return_value = datetime.now(IST).strftime("%Y-%m-%d")
    s = settings_mock(nifty_expiry_sensex_parity_enabled=True)
    snap = _nifty_expiry_snap()
    lo, hi = resolve_premium_band_limits(snap=snap, settings=s)
    assert hi == 350.0
    hi2 = resolve_nifty_expiry_max_premium_inr(default_max=350.0, snap=snap, settings=s)
    assert hi2 == 350.0
    lo_tight, hi_lift = resolve_premium_band_limits(
        snap=snap,
        settings=settings_mock(
            nifty_expiry_sensex_parity_enabled=True,
            max_option_premium_inr=175.0,
        ),
    )
    assert hi_lift == 250.0
    assert lo_tight == 10.0


@patch("app.engines.expiry_day_guards._today_str")
def test_nifty_expiry_premium_min_coil(mock_today):
    mock_today.return_value = datetime.now(IST).strftime("%Y-%m-%d")
    s = settings_mock(nifty_expiry_sensex_parity_enabled=True)
    snap = _nifty_expiry_snap()
    lo, _ = resolve_premium_band_limits(
        mode="explosion", snap=snap, settings=s
    )
    assert lo <= 10.0


def test_nifty_expiry_scan_range_1200():
    s = settings_mock(nifty_expiry_sensex_parity_enabled=True)
    with patch("app.engines.expiry_day_guards.get_settings", return_value=s):
        assert resolve_expiry_itm_scan_range("NIFTY") == 1200.0
    s2 = settings_mock(nifty_expiry_sensex_parity_enabled=False)
    with patch("app.engines.expiry_day_guards.get_settings", return_value=s2):
        assert resolve_expiry_itm_scan_range("NIFTY") == 800.0


def test_parity_off_keeps_legacy_nifty_otm_band():
    s = settings_mock(nifty_expiry_sensex_parity_enabled=False)
    snap = _nifty_expiry_snap()
    with patch(
        "app.engines.expiry_day_guards.is_symbol_expiry_day",
        return_value=True,
    ):
        blocked, reason = expiry_cheap_otm_entry_blocked(
            type(
                "C",
                (),
                {
                    "mode": "explosion",
                    "symbol": "NIFTY",
                    "side": Side.PUT,
                    "strike": 24900.0,
                    "premium": 35.0,
                    "alert": {},
                },
            )(),
            snap,
            {},
            settings=s,
        )
        assert blocked is True
        assert reason == "best_trade_block_expiry_cheap_otm"
