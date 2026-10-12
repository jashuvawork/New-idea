"""Oct 12 RCA — open index flip OTM + entry-window relief (CE/PE symmetric hooks)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.explosion_entry_guards import explosion_entry_window_blocked
from app.engines.oct_open_index_flip_otm import oct_open_index_flip_otm_entry_ok
from app.models.schemas import MarketPhase, Side, SpotChart, SymbolSnapshot
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _frozen_settings(**kwargs):
    base = dict(
        october_frozen_profile_enabled=True,
        live_paper_parity_enabled=True,
        paper_live_parity_enabled=True,
        oct_paper_open_moment_pad_waiver_enabled=True,
        index_rally_side_flip_enabled=True,
        explosion_shallow_otm_entry_enabled=False,
        oct_open_index_flip_max_otm_steps=2,
        oct_open_index_flip_min_pad_pct=3.0,
    )
    base.update(kwargs)
    return settings_mock(**base)


def _snap(symbol: str = "NIFTY", spot: float = 22630.0, atm: float = 22650.0):
    chart = SpotChart(
        rsi=38.0,
        momentum5Pct=-0.12,
        macdBias="BEARISH",
        macdHistogram=-0.5,
    )
    return SymbolSnapshot(
        symbol=symbol,
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=spot,
        atmStrike=atm,
        sessionHigh=spot + 80,
        sessionLow=spot - 20,
        spotChart=chart,
    )


@patch("app.config.get_settings")
@patch("app.engines.oct_open_index_flip_otm._in_open_premium_window", return_value=True)
@patch("app.engines.index_rally_side_flip.index_rally_side_flip_bypass")
def test_put_open_index_flip_allows_two_step_otm(mock_bypass, _open, mock_settings):
    mock_settings.return_value = _frozen_settings()
    mock_bypass.return_value = (True, "index_slide_side_flip", {"mode": "slide"})
    alert = {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 22550.0,
        "tier": "ELITE",
        "momentType": "v_rip_session_low",
        "armedBaseLaunch": True,
        "explosionScore": 100.0,
    }
    snap = _snap()
    assert oct_open_index_flip_otm_entry_ok(alert, snap) is True


@patch("app.config.get_settings")
@patch("app.engines.oct_open_index_flip_otm._in_open_premium_window", return_value=True)
@patch("app.engines.index_rally_side_flip.index_rally_side_flip_bypass")
def test_put_open_flip_rejects_deep_otm(mock_bypass, _open, mock_settings):
    mock_settings.return_value = _frozen_settings(oct_open_index_flip_max_otm_steps=2)
    mock_bypass.return_value = (True, "index_slide_side_flip", {})
    alert = {
        "symbol": "NIFTY",
        "side": "PUT",
        "strike": 22400.0,
        "tier": "ELITE",
        "momentType": "armed_base_launch",
        "armedBaseLaunch": True,
    }
    snap = _snap()
    assert oct_open_index_flip_otm_entry_ok(alert, snap) is False


@patch("app.config.get_settings")
@patch("app.engines.oct_open_index_flip_otm._in_open_premium_window", return_value=True)
@patch("app.engines.index_rally_side_flip.index_rally_side_flip_bypass")
def test_call_open_index_flip_otm_mirror(mock_bypass, _open, mock_settings):
    mock_settings.return_value = _frozen_settings()
    mock_bypass.return_value = (True, "index_rally_side_flip", {"mode": "rally"})
    alert = {
        "symbol": "NIFTY",
        "side": "CALL",
        "strike": 22750.0,
        "tier": "ELITE",
        "momentType": "v_rip_session_low",
        "vRipReady": True,
    }
    snap = _snap(spot=22630.0, atm=22650.0)
    assert oct_open_index_flip_otm_entry_ok(alert, snap) is True


@patch("app.engines.explosion_entry_guards.get_settings")
@patch("app.engines.oct_open_index_flip_otm._in_open_premium_window", return_value=True)
@patch("app.engines.live_paper_parity.trading_rules_match_paper", return_value=True)
@patch("app.engines.index_rally_side_flip.index_rally_side_flip_bypass")
def test_entry_window_relax_at_four_pct_pad(mock_bypass, _parity, _open, mock_settings):
    mock_settings.return_value = _frozen_settings()
    mock_bypass.return_value = (True, "index_slide_side_flip", {})
    from types import SimpleNamespace

    event = SimpleNamespace(tier="ELITE", side=Side.PUT, symbol="SENSEX")
    ict = SimpleNamespace(armed_base_launch=True)
    with patch(
        "app.engines.explosion_entry_guards.effective_local_base_move_pct",
        return_value=4.0,
    ):
        with patch(
            "app.engines.explosion_entry_guards.entry_window_bounds",
            return_value=(15.0, 65.0),
        ):
            alert = {
                "symbol": "SENSEX",
                "side": "PUT",
                "tier": "ELITE",
                "momentType": "armed_base_launch",
                "armedBaseLaunch": True,
            }
            snap = _snap(symbol="SENSEX", spot=72100.0, atm=72200.0)
            blocked, reason = explosion_entry_window_blocked(
                event,
                ict=ict,
                alert=alert,
                snap=snap,
            )
    assert blocked is False, reason


def test_oct1_put_vrip_armed_open_waive():
    from app.engines.oct1_pad_location import oct1_open_moment_pad_waived

    with patch("app.engines.live_paper_parity.trading_rules_match_paper", return_value=True):
        with patch("app.engines.session_timing.in_open_premium_window", return_value=True):
            ok, tag = oct1_open_moment_pad_waived(
                "PUT",
                {
                    "momentType": "v_rip_session_low",
                    "tier": "ELITE",
                    "armedBaseLaunch": True,
                },
                settings=_frozen_settings(),
            )
    assert ok is True
    assert tag == "oct_open_put_vrip_armed_waive"
