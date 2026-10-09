"""Open rip ELITE must reach selector despite Sep917 OTM tradeable wipe."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.engines.open_rip_selector import (
    open_rip_elite_tradeable_preserve,
    open_rip_selector_lift_waiver,
)
from app.engines.trade_selector import _high_signal_pre_candidate_skip_reason
from app.models.schemas import AutoTraderState, MarketPhase, SymbolSnapshot
from tests.mock_defaults import settings_mock

IST = ZoneInfo("Asia/Kolkata")


def _otm_elite_open_rip_alert() -> dict:
    return {
        "tradeable": False,
        "tier": "ELITE",
        "side": "CALL",
        "strike": 22600.0,
        "premium": 95.0,
        "explosionScore": 100.0,
        "velocity3s": 2.0,
        "ictVRipReady": True,
        "momentType": "v_rip_session_low",
        "localBaseMovePct": 14.0,
    }


def _snap(alerts: list[dict]) -> SymbolSnapshot:
    return SymbolSnapshot(
        symbol="NIFTY",
        timestamp=datetime.now(IST),
        marketPhase=MarketPhase.LIVE_MARKET,
        dataAvailable=True,
        spot=22380.0,
        atmStrike=22400.0,
        explosionAlerts=alerts,
    )


@patch("app.engines.session_timing.in_open_premium_window", return_value=True)
def test_open_rip_preserve_hot_otm_elite(_window):
    s = settings_mock(october_frozen_profile_enabled=True)
    assert open_rip_elite_tradeable_preserve(_otm_elite_open_rip_alert(), settings=s)


@patch("app.engines.session_timing.in_open_premium_window", return_value=True)
def test_selector_skip_reason_not_not_tradeable_for_open_rip_otm(_window):
    settings = settings_mock(
        october_frozen_profile_enabled=True,
        enable_live_trading=True,
        auto_trading_enabled=True,
        live_paper_parity_enabled=True,
        explosion_shallow_otm_entry_enabled=False,
        sep917_legacy_profile_enabled=True,
    )
    alert = _otm_elite_open_rip_alert()
    snap = _snap([alert])
    state = AutoTraderState()
    with patch("app.engines.trade_selector.get_settings", return_value=settings):
        reason = _high_signal_pre_candidate_skip_reason(
            "NIFTY", alert, snap, state, settings,
        )
    assert reason != "explosion_not_tradeable"


@patch("app.engines.session_timing.in_open_premium_window", return_value=True)
def test_open_rip_lift_waiver_frozen_live(_window):
    s = settings_mock(
        october_frozen_profile_enabled=True,
        enable_live_trading=True,
        auto_trading_enabled=True,
    )
    assert open_rip_selector_lift_waiver(
        _otm_elite_open_rip_alert(),
        _snap([]),
        AutoTraderState(),
        settings=s,
    )
